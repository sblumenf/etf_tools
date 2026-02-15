"""add borrower and liquidity classification to holding

Revision ID: 5bfc849e5e36
Revises: 5dab63ae21c8
Create Date: 2026-02-15 01:38:30.280878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5bfc849e5e36'
down_revision: Union[str, None] = '5dab63ae21c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('holding', sa.Column('borrower_name', sa.String(length=500), nullable=True))
    op.add_column('holding', sa.Column('liquidity_classification', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('holding', 'liquidity_classification')
    op.drop_column('holding', 'borrower_name')
