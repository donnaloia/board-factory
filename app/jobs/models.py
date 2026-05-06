"""Jobs domain — ORM tables: ``job_runs``, ``cost_entries``."""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.orm import Base


class JobRunRecord(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    eta_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_actual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ended_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    __table_args__ = (Index("ix_job_runs_ended_at", "ended_at"),)


class CostEntryRecord(Base):
    __tablename__ = "cost_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    op: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    usd: Mapped[float] = mapped_column(Float, nullable=False)
