"""Create synchronization metadata schema.

Revision ID: 0001
Revises: None
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep this initial migration tied to metadata; subsequent revisions must be explicit.
    from engineering_kb.persistence.orm_models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from engineering_kb.persistence.orm_models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
