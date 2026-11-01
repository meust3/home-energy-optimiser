"""Portable canonical weather archive schema, shared by Base and Alembic."""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from energy_optimizer.timestamps import AwareDateTime


def register_weather_tables(metadata: MetaData) -> dict[str, Table]:
    json_type = JSON().with_variant(JSONB(), "postgresql")
    cycles = Table(
        "weather_collection_cycles",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("account_ref", String(64), nullable=False),
        Column("configuration_scope", String(64), nullable=False),
        Column("provider", String(32), nullable=False),
        Column("product", String(64), nullable=False),
        Column("requested_units", String(16), nullable=False),
        Column("scheduled_for", AwareDateTime(), nullable=False),
        Column("created_at", AwareDateTime(), nullable=False),
        Column("completed_at", AwareDateTime()),
        Column("window_start", AwareDateTime(), nullable=False),
        Column("window_end", AwareDateTime(), nullable=False),
        Column("next_start_epoch", BigInteger, nullable=False),
        Column("page_count", Integer, nullable=False),
        Column("status", String(32), nullable=False),
        Column("error_code", String(64)),
        UniqueConstraint("account_ref", "scheduled_for", name="uq_weather_cycle_slot"),
    )
    Index("idx_weather_cycle_created", cycles.c.created_at)
    payloads = Table(
        "weather_response_payloads",
        metadata,
        Column("original_sha256", String(64), primary_key=True),
        Column("stored_sha256", String(64), nullable=False),
        Column("original_byte_count", Integer, nullable=False),
        Column("credential_redacted", Boolean, nullable=False),
        Column("body", LargeBinary, nullable=False),
    )
    attempts = Table(
        "weather_page_attempts",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("account_ref", String(64), nullable=False),
        Column("cycle_id", ForeignKey(cycles.c.id), nullable=False),
        Column("page_number", Integer, nullable=False),
        Column("request_start_epoch", BigInteger, nullable=False),
        Column("requested_at", AwareDateTime(), nullable=False),
        Column("received_at", AwareDateTime()),
        Column("status", String(32), nullable=False),
        Column("http_status", Integer),
        Column("error_code", String(64)),
        Column("payload_sha256", ForeignKey(payloads.c.original_sha256)),
        Column("provider_issue_time", AwareDateTime()),
        Column("model_identity", String(128), nullable=False),
        Column("native_resolution", String(32), nullable=False),
        Column("parser_version", String(32), nullable=False),
        UniqueConstraint("cycle_id", "page_number", name="uq_weather_page_number"),
    )
    Index("idx_weather_attempt_budget", attempts.c.account_ref, attempts.c.requested_at)
    target_versions = Table(
        "weather_target_versions",
        metadata,
        Column("sha256", String(64), primary_key=True),
        Column("target_at", AwareDateTime(), nullable=False),
        Column("body", json_type, nullable=False),
    )
    Index("idx_weather_target_time", target_versions.c.target_at)
    targets = Table(
        "weather_page_targets",
        metadata,
        Column("attempt_id", ForeignKey(attempts.c.id), primary_key=True),
        Column("target_at", AwareDateTime(), primary_key=True),
        Column("version_sha256", ForeignKey(target_versions.c.sha256), nullable=False),
        Column("source_index", Integer, nullable=False),
    )
    state = Table(
        "weather_collection_state",
        metadata,
        Column("account_ref", String(64), primary_key=True),
        Column("blocked_until", AwareDateTime()),
        Column("reason", String(64)),
    )
    return dict(
        cycles=cycles,
        payloads=payloads,
        attempts=attempts,
        versions=target_versions,
        targets=targets,
        state=state,
    )
