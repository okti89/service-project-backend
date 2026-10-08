"""Corporate A4 alternative to the existing receipt service form.

Call generate_service_form_a4_pdf(service) from a future download endpoint.
The existing receipt generator and its endpoints are intentionally independent.
"""

import io

from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import pdf_utils


NAVY = colors.HexColor('#143455')
PALE = colors.HexColor('#eaf1f7')
RULE = colors.HexColor('#a5b7c7')
INK = colors.HexColor('#182532')
MUTED = colors.HexColor('#526171')


class _PageNumberCanvas(canvas.Canvas):
    """Write page/total counters after the document's final page is known."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._page_states = []

    def showPage(self):
        self._page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self._page_states)
        for state in self._page_states:
            self.__dict__.update(state)
            self.saveState()
            self.setFillColor(MUTED)
            self.setFont(pdf_utils.FONT_REGULAR, 8)
            self.drawRightString(A4[0] - 14 * mm, 10 * mm, f'{self._pageNumber} / {page_count}')
            self.restoreState()
            super().showPage()
        super().save()


def generate_service_form_a4_pdf(service):
    """Return an A4 PDF BytesIO without changing data or the receipt format."""
    pdf_utils._register_fonts()
    # Prefer the service's tenant, even when it has no linked customer/technician.
    tenant = getattr(service, 'tenant', None) or pdf_utils._service_tenant(service)
    config = pdf_utils.CompanyConfig.objects.filter(tenant=tenant).first() if tenant else None
    font = pdf_utils.FONT_REGULAR
    bold = pdf_utils.FONT_BOLD
    width = A4[0] - 28 * mm
    receipt_no = str(service.receipt_number or service.id)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=20 * mm,
        title=f'Servis Formu - {receipt_no}', author=pdf_utils._company_name(config),
    )
    body = ParagraphStyle('A4Body', fontName=font, fontSize=9, leading=12, textColor=INK)
    label = ParagraphStyle('A4Label', parent=body, fontName=bold, textColor=NAVY)
    section = ParagraphStyle('A4Section', parent=label, fontSize=10, leading=13)
    right = ParagraphStyle('A4Right', parent=body, alignment=2)
    center = ParagraphStyle('A4Center', parent=body, alignment=1)

    def text(value, style=body):
        return Paragraph(pdf_utils._text(value).replace('\n', '<br/>'), style)

    def table(rows, widths, header=False, spans=(), repeat=0, minimum_heights=None):
        result = Table(rows, colWidths=widths, repeatRows=repeat,
                       minRowHeights=minimum_heights, splitByRow=1, splitInRow=1)
        commands = [
            ('GRID', (0, 0), (-1, -1), 0.5, RULE),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 9),
            ('RIGHTPADDING', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]
        if header:
            commands.append(('BACKGROUND', (0, 0), (-1, 0), PALE))
        for start, end in spans:
            commands.append(('SPAN', start, end))
        result.setStyle(TableStyle(commands))
        return result

    def heading(title):
        result = table([[text(title, section)]], [width], header=True)
        result.keepWithNext = True
        return result

    elements = []
    company_style = ParagraphStyle('A4Company', parent=label, fontSize=14, leading=18)
    contact_style = ParagraphStyle('A4Contact', parent=body, fontSize=8, leading=11, textColor=MUTED)
    logo = pdf_utils._logo_flowable(config)
    brand = [text(pdf_utils._company_name(config), company_style)]
    contact = ' | '.join(str(value) for value in [
        getattr(config, 'phone_number', None), getattr(config, 'email', None),
    ] if value)
    if contact:
        brand.append(text(contact, contact_style))
    if logo:
        left_header = Table([[logo, brand]], colWidths=[40 * mm, width * 0.6 - 40 * mm])
        left_header.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
    else:
        left_header = brand
    title_style = ParagraphStyle('A4Title', parent=label, fontSize=21, leading=25, alignment=2)
    metadata = [text('SERVİS FORMU', title_style), Spacer(1, 5),
                text(f'Kayıt No: {receipt_no}', right),
                text(f'Tarih: {pdf_utils._service_date(service)}', right)]
    header = Table([[left_header, metadata]], colWidths=[width * 0.6, width * 0.4])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 1.5, NAVY),
    ]))
    elements.extend([header, Spacer(1, 12), heading('MÜŞTERİ VE SERVİS BİLGİLERİ')])
    customer_table = table([
        [text('Müşteri', label), text(service.customer_full_name), text('Telefon', label), text(service.customer_phone)],
        [text('Adres', label), text(service.customer_address, body), '', ''],
        [text('Durum', label), text(pdf_utils._service_status_label(service)), text('Teknisyen', label), text(pdf_utils._technician_name(service))],
    ], [width * 0.16, width * 0.37, width * 0.16, width * 0.31], spans=[((1, 1), (3, 1))])
    customer_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), PALE),
                                       ('BACKGROUND', (2, 0), (2, 0), PALE),
                                       ('BACKGROUND', (2, 2), (2, 2), PALE)]))
    elements.extend([customer_table, Spacer(1, 12), heading('CİHAZ BİLGİLERİ')])
    device_rows = [[
        [text('Cihaz', label), text(pdf_utils._device_type_name(service))],
        [text('Marka', label), text(pdf_utils._device_brand_name(service))],
        [text('Model', label), text(pdf_utils._device_model_name(service))],
    ]]
    device_spans = []
    if service.warranty_months:
        device_rows.append([text(f'Garanti Süresi: {service.warranty_months} Ay', label), '', ''])
        device_spans.append(((0, 1), (2, 1)))
    elements.extend([table(device_rows, [width / 3] * 3, spans=device_spans), Spacer(1, 12),
                     heading('ARIZA VE AÇIKLAMA')])
    description_table = table([
        [text('Arıza Açıklaması', label), text(service.fault_description)],
        [text('Servis Açıklaması', label), text(service.description)],
    ], [width * 0.23, width * 0.77])
    description_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), PALE)]))
    elements.extend([description_table, Spacer(1, 12), heading('YAPILAN İŞLEMLER')])

    amount_width = width * 0.24 - 18

    def amount(value, base_size=9, available_width=amount_width):
        formatted = pdf_utils._money(value)
        size = min(base_size, (available_width - 1) * base_size / max(1, pdfmetrics.stringWidth(formatted, bold, base_size)))
        style = ParagraphStyle('A4Amount', parent=right, fontName=bold, fontSize=size,
                               leading=max(base_size + 3, size + 3), splitLongWords=False)
        return Paragraph(pdf_utils._text(formatted).replace(' ', '&nbsp;'), style)

    item_rows = [[text('No', label), text('İşlem / Parça', label), text('Adet', label), text('Tutar', label)]]
    total_price = 0.0
    for index, item in enumerate(service.items.all(), 1):
        price = pdf_utils._to_float(getattr(item, 'total_price', 0))
        total_price += price
        item_rows.append([text(index, center), text(pdf_utils._item_label(item)),
                          text(getattr(item, 'quantity', 1), center), amount(price)])
    if len(item_rows) == 1:
        item_rows.append([text('-', center), text('İşlem / parça eklenmedi'), text('-', center), amount(0)])
    elements.append(table(item_rows, [width * 0.07, width * 0.57, width * 0.12, width * 0.24],
                          header=True, repeat=1))
    total = table([[text('TOPLAM', section), amount(total_price, 14, width * 0.24 - 18)]],
                  [width * 0.16, width * 0.24], header=True)
    total_row = Table([['', total]], colWidths=[width * 0.6, width * 0.4])
    total_row.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.extend([total_row, Spacer(1, 14)])

    latest_signature = service.signatures.order_by('-created_at').first()
    customer_signature = pdf_utils._signature_flowable(getattr(latest_signature, 'customer_signature', None))
    technician_signature = pdf_utils._signature_flowable(getattr(latest_signature, 'technician_signature', None))
    signature_width = (width - 12) / 2
    signature_cards = []
    for title, signature in [('Müşteri İmzası', customer_signature), ('Teknisyen İmzası', technician_signature)]:
        card = table([[text(title, label)], [signature or '']], [signature_width],
                     header=True, minimum_heights=[25, 52])
        card.setStyle(TableStyle([('ALIGN', (0, 1), (0, 1), 'CENTER'), ('VALIGN', (0, 1), (0, 1), 'MIDDLE')]))
        signature_cards.append(card)
    signatures = Table([[signature_cards[0], '', signature_cards[1]]], colWidths=[signature_width, 12, signature_width])
    signatures.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    barcode = code128.Code128(receipt_no.replace(' ', ''), barHeight=11 * mm, barWidth=0.45)
    if barcode.width > width:
        barcode = code128.Code128(receipt_no.replace(' ', ''), barHeight=11 * mm,
                                 barWidth=0.45 * (width - 40) / max(1, barcode.width))
    barcode_table = Table([[barcode]], colWidths=[width], style=[('ALIGN', (0, 0), (-1, -1), 'CENTER')])
    footer_style = ParagraphStyle('A4Footer', parent=center, fontSize=8, leading=11, textColor=MUTED)
    elements.append(KeepTogether([signatures, Spacer(1, 12), barcode_table,
                                  text(receipt_no, footer_style), Spacer(1, 5),
                                  text('Teşekkür ederiz. Tekrar görüşmek üzere.', footer_style)]))
    doc.build(elements, canvasmaker=_PageNumberCanvas)
    buffer.seek(0)
    return buffer
