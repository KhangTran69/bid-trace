import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError

from app.models import AuditEvent


def test_migrated_schema_has_expected_tables_constraints_and_types(engine):
    inspector = inspect(engine)
    assert {
        "bids",
        "source_documents",
        "bid_line_items",
        "audit_events",
        "alembic_version",
    }.issubset(set(inspector.get_table_names()))

    source_unique = inspector.get_unique_constraints("source_documents")
    assert any(
        constraint["name"] == "uq_source_documents_sha256"
        and constraint["column_names"] == ["sha256"]
        for constraint in source_unique
    )

    item_columns = {column["name"]: column for column in inspector.get_columns("bid_line_items")}
    assert (
        item_columns["extracted_quantity"]["type"].precision,
        item_columns["extracted_quantity"]["type"].scale,
    ) == (12, 3)
    assert (
        item_columns["reviewed_unit_price"]["type"].precision,
        item_columns["reviewed_unit_price"]["type"].scale,
    ) == (12, 2)

    checks = inspector.get_check_constraints("bid_line_items")
    assert any("reviewed_quantity > 0" in constraint["sqltext"] for constraint in checks)
    assert any("reviewed_unit_price >= 0" in constraint["sqltext"] for constraint in checks)
    assert any(
        foreign_key["constrained_columns"] == ["bid_id"] and foreign_key["referred_table"] == "bids"
        for foreign_key in inspector.get_foreign_keys("bid_line_items")
    )

    assert isinstance(AuditEvent.__table__.c.after_values.type.dialect_impl(engine.dialect), JSONB)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        trigger = connection.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'audit_events_no_mutation'")
        ).scalar_one_or_none()
        assert trigger == 1


def test_database_rejects_audit_mutation(engine):
    with engine.begin() as connection:
        with pytest.raises(DBAPIError, match="append-only"):
            with connection.begin_nested():
                bid_id = connection.execute(
                    text(
                        "INSERT INTO bids (project_name, vendor_name, status) "
                        "VALUES ('synthetic', 'synthetic', 'needs_review') RETURNING id"
                    )
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO audit_events "
                        "(bid_id, entity_type, entity_id, actor, action, after_values) "
                        "VALUES (:bid_id, 'bid', :bid_id, 'demo-reviewer', 'test', '{}'::jsonb)"
                    ),
                    {"bid_id": bid_id},
                )
                connection.execute(
                    text("UPDATE audit_events SET action = 'tampered' WHERE bid_id = :bid_id"),
                    {"bid_id": bid_id},
                )
