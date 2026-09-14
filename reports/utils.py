import io
import os
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config.models import CompanyConfig

_font_registered = False
FONT_REGULAR = 'Helvetica'
FONT_BOLD = 'Helvetica-Bold'


def _pick_first_existing(paths):
    for path in paths:
        if path and os.path.exists(path):
            return path
    return None


def _register_fonts():
    global _font_registered, FONT_REGULAR, FONT_BOLD
    if _font_registered:
        return

    reportlab_fonts_dir = Path(reportlab.__file__).resolve().parent / 'fonts'

    regular_candidates = [
        settings.BASE_DIR / 'reporting' / 'fonts' / 'Roboto-Regular.ttf',
        settings.BASE_DIR / 'reports' / 'fonts' / 'Roboto-Regular.ttf',
        Path('C:/Windows/Fonts/arial.ttf'),
        Path('C:/Windows/Fonts/calibri.ttf'),
        reportlab_fonts_dir / 'Vera.ttf',
    ]
    bold_candidates = [
        settings.BASE_DIR / 'reporting' / 'fonts' / 'Roboto-Bold.ttf',
        settings.BASE_DIR / 'reports' / 'fonts' / 'Roboto-Bold.ttf',
        Path('C:/Windows/Fonts/arialbd.ttf'),
        Path('C:/Windows/Fonts/calibrib.ttf'),
        reportlab_fonts_dir / 'VeraBd.ttf',
    ]

    regular_path = _pick_first_existing(regular_candidates)
    bold_path = _pick_first_existing(bold_candidates)

    if regular_path:
        pdfmetrics.registerFont(TTFont('TurkishFont', str(regular_path)))
        FONT_REGULAR = 'TurkishFont'

    if bold_path:
        pdfmetrics.registerFont(TTFont('TurkishFont-Bold', str(bold_path)))
        FONT_BOLD = 'TurkishFont-Bold'
    elif regular_path:
        FONT_BOLD = 'TurkishFont'

    if regular_path:
        pdfmetrics.registerFontFamily(
            'TurkishFont',
            normal='TurkishFont',
            bold=FONT_BOLD,
            italic='TurkishFont',
            boldItalic=FONT_BOLD,
        )

    _font_registered = True


def _safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_currency(value):
    val_float = _safe_float(value)
    parts = f"{val_float:.2f}".split('.')
    int_part = ""
    for idx, char in enumerate(reversed(parts[0])):
        if idx > 0 and idx % 3 == 0:
            int_part = "." + int_part
        int_part = char + int_part
    return f"{int_part},{parts[1]} TL"


def _get_company_info(tenant=None):
    config_qs = CompanyConfig.objects.all()
    if tenant is not None:
        config_qs = config_qs.filter(tenant=tenant)
    config = config_qs.first()
    if config:
        return {
            'name': config.name,
            'address': config.address or '',
            'phone': config.phone_number or '',
            'email': config.email or '',
            'logo': config.logo,
        }
    return {
        'name': 'Servis Asistanı',
        'address': '',
        'phone': '',
        'email': '',
        'logo': None,
    }


def _company_logo_flowable(company):
    logo = company.get('logo') if company else None
    if not logo:
        return None
    try:
        if hasattr(logo, 'path') and logo.path and os.path.exists(logo.path):
            return Image(logo.path, width=32, height=32, kind='proportional')
    except (NotImplementedError, ValueError, OSError):
        pass
    try:
        logo.open('rb')
        data = io.BytesIO(logo.read())
        logo.close()
        return Image(data, width=32, height=32, kind='proportional')
    except Exception:
        return None


def generate_general_performance_pdf(data, tenant=None):
    _register_fonts()
    company = _get_company_info(tenant=tenant)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    elements = []

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'TurkishTitle',
        parent=styles['Heading1'],
        fontName=FONT_BOLD,
        fontSize=22,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=0,
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        'TurkishSubtitle',
        parent=styles['Normal'],
        fontName=FONT_REGULAR,
        fontSize=10,
        textColor=colors.HexColor('#64748b'),
        alignment=0,
        spaceAfter=24,
    )
    header_style = ParagraphStyle(
        'CompanyHeader',
        parent=styles['Normal'],
        fontName=FONT_BOLD,
        fontSize=13,
        textColor=colors.HexColor('#1e40af'),
        alignment=2,
    )
    contact_style = ParagraphStyle(
        'ContactStyle',
        parent=styles['Normal'],
        fontName=FONT_REGULAR,
        fontSize=8,
        textColor=colors.HexColor('#94a3b8'),
        alignment=2,
    )

    header_table = Table(
        [
            [Paragraph('SİSTEM PERFORMANS RAPORU', title_style), Paragraph(company['name'], header_style)],
            [
                Paragraph(f"Oluşturulma: {timezone.now().strftime('%d.%m.%Y %H:%M')}", subtitle_style),
                Paragraph(f"{company['phone']} | {company['email']}<br/>{company['address']}", contact_style),
            ],
        ],
        colWidths=[300, 215],
    )
    header_table.setStyle(
        TableStyle(
            [
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 12))
    elements.append(
        Table(
            [['']],
            colWidths=[515],
            rowHeights=[2],
            style=[('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1e40af'))],
        )
    )
    elements.append(Spacer(1, 24))

    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading3'],
        fontName=FONT_BOLD,
        fontSize=14,
        textColor=colors.HexColor('#334155'),
        spaceAfter=12,
    )
    elements.append(Paragraph('Özet Metrikler', section_style))

    total_revenue = _safe_float(data.get('total_revenue'))
    total_expenses = _safe_float(data.get('total_expenses'))
    total_profit = _safe_float(data.get('total_profit', data.get('net_profit')))

    table_data = [
        ['Operasyonel Metrikler', 'Değer'],
        ['Toplam Servis Sayısı', f"{data.get('total_services', 0)} Adet"],
        ['Tamamlanan Servis Sayısı', f"{data.get('total_completed_services', data.get('total_services_completed', 0))} Adet"],
        ['Bekleyen / Açık Servisler', f"{data.get('total_pending_services', data.get('total_services_pending', 0))} Adet"],
        ['İptal Edilen Servisler', f"{data.get('total_cancelled_services', 0)} Adet"],
        ['', ''],
        ['Finansal Metrikler', ''],
        ['Toplam Tahsilat (Brüt Gelir)', _format_currency(total_revenue)],
        ['Toplam Gider', _format_currency(total_expenses)],
        ['Net Kâr', _format_currency(total_profit)],
    ]

    table = Table(table_data, colWidths=[350, 165])
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('BACKGROUND', (0, 6), (-1, 6), colors.HexColor('#f1f5f9')),
                ('FONTNAME', (0, 6), (-1, 6), FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, -1), FONT_REGULAR),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('TOPPADDING', (0, 1), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
                ('BACKGROUND', (0, 9), (-1, 9), colors.HexColor('#ecfdf5')),
                ('TEXTCOLOR', (1, 9), (1, 9), colors.HexColor('#059669')),
                ('FONTNAME', (0, 9), (-1, 9), FONT_BOLD),
            ]
        )
    )
    elements.append(table)

    elements.append(Spacer(1, 80))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName=FONT_REGULAR,
        fontSize=8,
        textColor=colors.HexColor('#94a3b8'),
        alignment=1,
    )
    footer_text = f"Bu rapor sistem tarafından otomatik oluşturulmuştur. © {timezone.now().year} {company['name']}"
    elements.append(Paragraph(footer_text, footer_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_daily_summary_pdf(data, tenant=None):
    """Generate the income-only daily service summary approved for the reports screen."""
    _register_fonts()
    company = _get_company_info(tenant=tenant)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=32, leftMargin=32, topMargin=32, bottomMargin=32,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DailySummaryTitle', parent=styles['Heading1'], fontName=FONT_BOLD,
        fontSize=22, leading=27, textColor=colors.HexColor('#0f2f5f'), spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        'DailySummarySubtitle', parent=styles['Normal'], fontName=FONT_REGULAR,
        fontSize=10, leading=14, textColor=colors.HexColor('#64748b'), spaceAfter=16,
    )
    section_style = ParagraphStyle(
        'DailySummarySection', parent=styles['Heading2'], fontName=FONT_BOLD,
        fontSize=14, leading=18, textColor=colors.HexColor('#0f2f5f'), spaceBefore=16, spaceAfter=8,
    )
    label_style = ParagraphStyle(
        'DailySummaryLabel', parent=styles['Normal'], fontName=FONT_BOLD,
        fontSize=8.5, leading=11, textColor=colors.HexColor('#0f2f5f'),
    )
    metric_value_style = ParagraphStyle(
        'DailySummaryValue', parent=styles['Normal'], fontName=FONT_BOLD,
        fontSize=17, leading=21, textColor=colors.HexColor('#0f2f5f'),
    )
    normal_style = ParagraphStyle(
        'DailySummaryNormal', parent=styles['Normal'], fontName=FONT_REGULAR,
        fontSize=8.5, leading=11, textColor=colors.HexColor('#162033'),
    )
    right_style = ParagraphStyle(
        'DailySummaryRight', parent=normal_style, alignment=2,
    )

    report_date = data['report_date'].strftime('%d.%m.%Y')
    brand_title = Paragraph(f"<b>{escape(company['name'] or 'Servis Yönetimi')}</b><br/><font size=\"8\" color=\"#64748b\">Planlı servis, görünür operasyon</font>", subtitle_style)
    logo = _company_logo_flowable(company)
    brand_header = Table(
        [[logo or '', brand_title]],
        colWidths=[38 if logo else 0, 302 if logo else 340],
        style=[('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 4)],
    )
    header = Table([
        [
            brand_header,
            Paragraph(f"<b>Rapor No: GI-{data['report_date'].strftime('%Y%m%d')}</b><br/><font size=\"8\" color=\"#64748b\">Gelir ve tahsilat özeti</font>", right_style),
        ]
    ], colWidths=[340, 163])
    header.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEAFTER', (0, 0), (0, 0), 1, colors.HexColor('#9cb2d0')), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))

    def metric(label, value, background, value_color='#0f2f5f'):
        return Table([[Paragraph(label, label_style)], [Paragraph(value, ParagraphStyle('Metric' + label, parent=metric_value_style, textColor=colors.HexColor(value_color)))]], colWidths=[119], rowHeights=[22, 28], style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(background)), ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor(background)), ('LEFTPADDING', (0, 0), (-1, -1), 12), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))

    elements = [header, Spacer(1, 20), Paragraph('GÜNLÜK İCMAL RAPORU', title_style), Paragraph(f'{report_date} - Servis operasyonunun gün sonu görünümü', subtitle_style)]
    metrics = Table([[
        metric('Toplam Servis', str(data['total_services']), '#eff6ff'),
        metric('Toplam Ciro', _format_currency(data['total_revenue']), '#f1f7ff'),
        metric('Tahsil Edilen', _format_currency(data['collected_total']), '#ecfdf5', '#15803d'),
        metric('Açık Bakiye', _format_currency(data['outstanding_total']), '#fffbeb', '#a85b00'),
    ]], colWidths=[126, 126, 126, 126])
    metrics.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 6)]))
    elements.extend([metrics, Paragraph('Servis Hareketleri', section_style)])

    table_rows = [[
        'SERVİS NO', 'MÜŞTERİ', 'İŞLEM', 'TEKNİSYEN', 'ÖDEME', 'TUTAR',
    ]]
    for row in data['services']:
        table_rows.append([
            row['receipt_number'] or '-', row['customer_name'] or '-', row['operation_name'] or '-',
            row['technician_name'] or 'Atanmadı', row['payment_method'] or 'Bekliyor',
            _format_currency(row['total_amount']),
        ])
    if len(table_rows) == 1:
        table_rows.append(['-', 'Bu tarih için servis kaydı bulunmuyor.', '', '', '', _format_currency(0)])
    service_table = Table(table_rows, colWidths=[67, 105, 108, 82, 72, 69], repeatRows=1)
    service_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f2f5f')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD), ('FONTNAME', (0, 1), (-1, -1), FONT_REGULAR),
        ('FONTSIZE', (0, 0), (-1, 0), 7.5), ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#fafcff'), colors.white]),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#dbe5ef')), ('ALIGN', (-1, 1), (-1, -1), 'RIGHT'),
    ]))
    elements.append(service_table)

    elements.append(Spacer(1, 16))
    payment_rows = [['ÖDEME YÖNTEMİ', 'TAHSİLAT']]
    for item in data['payment_distribution']:
        payment_rows.append([item['name'], _format_currency(item['amount'])])
    if len(payment_rows) == 1:
        payment_rows.append(['Tahsilat bulunmuyor.', _format_currency(0)])
    revenue_rows = [
        ['GELİR ÖZETİ', ''], ['Toplam ciro', _format_currency(data['total_revenue'])],
        ['Tahsil edilen', _format_currency(data['collected_total'])], ['Açık bakiye', _format_currency(data['outstanding_total'])],
    ]
    left = Table(payment_rows, colWidths=[175, 75])
    right = Table(revenue_rows, colWidths=[175, 75])
    for summary_table in (left, right):
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eff6ff')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#0f2f5f')),
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD), ('FONTNAME', (0, 1), (-1, -1), FONT_REGULAR),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5), ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#dbe5ef')),
            ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7), ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ]))
    right.setStyle(TableStyle([('TEXTCOLOR', (1, 2), (1, 2), colors.HexColor('#15803d')), ('TEXTCOLOR', (1, 3), (1, 3), colors.HexColor('#a85b00')), ('FONTNAME', (1, 1), (1, -1), FONT_BOLD)]))
    elements.append(Table([[left, right]], colWidths=[251, 251], style=[('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 10)]))
    elements.append(Spacer(1, 16))
    total_strip = Table([[Paragraph('Günlük Tahsilat', ParagraphStyle('TotalLabel', parent=section_style, fontSize=15, spaceBefore=0, spaceAfter=0)), Paragraph(_format_currency(data['collected_total']), ParagraphStyle('TotalValue', parent=metric_value_style, fontSize=22, leading=26, alignment=2, textColor=colors.HexColor('#15803d')))]], colWidths=[250, 252], rowHeights=[50])
    total_strip.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eaf4ff')), ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#eaf4ff')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 16), ('RIGHTPADDING', (0, 0), (-1, -1), 16)]))
    elements.extend([total_strip, Spacer(1, 28), Paragraph(f'Bu rapor {escape(company["name"] or "Servis Yönetimi")} tarafından otomatik oluşturulmuştur.', ParagraphStyle('DailySummaryFooter', parent=normal_style, fontSize=7.5, textColor=colors.HexColor('#64748b'), alignment=1))])
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_daily_service_list_pdf(data, tenant=None):
    """Generate a schedule-first, multi-page daily service list PDF."""
    _register_fonts()
    company = _get_company_info(tenant=tenant)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28,
    )
    styles = getSampleStyleSheet()
    navy = colors.HexColor('#0f2f5f')
    blue = colors.HexColor('#2563eb')
    text = colors.HexColor('#14213d')
    muted = colors.HexColor('#64748b')
    normal = ParagraphStyle('DailyListNormal', parent=styles['Normal'], fontName=FONT_REGULAR, fontSize=8.5, leading=11, textColor=text)
    small = ParagraphStyle('DailyListSmall', parent=normal, fontSize=7.6, leading=9.5, textColor=muted)
    heading = ParagraphStyle('DailyListHeading', parent=styles['Heading1'], fontName=FONT_BOLD, fontSize=20, leading=24, textColor=navy)
    card_title = ParagraphStyle('DailyListCardTitle', parent=normal, fontName=FONT_BOLD, fontSize=9.5, leading=12, textColor=navy)
    card_value = ParagraphStyle('DailyListCardValue', parent=normal, fontName=FONT_BOLD, fontSize=22, leading=25, textColor=navy)
    service_name = ParagraphStyle('DailyListServiceName', parent=normal, fontName=FONT_BOLD, fontSize=10.2, leading=13, textColor=navy)
    time_style = ParagraphStyle('DailyListTime', parent=normal, fontName=FONT_BOLD, fontSize=17, leading=20, alignment=1, textColor=navy)
    tech_style = ParagraphStyle('DailyListTech', parent=normal, fontName=FONT_BOLD, fontSize=9.5, leading=12, alignment=1, textColor=navy)

    weekdays = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar']
    months = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']
    date_label = f"{data['report_date'].day} {months[data['report_date'].month]} {data['report_date'].year} - {weekdays[data['report_date'].weekday()]}"
    logo = _company_logo_flowable(company)
    brand = Paragraph(
        f"<b>{escape(company['name'] or 'Servis Yönetimi')}</b><br/><font size=\"8\" color=\"#9cb2d0\">Günlük servis planlama</font>",
        ParagraphStyle('DailyListBrand', parent=normal, fontName=FONT_BOLD, fontSize=15, leading=19, textColor=colors.white),
    )
    left_header = Table([[logo or '', brand]], colWidths=[38 if logo else 0, 235 if logo else 273], style=[
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ])
    technician_name = data.get('technician_name') or ''
    report_title = 'TEKNİSYENE ÖZEL SERVİS LİSTESİ' if technician_name else 'GÜNLÜK SERVİS LİSTESİ'
    report_number_prefix = 'TSL' if technician_name else 'GSL'
    right_header = Paragraph(
        f"<b>{report_title}</b><br/><font size=\"10\">{date_label}</font><br/><font size=\"7.5\" color=\"#cbd5e1\">Rapor No: {report_number_prefix}-{data['report_date'].strftime('%Y%m%d')}</font>",
        ParagraphStyle('DailyListHeaderRight', parent=normal, fontName=FONT_BOLD, fontSize=14, leading=18, alignment=2, textColor=colors.white),
    )
    header = Table([[left_header, right_header]], colWidths=[280, 247], rowHeights=[80])
    header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), navy), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 16), ('RIGHTPADDING', (0, 0), (-1, -1), 16),
    ]))

    def metric(label, value, background, value_color='#0f2f5f'):
        return Table([[Paragraph(label, card_title)], [Paragraph(str(value), ParagraphStyle(f'DailyListMetric{label}', parent=card_value, textColor=colors.HexColor(value_color)))]], colWidths=[125], rowHeights=[20, 28], style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(background)), ('BOX', (0, 0), (-1, -1), .4, colors.HexColor(background)),
            ('LEFTPADDING', (0, 0), (-1, -1), 11), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))

    elements = [header, Spacer(1, 14)]
    metrics = Table([[
        metric('Toplam Servis', data['total_services'], '#eff6ff'),
        metric('Planlandı', data['planned_count'], '#fff7ed', '#c2410c'),
        metric('Yolda / İşlemde', data['in_progress_count'], '#eff6ff', '#1d4ed8'),
        metric('Tamamlandı', data['completed_count'], '#ecfdf5', '#15803d'),
    ]], colWidths=[132, 132, 132, 132], style=[('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 7), ('VALIGN', (0, 0), (-1, -1), 'TOP')])
    elements.extend([metrics, Spacer(1, 16)])
    section_title = f'{escape(technician_name)} Servis Programı' if technician_name else 'Bugünün Servis Programı'
    section = Table([[Paragraph(section_title, ParagraphStyle('DailyListSection', parent=heading, fontSize=15, leading=19, textColor=colors.white))]], colWidths=[527], rowHeights=[38])
    section.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), navy), ('LEFTPADDING', (0, 0), (-1, -1), 16), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
    elements.append(section)
    elements.append(Spacer(1, 8))

    status_colors = {
        'completed': ('#dcfce7', '#15803d'),
        'in_progress': ('#dbeafe', '#1d4ed8'),
        'postponed': ('#f3e8ff', '#7e22ce'),
        'assigned': ('#fff7ed', '#c2410c'),
        'new': ('#fff7ed', '#c2410c'),
    }
    for row in data['services']:
        bg, status_color = status_colors.get(row['status_code'], ('#f1f5f9', '#475569'))
        status = Table([[Paragraph(escape(row['status_name']), ParagraphStyle(f"DailyListStatus{row['receipt_number']}", parent=normal, fontName=FONT_BOLD, fontSize=8.5, alignment=1, textColor=colors.HexColor(status_color)))]], colWidths=[93], rowHeights=[24], style=[
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(bg)), ('BOX', (0, 0), (-1, -1), .3, colors.HexColor(bg)), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ])
        detail_lines = [
            f"<b>Servis No:</b> {escape(row['receipt_number'])}",
            f"<b>{escape(row['customer_name'])}</b>",
            escape(row['customer_phone']),
            escape(row['customer_address']),
            f"<b>İşlem:</b> {escape(row['operation_name'])}",
        ]
        if row['device_name']:
            detail_lines.append(f"<b>Cihaz:</b> {escape(row['device_name'])}")
        details = Paragraph('<br/>'.join(detail_lines), service_name)
        technician = Paragraph(f"<font size=\"8\" color=\"#64748b\">TEKNİSYEN</font><br/>{escape(row['technician_name'])}", tech_style)
        service_card = Table([[Paragraph(row['time'], time_style), status, details, technician]], colWidths=[70, 104, 250, 103], rowHeights=[94])
        service_card.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.white), ('BOX', (0, 0), (-1, -1), .55, colors.HexColor('#dbe5ef')),
            ('LINEAFTER', (1, 0), (1, 0), .55, colors.HexColor('#bfdbfe')), ('LINEAFTER', (2, 0), (2, 0), .55, colors.HexColor('#dbe5ef')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (0, 0), (1, 0), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        elements.extend([service_card, Spacer(1, 7)])

    if not data['services']:
        empty = Table([[Paragraph('Bu tarih için planlanmış servis kaydı bulunmuyor.', ParagraphStyle('DailyListEmpty', parent=normal, alignment=1, textColor=muted))]], colWidths=[527], rowHeights=[70], style=[('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')), ('BOX', (0, 0), (-1, -1), .4, colors.HexColor('#dbe5ef')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')])
        elements.append(empty)

    elements.extend([Spacer(1, 15), Paragraph('Planlama notu: Servis öncesinde müşteri iletişim ve adres bilgilerini kontrol ediniz.', ParagraphStyle('DailyListFooter', parent=small, alignment=1, textColor=muted))])
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_technician_performance_pdf(data_list, tenant=None):
    _register_fonts()
    company = _get_company_info(tenant=tenant)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    elements = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TurkishTitle',
        parent=styles['Heading1'],
        fontName=FONT_BOLD,
        fontSize=22,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=0,
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        'TurkishSubtitle',
        parent=styles['Normal'],
        fontName=FONT_REGULAR,
        fontSize=10,
        textColor=colors.HexColor('#64748b'),
        alignment=0,
        spaceAfter=24,
    )

    elements.append(Paragraph('TEKNİSYEN PERFORMANS RAPORU', title_style))
    elements.append(Paragraph(f"Tarih: {timezone.now().strftime('%d.%m.%Y %H:%M')}", subtitle_style))
    elements.append(
        Table(
            [['']],
            colWidths=[515],
            rowHeights=[2],
            style=[('LINEBELOW', (0, 0), (-1, -1), 1, colors.HexColor('#1e40af'))],
        )
    )
    elements.append(Spacer(1, 24))

    table_data = [['Teknisyen Adı', 'Tamamlanan İş', 'Kazandırılan Ciro', 'Performans %']]
    total_revenue = sum(_safe_float(row.get('total_revenue_generated')) for row in data_list) or 1.0

    # Ciroya göre azalan sıralama yapalım
    sorted_data = sorted(
        data_list,
        key=lambda x: _safe_float(x.get('total_revenue_generated')),
        reverse=True
    )

    for row in sorted_data:
        revenue = _safe_float(row.get('total_revenue_generated'))
        percentage = (revenue / total_revenue) * 100
        table_data.append(
            [
                str(row.get('technician_name', '-')),
                str(row.get('completed_services_count', 0)),
                _format_currency(revenue),
                f'% {percentage:.1f}',
            ]
        )

    table = Table(table_data, colWidths=[200, 100, 120, 95])
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
                ('ALIGN', (0, 1), (0, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, -1), FONT_REGULAR),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('FONTSIZE', (0, 1), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('TOPPADDING', (0, 1), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#1e3a8a')),
            ]
        )
    )
    elements.append(table)

    elements.append(Spacer(1, 80))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName=FONT_REGULAR,
        fontSize=8,
        textColor=colors.HexColor('#94a3b8'),
        alignment=1,
    )
    footer_text = f"Firma: {company['name']} | Teknisyen Performans Verileri | © {timezone.now().year}"
    elements.append(Paragraph(footer_text, footer_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer
