import io
import os
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics.barcode import code128
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config.models import CompanyConfig


RECEIPT_WIDTH = 80 * mm
RECEIPT_MARGIN = 6 * mm

FONT_REGULAR = 'Helvetica'
FONT_BOLD = 'Helvetica-Bold'
_font_registered = False


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
        settings.BASE_DIR / 'services' / 'fonts' / 'Roboto-Regular.ttf',
        settings.BASE_DIR / 'reporting' / 'fonts' / 'Roboto-Regular.ttf',
        settings.BASE_DIR / 'reports' / 'fonts' / 'Roboto-Regular.ttf',
        Path('C:/Windows/Fonts/arial.ttf'),
        Path('C:/Windows/Fonts/calibri.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        reportlab_fonts_dir / 'Vera.ttf',
    ]
    bold_candidates = [
        settings.BASE_DIR / 'services' / 'fonts' / 'Roboto-Bold.ttf',
        settings.BASE_DIR / 'reporting' / 'fonts' / 'Roboto-Bold.ttf',
        settings.BASE_DIR / 'reports' / 'fonts' / 'Roboto-Bold.ttf',
        Path('C:/Windows/Fonts/arialbd.ttf'),
        Path('C:/Windows/Fonts/calibrib.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        reportlab_fonts_dir / 'VeraBd.ttf',
    ]

    regular_path = _pick_first_existing(regular_candidates)
    bold_path = _pick_first_existing(bold_candidates)

    if regular_path:
        pdfmetrics.registerFont(TTFont('ServiceTurkishFont', str(regular_path)))
        FONT_REGULAR = 'ServiceTurkishFont'

    if bold_path:
        pdfmetrics.registerFont(TTFont('ServiceTurkishFont-Bold', str(bold_path)))
        FONT_BOLD = 'ServiceTurkishFont-Bold'
    elif regular_path:
        FONT_BOLD = 'ServiceTurkishFont'

    if regular_path:
        pdfmetrics.registerFontFamily(
            'ServiceTurkishFont',
            normal='ServiceTurkishFont',
            bold=FONT_BOLD,
            italic='ServiceTurkishFont',
            boldItalic=FONT_BOLD,
        )

    _font_registered = True

STATUS_LABELS = {
    'new': 'Yeni',
    'assigned': 'Atandı',
    'in_progress': 'İşlemde',
    'postponed': 'Ertelendi',
    'completed': 'Tamamlandı',
    'cancelled': 'İptal',
}


def _to_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _calculate_service_totals(service):
    total_price = 0.0
    total_paid = 0.0

    for item in service.items.all():
        total_price += _to_float(getattr(item, 'total_price', 0))

    for payment in service.payments.all():
        total_paid += _to_float(getattr(payment, 'amount', 0))

    remaining = total_price - total_paid
    if remaining < 0:
        remaining = 0.0

    return total_price, total_paid, remaining


def _money(value):
    amount = _to_float(value)
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} TL"


def _text(value, fallback='-'):
    value = str(value or '').strip()
    return escape(value) if value else fallback


def _service_tenant(service):
    customer_tenant = getattr(getattr(service, 'customer', None), 'tenant', None)
    if customer_tenant:
        return customer_tenant
    technician_user = getattr(getattr(service, 'technician', None), 'user', None)
    return getattr(technician_user, 'tenant', None)


def _company_config(service):
    tenant = _service_tenant(service)
    qs = CompanyConfig.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    return qs.first()


def _company_name(config):
    return getattr(config, 'name', None) or 'Servis Yönetim'


def _logo_flowable(config):
    logo = getattr(config, 'logo', None)
    if not logo:
        return None

    try:
        if hasattr(logo, 'path') and logo.path and os.path.exists(logo.path):
            return Image(logo.path, width=38 * mm, height=16 * mm, kind='proportional')
    except (NotImplementedError, ValueError, OSError):
        pass

    try:
        logo.open('rb')
        data = io.BytesIO(logo.read())
        logo.close()
        return Image(data, width=38 * mm, height=16 * mm, kind='proportional')
    except Exception:
        return None


def _signature_flowable(image_field):
    if not image_field:
        return None
    try:
        if hasattr(image_field, 'path') and image_field.path and os.path.exists(image_field.path):
            return Image(image_field.path, width=28 * mm, height=14 * mm, kind='proportional')
    except (NotImplementedError, ValueError, OSError):
        pass

    try:
        image_field.open('rb')
        data = io.BytesIO(image_field.read())
        image_field.close()
        return Image(data, width=28 * mm, height=14 * mm, kind='proportional')
    except Exception:
        return None


def _technician_name(service):
    technician = getattr(service, 'technician', None)
    user = getattr(technician, 'user', None)
    if user:
        full_name = user.get_full_name()
        return full_name or getattr(user, 'email', '') or str(user)
    return str(technician) if technician else '-'


def _device_type_name(service):
    parts = [
        getattr(getattr(service, 'device_type', None), 'name', None),
        getattr(getattr(service, 'device_brand', None), 'name', None),
        getattr(getattr(service, 'device_model', None), 'name', None),
    ]
    return ' '.join(str(part).strip() for part in parts if part) or '-'


def _device_type_name(service):
    return getattr(getattr(service, 'device_type', None), 'name', None) or '-'


def _device_brand_name(service):
    return getattr(getattr(service, 'device_brand', None), 'name', None) or '-'


def _device_model_name(service):
    return getattr(getattr(service, 'device_model', None), 'name', None) or '-'


def _service_date(service):
    value = getattr(service, 'scheduled_date', None) or getattr(service, 'created_at', None)
    if not value:
        return '-'
    value = timezone.localtime(value) if timezone.is_aware(value) else value
    return value.strftime('%d.%m.%Y %H:%M')


def _divider(width):
    table = Table([['']], colWidths=[width], rowHeights=[4])
    table.setStyle(
        TableStyle(
            [
                ('LINEBELOW', (0, 0), (-1, -1), 0.7, colors.HexColor('#d1d5db')),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _info_row(label, value, label_style, value_style, width):
    return Table(
        [[Paragraph(label, label_style), Paragraph(_text(value), value_style)]],
        colWidths=[24 * mm, width - (24 * mm)],
        style=[
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ],
    )


def _item_label(item):
    product_name = getattr(getattr(item, 'product', None), 'name', None)
    return item.name or product_name or item.description or 'Servis işlemi'


def generate_service_form_pdf(service):
    _register_fonts()
    font_regular = FONT_REGULAR
    font_bold = FONT_BOLD
    config = _company_config(service)

    styles = getSampleStyleSheet()
    usable_width = RECEIPT_WIDTH - (RECEIPT_MARGIN * 2)
    item_count = max(service.items.count(), 1)
    payment_count = service.payments.count()
    page_height = max(230 * mm, (185 + item_count * 15 + payment_count * 10) * mm)

    company_style = ParagraphStyle(
        'ReceiptCompany',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=15,
        leading=18,
        alignment=1,
        textColor=colors.HexColor('#0f2f5f'),
    )
    small_center_style = ParagraphStyle(
        'ReceiptSmallCenter',
        parent=styles['Normal'],
        fontName=font_regular,
        fontSize=7,
        leading=9,
        alignment=1,
        textColor=colors.HexColor('#334155'),
    )
    label_style = ParagraphStyle(
        'ReceiptLabel',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=8.8,
        leading=11,
        textColor=colors.HexColor('#111827'),
    )
    value_style = ParagraphStyle(
        'ReceiptValue',
        parent=styles['Normal'],
        fontName=font_regular,
        fontSize=8.8,
        leading=11,
        textColor=colors.HexColor('#111827'),
    )
    section_style = ParagraphStyle(
        'ReceiptSection',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor('#111827'),
        spaceAfter=2,
        leftIndent=0,
    )
    section_body_style = ParagraphStyle(
        'ReceiptSectionBody',
        parent=value_style,
        leftIndent=0,
    )
    operation_item_style = ParagraphStyle(
        'ReceiptOperationItem',
        parent=value_style,
        leftIndent=6,
    )
    total_label_style = ParagraphStyle(
        'ReceiptTotalLabel',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor('#111827'),
    )
    total_value_style = ParagraphStyle(
        'ReceiptTotalValue',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=14,
        leading=16,
        alignment=2,
        textColor=colors.HexColor('#111827'),
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(RECEIPT_WIDTH, page_height),
        rightMargin=RECEIPT_MARGIN,
        leftMargin=RECEIPT_MARGIN,
        topMargin=5 * mm,
        bottomMargin=6 * mm,
    )
    elements = []

    logo = _logo_flowable(config)
    if logo:
        elements.append(
            Table([[logo]], colWidths=[usable_width], style=[('ALIGN', (0, 0), (-1, -1), 'CENTER')])
        )
        elements.append(Spacer(1, 2))

    elements.append(Paragraph(_text(_company_name(config)), company_style))
    contact = ' | '.join(
        item for item in [
            getattr(config, 'phone_number', None),
            getattr(config, 'email', None),
        ]
        if item
    )
    if contact:
        elements.append(Paragraph(_text(contact), small_center_style))
    elements.append(Spacer(1, 5))

    receipt_no = service.receipt_number or str(service.id)
    elements.append(_info_row('Kayıt No', f': {receipt_no}', label_style, value_style, usable_width))
    elements.append(_info_row('Tarih', f': {_service_date(service)}', label_style, value_style, usable_width))
    elements.append(_divider(usable_width))

    elements.append(_info_row('Müşteri', f': {service.customer_full_name or "-"}', label_style, value_style, usable_width))
    elements.append(_info_row('Telefon', f': {service.customer_phone or "-"}', label_style, value_style, usable_width))
    elements.append(_info_row('Cihaz', f': {_device_type_name(service)}', label_style, value_style, usable_width))
    elements.append(_info_row('Marka', f': {_device_brand_name(service)}', label_style, value_style, usable_width))
    elements.append(_info_row('Model', f': {_device_model_name(service)}', label_style, value_style, usable_width))
    elements.append(_info_row('Arıza', f': {service.fault_description or "-"}', label_style, value_style, usable_width))
    elements.append(_info_row('Durum', f': {STATUS_LABELS.get(service.service_status, service.service_status or "-")}', label_style, value_style, usable_width))
    elements.append(_info_row('Teknisyen', f': {_technician_name(service)}', label_style, value_style, usable_width))
    elements.append(_divider(usable_width))

    elements.append(Paragraph('AÇIKLAMA', section_style))
    description = service.fault_description or 'Servis aciklamasi girilmedi.'
    elements.append(Paragraph(_text(description), section_body_style))
    elements.append(Spacer(1, 2))
    elements.append(Paragraph('ADRES', section_style))
    address_text = service.customer_address or 'Adres bilgisi girilmedi.'
    elements.append(Paragraph(_text(address_text), section_body_style))
    elements.append(_divider(usable_width))

    items = service.items.all()
    elements.append(Paragraph('YAPILAN İŞLEMLER', section_style))
    item_rows = []
    for item in items:
        qty = int(_to_float(item.quantity) or 0)
        label = _item_label(item)
        if qty > 1:
            label = f"{label} x{qty}"
        item_rows.append([
            Paragraph(_text(label), operation_item_style),
            Paragraph(_money(getattr(item, 'total_price', 0)), value_style),
        ])
    if not item_rows:
        item_rows.append([Paragraph('İşlem / parça eklenmedi', value_style), Paragraph(_money(0), value_style)])

    item_table = Table(item_rows, colWidths=[usable_width - 25 * mm, 25 * mm])
    item_table.setStyle(
        TableStyle(
            [
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]
        )
    )
    elements.append(item_table)
    elements.append(_divider(usable_width))

    total_price, total_paid, remaining = _calculate_service_totals(service)

    total_table = Table(
        [[Paragraph('TOPLAM', total_label_style), Paragraph(_money(total_price), total_value_style)]],
        colWidths=[usable_width * 0.45, usable_width * 0.55],
        style=[
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ],
    )
    elements.append(total_table)
    elements.append(Spacer(1, 5))

    latest_signature = service.signatures.order_by('-created_at').first()
    customer_signature_img = _signature_flowable(getattr(latest_signature, 'customer_signature', None))
    technician_signature_img = _signature_flowable(getattr(latest_signature, 'technician_signature', None))
    if customer_signature_img or technician_signature_img:
        elements.append(_divider(usable_width))
        elements.append(Paragraph('İMZALAR', section_style))
        signature_rows = [[
            Paragraph('Müşteri İmzası', label_style),
            Paragraph('Teknisyen İmzası', label_style),
        ]]
        signature_rows.append([
            customer_signature_img or Paragraph('-', value_style),
            technician_signature_img or Paragraph('-', value_style),
        ])
        signature_table = Table(
            signature_rows,
            colWidths=[usable_width / 2, usable_width / 2],
            style=[
                ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
                ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ],
        )
        elements.append(signature_table)
        elements.append(Spacer(1, 4))

    barcode_value = str(receipt_no).replace(' ', '')
    barcode = code128.Code128(barcode_value, barHeight=18 * mm, barWidth=0.55)
    elements.append(
        Table([[barcode]], colWidths=[usable_width], style=[('ALIGN', (0, 0), (-1, -1), 'CENTER')])
    )
    elements.append(Paragraph(_text(receipt_no), small_center_style))
    elements.append(Spacer(1, 7))
    elements.append(Paragraph('Teşekkür ederiz.', small_center_style))
    elements.append(Paragraph('Tekrar görüşmek üzere.', small_center_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_warranty_certificate_pdf(warranty):
    _register_fonts()
    font_regular = FONT_REGULAR
    font_bold = FONT_BOLD
    service = warranty.service
    config = _company_config(service)

    styles = getSampleStyleSheet()
    usable_width = RECEIPT_WIDTH - (RECEIPT_MARGIN * 2)
    
    # Calculate approximate height based on coverage details lines
    coverage_lines = len(warranty.coverage_details.split('\n')) if warranty.coverage_details else 5
    page_height = max(180 * mm, (120 + coverage_lines * 5) * mm)

    company_style = ParagraphStyle(
        'ReceiptCompany',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=15,
        leading=18,
        alignment=1,
        textColor=colors.HexColor('#0f2f5f'),
    )
    title_style = ParagraphStyle(
        'ReceiptTitle',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=13,
        leading=16,
        alignment=1,
        textColor=colors.HexColor('#111827'),
    )
    small_center_style = ParagraphStyle(
        'ReceiptSmallCenter',
        parent=styles['Normal'],
        fontName=font_regular,
        fontSize=7,
        leading=9,
        alignment=1,
        textColor=colors.HexColor('#334155'),
    )
    label_style = ParagraphStyle(
        'ReceiptLabel',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=8.8,
        leading=11,
        textColor=colors.HexColor('#111827'),
    )
    value_style = ParagraphStyle(
        'ReceiptValue',
        parent=styles['Normal'],
        fontName=font_regular,
        fontSize=8.8,
        leading=11,
        textColor=colors.HexColor('#111827'),
    )
    section_style = ParagraphStyle(
        'ReceiptSection',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor('#111827'),
        spaceAfter=2,
        leftIndent=0,
    )
    coverage_style = ParagraphStyle(
        'ReceiptCoverage',
        parent=styles['Normal'],
        fontName=font_regular,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#374151'),
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(RECEIPT_WIDTH, page_height),
        rightMargin=RECEIPT_MARGIN,
        leftMargin=RECEIPT_MARGIN,
        topMargin=5 * mm,
        bottomMargin=6 * mm,
    )
    elements = []

    logo = _logo_flowable(config)
    if logo:
        elements.append(
            Table([[logo]], colWidths=[usable_width], style=[('ALIGN', (0, 0), (-1, -1), 'CENTER')])
        )
        elements.append(Spacer(1, 2))

    elements.append(Paragraph(_text(_company_name(config)), company_style))
    contact = ' | '.join(
        item for item in [
            getattr(config, 'phone_number', None),
            getattr(config, 'email', None),
        ]
        if item
    )
    if contact:
        elements.append(Paragraph(_text(contact), small_center_style))
    elements.append(Spacer(1, 5))
    
    elements.append(Paragraph('GARANTİ BELGESİ', title_style))
    elements.append(Spacer(1, 5))

    elements.append(_info_row('Belge No', f': {warranty.certificate_no}', label_style, value_style, usable_width))
    elements.append(_info_row('Servis No', f': {service.receipt_number or str(service.id)[:8]}', label_style, value_style, usable_width))
    elements.append(_divider(usable_width))

    elements.append(_info_row('Müşteri', f': {service.customer_full_name or "-"}', label_style, value_style, usable_width))
    elements.append(_info_row('Cihaz', f': {_device_type_name(service)}', label_style, value_style, usable_width))
    elements.append(_info_row('Marka', f': {_device_brand_name(service)}', label_style, value_style, usable_width))
    elements.append(_info_row('Model', f': {_device_model_name(service)}', label_style, value_style, usable_width))
    elements.append(_divider(usable_width))

    elements.append(_info_row('Başlangıç', f': {warranty.start_date.strftime("%d.%m.%Y")}', label_style, value_style, usable_width))
    elements.append(_info_row('Bitiş', f': {warranty.end_date.strftime("%d.%m.%Y")}', label_style, value_style, usable_width))
    elements.append(_info_row('Süre', f': {warranty.warranty_months} Ay', label_style, value_style, usable_width))
    elements.append(_divider(usable_width))

    elements.append(Paragraph('GARANTİ ŞARTLARI', section_style))
    elements.append(Spacer(1, 2))
    
    coverage_text = warranty.coverage_details or "Garanti detayları belirtilmedi."
    for line in coverage_text.split('\n'):
        if line.strip():
            elements.append(Paragraph(_text(line.strip()), coverage_style))
            elements.append(Spacer(1, 2))
    
    elements.append(_divider(usable_width))

    latest_signature = service.signatures.order_by('-created_at').first()
    customer_signature_img = _signature_flowable(getattr(latest_signature, 'customer_signature', None))
    technician_signature_img = _signature_flowable(getattr(latest_signature, 'technician_signature', None))
    
    signature_rows = [[
        Paragraph('Müşteri', small_center_style),
        Paragraph('Firma Yetkilisi', small_center_style),
    ]]
    signature_rows.append([
        customer_signature_img or Paragraph('-', small_center_style),
        technician_signature_img or Paragraph('-', small_center_style),
    ])
    signature_table = Table(
        signature_rows,
        colWidths=[usable_width / 2, usable_width / 2],
        style=[
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ],
    )
    elements.append(signature_table)
    elements.append(Spacer(1, 5))

    barcode_value = str(warranty.certificate_no).replace(' ', '')
    barcode = code128.Code128(barcode_value, barHeight=15 * mm, barWidth=0.55)
    elements.append(
        Table([[barcode]], colWidths=[usable_width], style=[('ALIGN', (0, 0), (-1, -1), 'CENTER')])
    )
    elements.append(Paragraph(_text(warranty.certificate_no), small_center_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer
