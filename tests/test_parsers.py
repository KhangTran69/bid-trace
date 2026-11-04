from pathlib import Path

import pytest

from app.parsers import ParseError, parse_document


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
