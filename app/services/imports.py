import os
import re
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Bid, BidLineItem, SourceDocument
from app.parsers import parse_document


def _safe_filename(filename: str) -> str:
    basename = Path(filename.replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", basename).strip(" .")
    return (cleaned or "uploaded-bid")[:255]


def _store_content(storage_dir: Path, storage_key: str, content: bytes) -> bool:
    """Atomically create a content-addressed file without replacing an existing one."""
    storage_dir.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=".incoming-", dir=storage_dir, delete=False) as temp:
        temp.write(content)
        temp_path = Path(temp.name)
    destination = storage_dir / storage_key
    try:
        os.link(temp_path, destination)
        return True
    except FileExistsError:
        return False
    finally:
        temp_path.unlink(missing_ok=True)


def _existing_bid(session: Session, digest: str) -> Bid | None:
    document = session.scalar(select(SourceDocument).where(SourceDocument.sha256 == digest))
    return session.get(Bid, document.bid_id) if document else None


def import_bid(
    session: Session,
    *,
    project_name: str,
    vendor_name: str,
    filename: str,
    content: bytes,
    storage_dir: Path,
) -> Bid:
    if not project_name.strip() or len(project_name.strip()) > 160:
        raise ValueError("Project name must contain 1 to 160 characters.")
    if not vendor_name.strip() or len(vendor_name.strip()) > 160:
        raise ValueError("Vendor name must contain 1 to 160 characters.")
    parsed = parse_document(filename, content)
    digest = sha256(content).hexdigest()

    existing = _existing_bid(session, digest)
    session.commit()
    if existing:
        return existing

    extension = Path(filename).suffix.lower()
    storage_key = f"{digest}{extension}"
    created_file = _store_content(storage_dir, storage_key, content)
    try:
        with session.begin():
            bid = Bid(project_name=project_name.strip(), vendor_name=vendor_name.strip())
            session.add(bid)
            session.flush()
            document = SourceDocument(
                bid_id=bid.id,
                filename=_safe_filename(filename),
                sha256=digest,
                parser_name=parsed.parser_name,
                storage_key=storage_key,
            )
            session.add(document)
            session.flush()
            items = []
            for row in parsed.items:
                items.append(
                    BidLineItem(
                        bid_id=bid.id,
                        document_id=document.id,
                        source_locator=row.source_locator,
                        source_excerpt=row.source_excerpt,
                        extracted_description=row.description,
                        extracted_quantity=row.quantity,
                        extracted_unit=row.unit,
                        extracted_unit_price=row.unit_price,
                        reviewed_description=row.description,
                        reviewed_quantity=row.quantity,
                        reviewed_unit=row.unit,
                        reviewed_unit_price=row.unit_price,
                        status="needs_review",
                        version=0,
                    )
                )
            session.add_all(items)
            session.flush()
            session.add(
                AuditEvent(
                    bid_id=bid.id,
                    entity_type="bid",
                    entity_id=bid.id,
                    actor="demo-reviewer",
                    action="bid_imported",
                    before_values=None,
                    after_values={"sha256": digest, "item_count": len(items)},
                )
            )
        return bid
    except Exception:
        session.rollback()
        try:
            winning_bid = _existing_bid(session, digest)
            session.commit()
        except Exception:
            session.rollback()
            winning_bid = None
        if winning_bid is not None:
            return winning_bid
        if created_file:
            (storage_dir / storage_key).unlink(missing_ok=True)
        raise
