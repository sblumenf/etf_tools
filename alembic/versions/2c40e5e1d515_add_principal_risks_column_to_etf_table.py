"""add principal_risks column to etf table

Revision ID: 2c40e5e1d515
Revises: 5bfc849e5e36
Create Date: 2026-02-15 01:57:57.074220

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c40e5e1d515'
down_revision: Union[str, None] = '5bfc849e5e36'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('etf', sa.Column('principal_risks', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('etf', 'principal_risks')
