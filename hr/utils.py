import io

from django.utils import timezone
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from reports import utils as report_utils


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

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "PayrollTitle",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=18,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=8,
    )

    text_style = ParagraphStyle(
        "PayrollText",
        parent=styles["Normal"],
        fontName=font_regular,
        fontSize=10,
        textColor=colors.HexColor("#334155"),
        leading=14,
    )

    elements = [
        Paragraph("MAAS BORDROSU", title_style),
        Paragraph(
            f"Olusturma Tarihi: {timezone.now().strftime('%d.%m.%Y %H:%M')}",
            text_style,
        ),
        Spacer(1, 12),
    ]

    summary_data = [
        ["Teknisyen", tech_name],
        [
            "Donem",
            f"{payroll.period_start.strftime('%d.%m.%Y')} - {payroll.period_end.strftime('%d.%m.%Y')}",
        ],
        ["Taban Maas", f"{_to_decimal(payroll.base_salary):.2f}"],
        ["Toplam Prim", f"{_to_decimal(payroll.total_premiums):.2f}"],
        ["Toplam Kesinti", f"{_to_decimal(payroll.total_deductions):.2f}"],
        ["Net Maas", f"{_to_decimal(payroll.net_salary):.2f}"],
        ["Odeme Durumu", "Odendi" if payroll.status == "paid" else "Bekliyor"],
    ]

    summary_table = Table(summary_data, colWidths=[150, 355])
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), font_bold),
                ("FONTNAME", (1, 0), (1, -1), font_regular),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    elements.append(summary_table)
    elements.append(Spacer(1, 16))

    # 🔒 TENANT SAFE QUERY
    components = payroll.components.filter(
        payroll__technician__user__tenant=tenant
    ).order_by("type", "name")

    component_rows = [["Kalem", "Tip", "Tutar"]]

    total_add = Decimal("0.00")
    total_ded = Decimal("0.00")

    for comp in components:
        amount = _to_decimal(comp.amount)

        if comp.type == "addition":
            total_add += amount
        else:
            total_ded += amount

        component_rows.append(
            [
                comp.name,
                "Eklenti" if comp.type == "addition" else "Kesinti",
                f"{amount:.2f}",
            ]
        )

    # footer total
    component_rows.append(["TOPLAM", "-", f"{(total_add - total_ded):.2f}"])

    component_table = Table(component_rows, colWidths=[245, 120, 140])
    component_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), font_bold),
                ("FONTNAME", (0, 1), (-1, -1), font_regular),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
            ]
        )
    )

    elements.append(component_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
