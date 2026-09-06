from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# reportlab's base14 fonts (Helvetica) use WinAnsiEncoding, which doesn't
# include the ₹ glyph (U+20B9) — using it would risk a broken/garbled PDF.
# "Rs." renders reliably with the default font; the frontend UI (browser,
# full Unicode support) is free to show ₹ instead.
CURRENCY = "Rs."

BILLS_DIR = Path(__file__).resolve().parent.parent.parent / "bills"


def generate_bill_pdf(bill, meter, consumer_name: str, tariff) -> str:
    BILLS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = BILLS_DIR / f"{bill.id}.pdf"

    c = canvas.Canvas(str(filepath), pagesize=A4)
    width, height = A4
    y = height - 30 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, "Grid Watch - Electricity Bill")
    y -= 12 * mm

    c.setFont("Helvetica", 11)
    for line in [
        f"Consumer: {consumer_name}",
        f"Meter: {meter.meter_code}",
        f"Billing cycle: {bill.cycle_start} to {bill.cycle_end}",
        f"Units consumed: {float(bill.units_consumed_kwh):.2f} kWh",
    ]:
        c.drawString(20 * mm, y, line)
        y -= 6 * mm
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, y, "Tariff Breakdown")
    y -= 8 * mm

    c.setFont("Helvetica", 10)
    remaining = float(bill.units_consumed_kwh)
    lower_bound = 0.0
    for slab in tariff.slabs:
        upto = slab["upto_kwh"]
        rate = float(slab["rate"])
        slab_width = remaining if upto is None else (upto - lower_bound)
        slab_units = max(0.0, min(remaining, slab_width))
        upper_label = "no limit" if upto is None else f"{upto:.0f}"
        slab_amount = slab_units * rate
        c.drawString(
            25 * mm,
            y,
            f"{lower_bound:.0f}-{upper_label} kWh @ {CURRENCY} {rate:.2f}/kWh: "
            f"{slab_units:.2f} kWh = {CURRENCY} {slab_amount:.2f}",
        )
        y -= 6 * mm
        remaining -= slab_units
        lower_bound = lower_bound if upto is None else upto
        if remaining <= 0 and upto is not None:
            continue

    c.drawString(25 * mm, y, f"Fixed charge: {CURRENCY} {float(tariff.fixed_charge):.2f}")
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, y, f"Total amount: {CURRENCY} {float(bill.amount):.2f}")

    c.showPage()
    c.save()
    return str(filepath)
