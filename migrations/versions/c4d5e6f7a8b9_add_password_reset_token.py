"""add password reset token table

Revision ID: c4d5e6f7a8b9
Revises: b3f1a2c4d5e6
Create Date: 2026-03-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3f1a2c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'password_reset_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_password_reset_token_token_hash', 'password_reset_token', ['token_hash'], unique=True)
    op.create_index('ix_password_reset_token_email', 'password_reset_token', ['email'], unique=False)
    op.create_index('ix_password_reset_token_created_at', 'password_reset_token', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_password_reset_token_created_at', table_name='password_reset_token')
    op.drop_index('ix_password_reset_token_email', table_name='password_reset_token')
    op.drop_index('ix_password_reset_token_token_hash', table_name='password_reset_token')
    op.drop_table('password_reset_token')
