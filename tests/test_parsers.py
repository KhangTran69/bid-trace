from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from app.parsers import ParseError, parse_document


@pytest.fixture
def bid_sheet():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Bid"
    sheet.append(["description", "quantity", "unit", "unit_price"])
    sheet.append(["Concrete pour", 12, "CY", 145.50])
    yield sheet
    workbook.close()


def _xlsx_with_dimensions(sheet, dimensions: str) -> bytes:
    original_bytes = BytesIO()
    sheet.parent.save(original_bytes)
    changed_bytes = BytesIO()
    with ZipFile(original_bytes) as original, ZipFile(changed_bytes, "w") as changed:
        for member in original.infolist():
            content = original.read(member)
            if member.filename == "xl/worksheets/sheet1.xml":
                worksheet_xml = ElementTree.fromstring(content)
                dimension = worksheet_xml.find("{*}dimension")
                assert dimension is not None
                dimension.set("ref", dimensions)
                content = ElementTree.tostring(worksheet_xml)
            changed.writestr(member, content)
    return changed_bytes.getvalue()


def test_pdf_items_keep_page_and_exact_source_excerpt(fixtures_dir):
    parsed = parse_document("bid-demo.pdf", (Path(fixtures_dir) / "bid-demo.pdf").read_bytes())
    assert len(parsed.items) == 2
    assert parsed.items[0].source_locator == "page:1"
    assert parsed.items[0].source_excerpt == "ITEM|Concrete pour|12|CY|145.50"
    assert parsed.items[0].quantity == pytest.approx(12)


def test_csv_items_keep_source_rows(fixtures_dir):
    parsed = parse_document("bid-demo.csv", (Path(fixtures_dir) / "bid-demo.csv").read_bytes())
    assert [item.source_locator for item in parsed.items] == ["row:2", "row:3"]
    assert parsed.items[1].description == "Rebar installation"


def test_xlsx_items_keep_sheet_and_cell_range(fixtures_dir):
    parsed = parse_document("bid-demo.xlsx", (Path(fixtures_dir) / "bid-demo.xlsx").read_bytes())
    assert parsed.items[0].source_locator == "sheet:Bid!A2:D2"
    assert parsed.items[0].description == "Concrete pour"


@pytest.mark.parametrize("dimensions", ["A1:D2", "A1:G10002"])
def test_xlsx_items_follow_actual_rows_when_dimensions_are_stale(bid_sheet, dimensions):
    bid_sheet.append(["Rebar installation", 20, "EA", 5.00])
    bid_sheet["G4"].number_format = "0.00"

    parsed = parse_document("bid.xlsx", _xlsx_with_dimensions(bid_sheet, dimensions))

    assert [(item.description, item.source_locator) for item in parsed.items] == [
        ("Concrete pour", "sheet:Bid!A2:D2"),
        ("Rebar installation", "sheet:Bid!A3:D3"),
    ]


@pytest.mark.parametrize(
    ("cell", "value", "message"),
    [
        ("E1", "memo", "Expected columns"),
        ("E2", "additional data", "Row 2 contains data beyond the fourth column"),
    ],
)
def test_xlsx_rejects_nonempty_extra_columns_outside_stale_dimensions(
    bid_sheet, cell, value, message
):
    bid_sheet[cell] = value

    with pytest.raises(ParseError, match=message):
        parse_document("bid.xlsx", _xlsx_with_dimensions(bid_sheet, "A1:D2"))


def test_xlsx_row_limit_uses_actual_rows_when_dimensions_are_stale(bid_sheet):
    for column, value in enumerate(["Rebar installation", 20, "EA", 5.00], start=1):
        bid_sheet.cell(row=10_002, column=column, value=value)

    with pytest.raises(ParseError, match="at most 10,000 data rows"):
        parse_document("bid.xlsx", _xlsx_with_dimensions(bid_sheet, "A1:D2"))


def test_xlsx_allows_trailing_row_formatting_past_the_data_limit(bid_sheet):
    bid_sheet.row_dimensions[10_002].height = 20

    parsed = parse_document("bid.xlsx", _xlsx_with_dimensions(bid_sheet, "A1:D2"))

    assert [item.source_locator for item in parsed.items] == ["sheet:Bid!A2:D2"]


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("notes.txt", b"not a bid"),
        ("broken.pdf", b"not a PDF"),
        ("bad.csv", b"wrong,headers\nx,y\n"),
        ("empty.csv", b"description,quantity,unit,unit_price\n"),
        ("bad-number.csv", b"description,quantity,unit,unit_price\nBrick,NaN,EA,2.00\n"),
    ],
)
def test_invalid_documents_fail_clearly(filename, content):
    with pytest.raises(ParseError):
        parse_document(filename, content)


def test_upload_limit_is_enforced():
    with pytest.raises(ParseError, match="10 MiB"):
        parse_document("large.csv", b"x" * (10 * 1024 * 1024 + 1))


@pytest.mark.parametrize(
    ("quantity", "unit_price"),
    [
        ("1.2345", "2.00"),
        ("12", "2.345"),
        ("1000000000", "2.00"),
        ("12", "10000000000"),
    ],
)
def test_csv_rejects_values_the_database_cannot_preserve_exactly(quantity, unit_price):
    content = (
        "description,quantity,unit,unit_price\n"
        f"Concrete,{quantity},CY,{unit_price}\n"
    ).encode()

    with pytest.raises(ParseError):
        parse_document("bid.csv", content)


def test_csv_rejects_source_rows_longer_than_the_stored_excerpt():
    quantity = "0" * 1001 + "1"
    content = (
        "description,quantity,unit,unit_price\n"
        f"Concrete,{quantity},CY,2.00\n"
    ).encode()

    with pytest.raises(ParseError, match="source row is too long"):
        parse_document("bid.csv", content)
