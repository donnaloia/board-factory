"""SQLAlchemy ORM models for persisted application state.

Each ``*Record`` class maps to a single relational table managed by
Alembic (see ``app/migrations/versions/``). The ``Base`` declarative
class is imported by all model modules and by ``infrastructure.db`` for engine
binding; migrations are hand-written, so models and migrations are kept
in sync by convention rather than autogenerate.
"""

from models.base import Base
from models.core import (
    AssetVersionRecord,
    BoardGameRecord,
    BrowserSessionRecord,
    CostEntryRecord,
    JobRunRecord,
    OwnedBoardRecord,
    UserRecord,
    UserSecretRecord,
)

__all__ = [
    "AssetVersionRecord",
    "Base",
    "BoardGameRecord",
    "BrowserSessionRecord",
    "CostEntryRecord",
    "JobRunRecord",
    "OwnedBoardRecord",
    "UserRecord",
    "UserSecretRecord",
]
