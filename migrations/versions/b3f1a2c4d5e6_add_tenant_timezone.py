"""add tenant timezone

Revision ID: b3f1a2c4d5e6
Revises: de946bf2aa55
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f1a2c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'de946bf2aa55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tenant',
        sa.Column('timezone', sa.String(length=64), nullable=True, server_default='America/New_York'),
    )


def downgrade() -> None:
    op.drop_column('tenant', 'timezone')
