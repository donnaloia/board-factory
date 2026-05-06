"""Auth domain — ORM tables: ``users``, ``user_secrets``, ``browser_sessions``."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.orm import Base


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    icon_glyph: Mapped[str] = mapped_column(String(8), nullable=False)
    icon_color: Mapped[str] = mapped_column(String(16), nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_login_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    secrets: Mapped[list["UserSecretRecord"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    browser_sessions: Mapped[list["BrowserSessionRecord"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserSecretRecord(Base):
    __tablename__ = "user_secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["UserRecord"] = relationship(back_populates="secrets")

    __table_args__ = (Index("ix_user_secrets_user_kind", "user_id", "kind", unique=True),)


class BrowserSessionRecord(Base):
    __tablename__ = "browser_sessions"

    sid: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_seen_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    user: Mapped["UserRecord"] = relationship(back_populates="browser_sessions")
