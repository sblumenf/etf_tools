"""add benchmark_mapping table

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-03-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'benchmark_mapping',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('member_id', sa.String(500), nullable=False),
        sa.Column('readable_name', sa.String(500), nullable=True),
        sa.Column('source', sa.String(20), nullable=True),
        sa.Column('first_seen_cik', sa.String(10), nullable=True),
        sa.Column('first_seen_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('member_id', name='benchmark_mapping_member_id_uniq'),
    )


def downgrade() -> None:
    op.drop_table('benchmark_mapping')
