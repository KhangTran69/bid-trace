"""Seed a synthetic BidTrace record and matching source file for the restore demo."""

import os
from hashlib import sha256
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import AuditEvent, Bid, BidLineItem, SourceDocument

CONTENT = b"item,quantity,unit_price\nSynthetic fixture item,1,1.00\n"


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    upload_dir_value = os.environ.get("UPLOAD_DIR")
    if not database_url or not upload_dir_value:
        raise SystemExit("Set DATABASE_URL and UPLOAD_DIR for the isolated restore fixture.")

    digest = sha256(CONTENT).hexdigest()
    storage_key = f"{digest}.csv"
    upload_dir = Path(upload_dir_value)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / storage_key).write_bytes(CONTENT)

    engine = create_engine(database_url)
    try:
        with Session(engine) as session, session.begin():
            bid = Bid(project_name="Synthetic restore demo", vendor_name="Fixture vendor")
            session.add(bid)
            session.flush()

            document = SourceDocument(
                bid_id=bid.id,
                filename="synthetic-restore-fixture.csv",
                sha256=digest,
                parser_name="synthetic-fixture",
                storage_key=storage_key,
            )
            session.add(document)
            session.flush()

            line_item = BidLineItem(
                bid_id=bid.id,
                document_id=document.id,
                source_locator="fixture:1",
                source_excerpt="Synthetic fixture item",
                extracted_description="Synthetic fixture item",
                extracted_quantity=1,
                extracted_unit="item",
                extracted_unit_price=1,
                reviewed_description="Synthetic fixture item",
                reviewed_quantity=1,
                reviewed_unit="item",
                reviewed_unit_price=1,
            )
            session.add(line_item)
            session.flush()

            session.add(
                AuditEvent(
                    bid_id=bid.id,
                    line_item_id=line_item.id,
                    entity_type="line_item",
                    entity_id=line_item.id,
                    actor="ci-restore-fixture",
                    action="created",
                    before_values=None,
                    after_values={"synthetic": True},
                )
            )
    finally:
        engine.dispose()

    print(f"Seeded one synthetic source document: {storage_key}")


if __name__ == "__main__":
    main()
