# backend/src/db/models.py
"""
Rows keep the full domain model as JSON (`data`) plus the few columns we
filter or join on. Pydantic models stay the source of truth for structure.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProfileRow(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SearchRow(Base):
    __tablename__ = "searches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("search_id", "dedupe_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    search_id: Mapped[str] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(512), index=True)
    data: Mapped[dict] = mapped_column(JSON)


class ApplicationRow(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    search_id: Mapped[str] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
