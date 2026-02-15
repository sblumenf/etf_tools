"""add fee_waiver_expiration_date to fee_expense

Revision ID: 072714b23b2a
Revises: 2c40e5e1d515
Create Date: 2026-02-15 02:36:19.286612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '072714b23b2a'
down_revision: Union[str, None] = '2c40e5e1d515'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fee_expense', sa.Column('fee_waiver_expiration_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('fee_expense', 'fee_waiver_expiration_date')
