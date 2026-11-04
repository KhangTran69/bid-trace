from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


class Bid(Base):
    __tablename__ = "bids"
    __table_args__ = (
        CheckConstraint("status IN ('needs_review', 'approved')", name="ck_bids_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(160), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["SourceDocument"] = relationship(back_populates="bid", uselist=False)
    line_items: Mapped[list["BidLineItem"]] = relationship(back_populates="bid")


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("sha256", name="uq_source_documents_sha256"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bid_id: Mapped[int] = mapped_column(ForeignKey("bids.id", ondelete="CASCADE"), unique=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bid: Mapped[Bid] = relationship(back_populates="document")
    line_items: Mapped[list["BidLineItem"]] = relationship(back_populates="document")


class BidLineItem(Base):
    __tablename__ = "bid_line_items"
    __table_args__ = (
        CheckConstraint(
            "extracted_quantity > 0 AND reviewed_quantity > 0",
            name="ck_bid_line_items_quantities_positive",
        ),
        CheckConstraint(
            "extracted_unit_price >= 0 AND reviewed_unit_price >= 0",
            name="ck_bid_line_items_prices_nonnegative",
        ),
        CheckConstraint(
            "status IN ('needs_review', 'corrected', 'approved')",
            name="ck_bid_line_items_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bid_id: Mapped[int] = mapped_column(ForeignKey("bids.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    source_locator: Mapped[str] = mapped_column(String(255), nullable=False)
    source_excerpt: Mapped[str] = mapped_column(String(1000), nullable=False)
    extracted_description: Mapped[str] = mapped_column(String(500), nullable=False)
    extracted_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    extracted_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    extracted_unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reviewed_description: Mapped[str] = mapped_column(String(500), nullable=False)
    reviewed_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    reviewed_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewed_unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    bid: Mapped[Bid] = relationship(back_populates="line_items")
    document: Mapped[SourceDocument] = relationship(back_populates="line_items")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("entity_type IN ('bid', 'line_item')", name="ck_audit_entity_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bid_id: Mapped[int] = mapped_column(ForeignKey("bids.id", ondelete="CASCADE"), index=True)
    line_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("bid_line_items.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    before_values: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    after_values: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
