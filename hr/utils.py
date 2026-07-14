import io
from django.utils import timezone
from decimal import Decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, Image

from reports import utils as report_utils
from config.models import CompanyConfig


def _to_decimal(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0.00")


def generate_payroll_pdf(payroll):
    report_utils._register_fonts()
    font_regular = report_utils.FONT_REGULAR
    font_bold = report_utils.FONT_BOLD

    tech_user = payroll.technician.user
    tech_name = tech_user.get_full_name() or tech_user.email
    tenant = getattr(tech_user, "tenant", None)

    # Fetch company settings
    company_name = "Servis Yönetimi"
    logo_img = None
    if tenant:
        config = CompanyConfig.objects.filter(tenant=tenant).first()
        if config:
            company_name = config.name or company_name
            if config.logo:
                try:
                    # Validate the file now because ReportLab opens images lazily during doc.build().
                    logo_path = config.logo.path
                    ImageReader(logo_path)
                    logo_img = Image(logo_path, width=36, height=36)
                except Exception:
                    logo_img = None

    # Fetch components upfront to calculate dynamic page height
    components_qs = payroll.components.filter(
        payroll__technician__user__tenant=tenant
    ).order_by("type", "name") if tenant else payroll.components.order_by("type", "name")
    components_list = list(components_qs)
    n_components = len(components_list)

    # Dynamic single-page sizing — bordro/payslip style (A5 portrait width)
    PAGE_W = 148 * mm      # A5 width
    H_BASE = 190 * mm      # fixed sections: header + meta + employee + net + footer
    H_PER_ROW = 12 * mm    # each component row
    page_height = max(H_BASE + n_components * H_PER_ROW, 200 * mm)

    MARGIN = 16 * mm
    usable_w = PAGE_W - 2 * MARGIN
    col_left = usable_w * 0.67
    col_right = usable_w * 0.33

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(PAGE_W, page_height),
        rightMargin=MARGIN,
        leftMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    styles = getSampleStyleSheet()

    # ── Paragraph Styles ─────────────────────────────────────────────────────

    company_title_style = ParagraphStyle(
        "CompanyTitle",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=13,
        textColor=colors.HexColor("#1e3a8a"),
        leading=16,
    )

    company_sub_style = ParagraphStyle(
        "CompanySub",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=8,
        textColor=colors.HexColor("#64748b"),
        leading=11,
    )

    doc_title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=14,
        textColor=colors.HexColor("#1e293b"),
        alignment=2,  # Right
    )

    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=9,
        textColor=colors.HexColor("#475569"),
    )

    meta_value_style = ParagraphStyle(
        "MetaValue",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=9,
        textColor=colors.HexColor("#1e293b"),
        alignment=2,  # Right
    )

    section_header_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=9,
        textColor=colors.HexColor("#1e3a8a"),
    )

    item_label_style = ParagraphStyle(
        "ItemLabel",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=9,
        textColor=colors.HexColor("#334155"),
    )

    item_value_style = ParagraphStyle(
        "ItemValue",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=9,
        textColor=colors.HexColor("#0f172a"),
        alignment=2,  # Right
    )

    total_label_style = ParagraphStyle(
        "TotalLabel",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=9,
        textColor=colors.HexColor("#1e3a8a"),
    )

    total_value_style = ParagraphStyle(
        "TotalValue",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=9,
        textColor=colors.HexColor("#1e3a8a"),
        alignment=2,  # Right
    )

    net_title_style = ParagraphStyle(
        "NetTitle",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=10,
        textColor=colors.HexColor("#2563eb"),
        alignment=1,  # Center
    )

    net_value_style = ParagraphStyle(
        "NetValue",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=18,
        textColor=colors.HexColor("#1d4ed8"),
        alignment=1,  # Center
    )

    # ── Build Elements ────────────────────────────────────────────────────────

    elements = []

    # 1. Header (Company left, "Maaş Bordrosu" right)
    company_info = [
        Paragraph(company_name, company_title_style),
        Paragraph("Teknik Servis", company_sub_style),
    ]
    company_info_table = Table([[company_info]], colWidths=[col_left])
    company_info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
    ]))

    if logo_img:
        LOGO_W = 10 * mm
        header_cols = [logo_img, company_info_table, Paragraph("Maaş Bordrosu", doc_title_style)]
        col_widths_h = [LOGO_W, col_left - LOGO_W, col_right]
    else:
        header_cols = [company_info_table, Paragraph("Maaş Bordrosu", doc_title_style)]
        col_widths_h = [col_left, col_right]

    header_table = Table([header_cols], colWidths=col_widths_h)
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    # Horizontal rule
    hr_table = Table([['']], colWidths=[usable_w])
    hr_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(hr_table)
    elements.append(Spacer(1, 8))

    # 2. Metadata Block
    MONTHS_TR = {
        1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan', 5: 'Mayıs', 6: 'Haziran',
        7: 'Temmuz', 8: 'Ağustos', 9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'
    }
    period_month = MONTHS_TR.get(payroll.period_start.month, 'Ocak')
    period_year = payroll.period_start.year
    period_str = f"{period_month} {period_year}"
    pay_date_str = payroll.paid_date.strftime('%d.%m.%Y') if payroll.paid_date else payroll.period_end.strftime('%d.%m.%Y')
    doc_id = f"BRD-{period_year}-{payroll.id.hex[:4].upper()}" if hasattr(payroll, 'id') and hasattr(payroll.id, 'hex') else f"BRD-{period_year}-1024"

    meta_data = [
        [Paragraph("Bordro No:", meta_label_style), Paragraph(doc_id, meta_value_style)],
        [Paragraph("Dönem:", meta_label_style), Paragraph(period_str, meta_value_style)],
        [Paragraph("Ödeme Tarihi:", meta_label_style), Paragraph(pay_date_str, meta_value_style)],
        [Paragraph("Çalışan:", meta_label_style), Paragraph(tech_name, meta_value_style)],
    ]
    meta_table = Table(meta_data, colWidths=[col_left, col_right])
    meta_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor("#f1f5f9")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 10))

    # 3. Earnings Section
    earnings_rows = [
        [Paragraph("Taban Maaş", item_label_style), Paragraph(f"{_to_decimal(payroll.base_salary):,.2f} TL", item_value_style)]
    ]
    total_earnings = _to_decimal(payroll.base_salary)

    for comp in components_list:
        if comp.type == "addition":
            amount = _to_decimal(comp.amount)
            total_earnings += amount
            earnings_rows.append([Paragraph(comp.name, item_label_style), Paragraph(f"{amount:,.2f} TL", item_value_style)])

    elements.append(Table([[Paragraph("Kazançlar", section_header_style)]], colWidths=[usable_w], style=TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
    ])))

    earnings_table = Table(earnings_rows, colWidths=[col_left, col_right])
    earnings_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor("#f1f5f9")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(earnings_table)

    elements.append(Table([[Paragraph("Toplam Kazanç", total_label_style), Paragraph(f"{total_earnings:,.2f} TL", total_value_style)]], colWidths=[col_left, col_right], style=TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ])))
    elements.append(Spacer(1, 8))

    # 4. Deductions Section
    deductions_rows = []
    total_deductions = Decimal("0.00")

    for comp in components_list:
        if comp.type == "deduction":
            amount = _to_decimal(comp.amount)
            total_deductions += amount
            deductions_rows.append([Paragraph(comp.name, item_label_style), Paragraph(f"{amount:,.2f} TL", item_value_style)])

    if deductions_rows:
        elements.append(Table([[Paragraph("Kesintiler", section_header_style)]], colWidths=[usable_w], style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#fff1f2")),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ])))

        deductions_table = Table(deductions_rows, colWidths=[col_left, col_right])
        deductions_table.setStyle(TableStyle([
            ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor("#f1f5f9")),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(deductions_table)

        elements.append(Table([[Paragraph("Toplam Kesinti", total_label_style), Paragraph(f"{total_deductions:,.2f} TL", total_value_style)]], colWidths=[col_left, col_right], style=TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ])))
        elements.append(Spacer(1, 8))

    # 5. Net Payment Box
    net_box_data = [
        [Paragraph("Net Ödenecek", net_title_style)],
        [Paragraph(f"{_to_decimal(payroll.net_salary):,.2f} TL", net_value_style)],
    ]
    net_box_table = Table(net_box_data, colWidths=[usable_w])
    net_box_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#eff6ff")),
        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor("#2563eb")),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(net_box_table)
    elements.append(Spacer(1, 10))

    # 6. Footer
    wish_style = ParagraphStyle(
        "WishText",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=8,
        textColor=colors.HexColor("#94a3b8"),
        alignment=1,
    )
    elements.append(Table([[Paragraph("İyi günlerde harcayın 🙂", wish_style)]], colWidths=[usable_w], style=TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ])))

    doc.build(elements)
    buffer.seek(0)
    return buffer
