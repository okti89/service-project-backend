import io

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config.models import CompanyConfig
from services import pdf_utils as service_pdf


def generate_quote_pdf(quote):
    service_pdf._register_fonts()
    regular = service_pdf.FONT_REGULAR
    bold = service_pdf.FONT_BOLD
    config = CompanyConfig.objects.filter(tenant=quote.tenant).first()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("QuoteNormal", parent=styles["Normal"], fontName=regular, fontSize=9, leading=12)
    heading = ParagraphStyle("QuoteHeading", parent=normal, fontName=bold, fontSize=16, leading=20, alignment=1)
    label = ParagraphStyle("QuoteLabel", parent=normal, fontName=bold)
    right = ParagraphStyle("QuoteRight", parent=normal, alignment=2)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    elements = []

    logo = service_pdf._logo_flowable(config)
    if logo:
        elements.append(Table([[logo]], colWidths=[174 * mm], style=[("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        elements.append(Spacer(1, 3 * mm))

    company_name = getattr(config, "name", None) or "Servis Yonetim"
    elements.append(Paragraph(service_pdf._text(company_name), heading))
    elements.append(Paragraph("FIYAT TEKLIFI", heading))
    elements.append(Spacer(1, 6 * mm))

    created_at = timezone.localtime(quote.created_at).strftime("%d.%m.%Y")
    valid_until = quote.valid_until.strftime("%d.%m.%Y") if quote.valid_until else "-"
    customer = quote.customer
    info = [
        [Paragraph("Teklif No", label), Paragraph(service_pdf._text(quote.quote_number), normal), Paragraph("Tarih", label), Paragraph(created_at, normal)],
        [Paragraph("Musteri", label), Paragraph(service_pdf._text(customer.full_name), normal), Paragraph("Gecerlilik", label), Paragraph(valid_until, normal)],
        [Paragraph("Telefon", label), Paragraph(service_pdf._text(customer.phone_number), normal), Paragraph("E-posta", label), Paragraph(service_pdf._text(customer.email), normal)],
        [Paragraph("Adres", label), Paragraph(service_pdf._text(customer.address), normal), "", ""],
    ]
    info_table = Table(info, colWidths=[24 * mm, 63 * mm, 24 * mm, 63 * mm])
    info_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f3f4f6")),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 7 * mm))

    rows = [[
        Paragraph("Urun / Islem", label),
        Paragraph("Aciklama", label),
        Paragraph("Adet", label),
        Paragraph("Birim Fiyat", label),
        Paragraph("Toplam", label),
    ]]
    for item in quote.items.all():
        rows.append([
            Paragraph(service_pdf._text(item.name), normal),
            Paragraph(service_pdf._text(item.description), normal),
            Paragraph(str(item.quantity), right),
            Paragraph(service_pdf._money(item.unit_price), right),
            Paragraph(service_pdf._money(item.total_price), right),
        ])

    item_table = Table(rows, colWidths=[47 * mm, 52 * mm, 14 * mm, 29 * mm, 32 * mm], repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 5 * mm))
    elements.append(Table(
        [[Paragraph("GENEL TOPLAM", label), Paragraph(service_pdf._money(quote.total_price), right)]],
        colWidths=[120 * mm, 54 * mm],
        style=[
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f4f6")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#94a3b8")),
            ("PADDING", (0, 0), (-1, -1), 7),
        ],
    ))

    if quote.note:
        elements.append(Spacer(1, 7 * mm))
        elements.append(Paragraph("Not", label))
        elements.append(Paragraph(service_pdf._text(quote.note), normal))

    document.build(elements)
    buffer.seek(0)
    return buffer
