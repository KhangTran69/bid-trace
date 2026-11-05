import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import Path

from openpyxl import load_workbook
from pypdf import PdfReader

from app.config import MAX_UPLOAD_BYTES
from app.decimal_limits import (
    QUANTITY_MAX_EXCLUSIVE,
    QUANTITY_SCALE,
    UNIT_PRICE_MAX_EXCLUSIVE,
    UNIT_PRICE_SCALE,
)


class ParseError(ValueError):
    """A file cannot be safely parsed as one of the documented demo formats."""


@dataclass(frozen=True)
class ParsedLineItem:
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    source_locator: str
    source_excerpt: str


@dataclass(frozen=True)
class ParsedDocument:
    parser_name: str
    items: list[ParsedLineItem]


EXPECTED_HEADERS = ("description", "quantity", "unit", "unit_price")
PDF_ROW = re.compile(r"^ITEM\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)$")


def _required_decimal(raw: object, label: str, *, allow_zero: bool = False) -> Decimal:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise ParseError(f"{label} must be a valid decimal number.") from None
    if not value.is_finite() or (value < 0 if allow_zero else value <= 0):
        condition = "zero or greater" if allow_zero else "greater than zero"
        raise ParseError(f"{label} must be finite and {condition}.")
    return value


def _make_item(
    description: object,
    quantity: object,
    unit: object,
    unit_price: object,
    locator: str,
    excerpt: str,
) -> ParsedLineItem:
    description_text = str(description).strip() if description is not None else ""
    unit_text = str(unit).strip() if unit is not None else ""
    if not description_text or len(description_text) > 500:
        raise ParseError("Each line item needs a description of 1 to 500 characters.")
    if not unit_text or len(unit_text) > 32:
        raise ParseError("Each line item needs a unit of 1 to 32 characters.")
    if len(excerpt) > 1000:
        raise ParseError("A source row is too long for the supported demo format.")
    quantity_value = _required_decimal(quantity, "Quantity")
    unit_price_value = _required_decimal(unit_price, "Unit price", allow_zero=True)
    if quantity_value.as_tuple().exponent < -QUANTITY_SCALE:
        raise ParseError(f"Quantity supports at most {QUANTITY_SCALE} decimal places.")
    if unit_price_value.as_tuple().exponent < -UNIT_PRICE_SCALE:
        raise ParseError(f"Unit price supports at most {UNIT_PRICE_SCALE} decimal places.")
    if quantity_value >= QUANTITY_MAX_EXCLUSIVE:
        raise ParseError("Quantity is too large for this bid demo.")
    if unit_price_value >= UNIT_PRICE_MAX_EXCLUSIVE:
        raise ParseError("Unit price is too large for this bid demo.")
    return ParsedLineItem(
        description=description_text,
        quantity=quantity_value,
        unit=unit_text,
        unit_price=unit_price_value,
        source_locator=locator,
        source_excerpt=excerpt,
    )


def parse_document(filename: str, content: bytes) -> ParsedDocument:
    """Parse a single documented demo layout and attach a stable source locator."""
    if not content:
        raise ParseError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ParseError("Uploads must be 10 MiB or smaller.")
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".csv", ".xlsx"}:
        raise ParseError("Unsupported file type. Upload a PDF, CSV, or XLSX file.")
    if extension == ".pdf":
        return _parse_pdf(content)
    if extension == ".csv":
        return _parse_csv(content)
    return _parse_xlsx(content)


def _parse_pdf(content: bytes) -> ParsedDocument:
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        items: list[ParsedLineItem] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for line in text.splitlines():
                candidate = line.strip()
                if not candidate.startswith("ITEM|"):
                    continue
                match = PDF_ROW.fullmatch(candidate)
                if not match:
                    raise ParseError(
                        "PDF line items must use ITEM|description|quantity|unit|unit_price."
                    )
                description, quantity, unit, unit_price = match.groups()
                items.append(
                    _make_item(
                        description,
                        quantity,
                        unit,
                        unit_price,
                        f"page:{page_number}",
                        candidate,
                    )
                )
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("The file could not be read as a valid PDF.") from exc
    return _document_with_items("text-pdf-v1", items)


def _dict_rows(rows: list[list[object]], locator) -> list[ParsedLineItem]:
    if not rows:
        raise ParseError("The spreadsheet has no header row.")
    headers = [str(value).strip().lower() if value is not None else "" for value in rows[0]]
    if tuple(headers[:4]) != EXPECTED_HEADERS or any(
        value not in (None, "") for value in rows[0][4:]
    ):
        raise ParseError("Expected columns: description, quantity, unit, unit_price.")
    items = []
    for row_number, row in enumerate(rows[1:], start=2):
        values = row[:4]
        if all(value is None or str(value).strip() == "" for value in values):
            continue
        if len(values) < 4:
            raise ParseError(f"Row {row_number} must contain all four bid columns.")
        excerpt = " | ".join("" if value is None else str(value) for value in values)
        items.append(_make_item(*values, locator(row_number), excerpt))
    return items


def _parse_csv(content: bytes) -> ParsedDocument:
    try:
        text = content.decode("utf-8-sig")
        rows = list(csv.reader(StringIO(text, newline="")))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ParseError("CSV files must be valid UTF-8 with comma-separated columns.") from exc
    items = _dict_rows(rows, lambda row: f"row:{row}")
    return _document_with_items("csv-v1", items)


def _parse_xlsx(content: bytes) -> ParsedDocument:
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        sheet = workbook[workbook.sheetnames[0]]
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        items = _dict_rows(
            rows,
            lambda row: f"sheet:{sheet.title}!A{row}:D{row}",
        )
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("The file could not be read as a valid XLSX workbook.") from exc
    finally:
        if "workbook" in locals():
            workbook.close()
    return _document_with_items("xlsx-v1", items)


def _document_with_items(parser_name: str, items: list[ParsedLineItem]) -> ParsedDocument:
    if not items:
        raise ParseError("No supported bid line items were found in the uploaded file.")
    return ParsedDocument(parser_name=parser_name, items=items)
