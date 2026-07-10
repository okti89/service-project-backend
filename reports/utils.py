import io
import os
from pathlib import Path

import reportlab
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
        }
    return {
        'name': 'Servis Asistanı',
        'address': '',
        'phone': '',
        'email': '',
    }


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
