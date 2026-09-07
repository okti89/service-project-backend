import io

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config.models import CompanyConfig
from services import pdf_utils as service_pdf


NAVY = colors.HexColor("#0F2F5F")
BLUE = colors.HexColor("#2563EB")
SLATE_900 = colors.HexColor("#0F172A")
SLATE_700 = colors.HexColor("#334155")
SLATE_500 = colors.HexColor("#64748B")
SLATE_300 = colors.HexColor("#CBD5E1")
SLATE_200 = colors.HexColor("#E2E8F0")
SLATE_50 = colors.HexColor("#F8FAFC")


def _company_config(quote):
    return CompanyConfig.objects.filter(tenant=quote.tenant).order_by("-updated_at").first()


def _company_name(config):
    return getattr(config, "name", None) or "Servis Yönetimi"


def _company_contact(config):
    if not config:
        return []
    return [
        value
        for value in [
            getattr(config, "phone_number", None),
            getattr(config, "email", None),
        ]
        if value
    ]


def _build_styles(regular, bold):
    sample = getSampleStyleSheet()
    return {
        "company": ParagraphStyle("QuoteCompany", parent=sample["Normal"], fontName=bold, fontSize=14, leading=17, textColor=NAVY),
        "company_meta": ParagraphStyle("QuoteCompanyMeta", parent=sample["Normal"], fontName=regular, fontSize=7.5, leading=10, textColor=SLATE_500),
        "document_title": ParagraphStyle("QuoteDocumentTitle", parent=sample["Normal"], fontName=bold, fontSize=18, leading=21, alignment=2, textColor=SLATE_900),
        "document_subtitle": ParagraphStyle("QuoteDocumentSubtitle", parent=sample["Normal"], fontName=regular, fontSize=8, leading=10, alignment=2, textColor=SLATE_500),
        "section": ParagraphStyle("QuoteSection", parent=sample["Normal"], fontName=bold, fontSize=8, leading=10, textColor=NAVY, spaceAfter=5),
        "label": ParagraphStyle("QuoteLabel", parent=sample["Normal"], fontName=bold, fontSize=8, leading=10, textColor=SLATE_500),
        "value": ParagraphStyle("QuoteValue", parent=sample["Normal"], fontName=regular, fontSize=9, leading=12, textColor=SLATE_900),
        "value_bold": ParagraphStyle("QuoteValueBold", parent=sample["Normal"], fontName=bold, fontSize=9, leading=12, textColor=SLATE_900),
        "table_header": ParagraphStyle("QuoteTableHeader", parent=sample["Normal"], fontName=bold, fontSize=7.5, leading=9, textColor=colors.white),
        "table_header_right": ParagraphStyle("QuoteTableHeaderRight", parent=sample["Normal"], fontName=bold, fontSize=7.5, leading=9, alignment=2, textColor=colors.white),
        "table_text": ParagraphStyle("QuoteTableText", parent=sample["Normal"], fontName=regular, fontSize=8, leading=10, textColor=SLATE_700),
        "table_text_bold": ParagraphStyle("QuoteTableTextBold", parent=sample["Normal"], fontName=bold, fontSize=8.2, leading=10, textColor=SLATE_900),
        "right": ParagraphStyle("QuoteRight", parent=sample["Normal"], fontName=regular, fontSize=8, leading=10, alignment=2, textColor=SLATE_700),
        "right_bold": ParagraphStyle("QuoteRightBold", parent=sample["Normal"], fontName=bold, fontSize=8.2, leading=10, alignment=2, textColor=SLATE_900),
        "note": ParagraphStyle("QuoteNote", parent=sample["Normal"], fontName=regular, fontSize=8.5, leading=12, textColor=SLATE_700),
        "total_label": ParagraphStyle("QuoteTotalLabel", parent=sample["Normal"], fontName=bold, fontSize=10, leading=13, textColor=NAVY),
        "total_value": ParagraphStyle("QuoteTotalValue", parent=sample["Normal"], fontName=bold, fontSize=15, leading=18, alignment=2, textColor=BLUE),
    }


def _meta_cell(label, value, styles):
    return [
        Paragraph(service_pdf._text(label), styles["label"]),
        Spacer(1, 2),
        Paragraph(service_pdf._text(value), styles["value_bold"]),
    ]


def generate_quote_pdf(quote):
    service_pdf._register_fonts()
    regular = service_pdf.FONT_REGULAR
    bold = service_pdf.FONT_BOLD
    styles = _build_styles(regular, bold)
    config = _company_config(quote)
    company_name = _company_name(config)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=17 * mm,
        title=f"Fiyat Teklifi {quote.quote_number}",
        author=company_name,
    )
    usable_width = A4[0] - document.leftMargin - document.rightMargin
    elements = []

    logo = service_pdf._logo_flowable(config)
    contact_lines = _company_contact(config)
    address = getattr(config, "address", None) if config else None
    company_content = [Paragraph(service_pdf._text(company_name), styles["company"])]
    if contact_lines:
        company_content.append(Paragraph(service_pdf._text("  |  ".join(contact_lines)), styles["company_meta"]))
    if address:
        company_content.append(Paragraph(service_pdf._text(address), styles["company_meta"]))

    document_title = [
        Paragraph("FİYAT TEKLİFİ", styles["document_title"]),
        Paragraph(service_pdf._text(quote.quote_number), styles["document_subtitle"]),
    ]
    if logo:
        header_data = [[logo, company_content, document_title]]
        header_widths = [42 * mm, 72 * mm, usable_width - 114 * mm]
    else:
        header_data = [[company_content, document_title]]
        header_widths = [usable_width - 60 * mm, 60 * mm]

    header = Table(header_data, colWidths=header_widths)
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (-1, 0), (-1, 0), "RIGHT"),
    ]))
    elements.append(header)
    elements.append(Spacer(1, 5 * mm))
    elements.append(Table([[""]], colWidths=[usable_width], rowHeights=[1], style=[
        ("BACKGROUND", (0, 0), (-1, -1), BLUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(Spacer(1, 6 * mm))

    created_at = timezone.localtime(quote.created_at) if timezone.is_aware(quote.created_at) else quote.created_at
    sent_at = quote.sent_at
    if sent_at and timezone.is_aware(sent_at):
        sent_at = timezone.localtime(sent_at)
    sent_status = f"Gönderildi - {sent_at.strftime('%d.%m.%Y %H:%M')}" if sent_at else "Henüz gönderilmedi"
    valid_until = quote.valid_until.strftime("%d.%m.%Y") if quote.valid_until else "Belirtilmedi"

    elements.append(Paragraph("TEKLİF BİLGİLERİ", styles["section"]))
    meta_table = Table([
        [_meta_cell("Teklif Numarası", quote.quote_number, styles), _meta_cell("Teklif Tarihi", created_at.strftime("%d.%m.%Y"), styles)],
        [_meta_cell("Geçerlilik Tarihi", valid_until, styles), _meta_cell("Gönderim Durumu", sent_status, styles)],
    ], colWidths=[usable_width / 2, usable_width / 2])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SLATE_50),
        ("BOX", (0, 0), (-1, -1), 0.6, SLATE_200),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, SLATE_200),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 6 * mm))

    customer = quote.customer
    elements.append(Paragraph("MÜŞTERİ BİLGİLERİ", styles["section"]))
    customer_table = Table([
        [_meta_cell("Müşteri Adı Soyadı", customer.full_name, styles), _meta_cell("Telefon Numarası", customer.phone_number or "Belirtilmedi", styles)],
        [_meta_cell("E-posta Adresi", customer.email or "Belirtilmedi", styles), _meta_cell("Müşteri Adresi", customer.address or "Belirtilmedi", styles)],
    ], colWidths=[usable_width / 2, usable_width / 2])
    customer_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, SLATE_200),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, SLATE_200),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 7 * mm))

    elements.append(Paragraph("TEKLİF İŞLEMLERİ", styles["section"]))
    rows = [[
        Paragraph("#", styles["table_header"]),
        Paragraph("İşlem", styles["table_header"]),
        Paragraph("Açıklama", styles["table_header"]),
        Paragraph("Adet", styles["table_header_right"]),
        Paragraph("Birim Fiyat", styles["table_header_right"]),
        Paragraph("Toplam Tutar", styles["table_header_right"]),
    ]]
    for index, item in enumerate(quote.items.all(), start=1):
        rows.append([
            Paragraph(str(index), styles["table_text"]),
            Paragraph(service_pdf._text(item.name), styles["table_text_bold"]),
            Paragraph(service_pdf._text(item.description, "Belirtilmedi"), styles["table_text"]),
            Paragraph(str(item.quantity), styles["right"]),
            Paragraph(service_pdf._money(item.unit_price), styles["right"]),
            Paragraph(service_pdf._money(item.total_price), styles["right_bold"]),
        ])

    item_table = Table(rows, colWidths=[8 * mm, 42 * mm, 50 * mm, 14 * mm, 28 * mm, 32 * mm], repeatRows=1)
    item_style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BOX", (0, 0), (-1, -1), 0.6, SLATE_300),
        ("INNERGRID", (0, 1), (-1, -1), 0.35, SLATE_200),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("TOPPADDING", (0, 1), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
    ]
    for row_index in range(2, len(rows), 2):
        item_style.append(("BACKGROUND", (0, row_index), (-1, row_index), SLATE_50))
    item_table.setStyle(TableStyle(item_style))
    elements.append(item_table)
    elements.append(Spacer(1, 4 * mm))

    total_table = Table([[
        Paragraph("GENEL TOPLAM", styles["total_label"]),
        Paragraph(service_pdf._money(quote.total_price), styles["total_value"]),
    ]], colWidths=[usable_width * 0.58, usable_width * 0.42])
    total_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#BFDBFE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    elements.append(total_table)

    if quote.note:
        note_content = [
            Paragraph("TEKLİF NOTU", styles["section"]),
            Table([[Paragraph(service_pdf._text(quote.note), styles["note"])]], colWidths=[usable_width], style=[
                ("BACKGROUND", (0, 0), (-1, -1), SLATE_50),
                ("BOX", (0, 0), (-1, -1), 0.6, SLATE_200),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]),
        ]
        elements.append(Spacer(1, 7 * mm))
        elements.append(KeepTogether(note_content))

    def draw_footer(canvas, doc):
        canvas.saveState()
        footer_y = 10 * mm
        canvas.setStrokeColor(SLATE_200)
        canvas.setLineWidth(0.5)
        canvas.line(document.leftMargin, footer_y + 4 * mm, A4[0] - document.rightMargin, footer_y + 4 * mm)
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(SLATE_500)
        canvas.drawString(document.leftMargin, footer_y, company_name)
        canvas.drawRightString(A4[0] - document.rightMargin, footer_y, f"Sayfa {doc.page}")
        canvas.restoreState()

    document.build(elements, onFirstPage=draw_footer, onLaterPages=draw_footer)
    buffer.seek(0)
    return buffer
