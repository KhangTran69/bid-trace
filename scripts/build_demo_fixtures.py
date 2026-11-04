"""Regenerate the synthetic PDF and XLSX used by the local demo and tests."""

from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def make_pdf() -> bytes:
    stream = (
        b"BT /F1 12 Tf 50 750 Td (BidTrace synthetic demo) Tj "
        b"0 -25 Td (ITEM|Concrete pour|12|CY|145.50) Tj "
        b"0 -25 Td (ITEM|Rebar installation|850|LB|2.40) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    trailer = f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    pdf.extend(trailer.encode())
    return bytes(pdf)


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    (ROOT / "bid-demo.pdf").write_bytes(make_pdf())
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Bid"
    sheet.append(["description", "quantity", "unit", "unit_price"])
    sheet.append(["Concrete pour", 12, "CY", 145.5])
    sheet.append(["Rebar installation", 850, "LB", 2.4])
    workbook.save(ROOT / "bid-demo.xlsx")


if __name__ == "__main__":
    main()
