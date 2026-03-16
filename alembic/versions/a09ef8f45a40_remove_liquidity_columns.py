"""remove liquidity columns

Revision ID: a09ef8f45a40
Revises: e4f5a6b7c8d9
Create Date: 2026-03-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a09ef8f45a40'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('holding') as batch_op:
        batch_op.drop_constraint('holding_uniq', type_='unique')
        batch_op.drop_column('liquidity_classification')
        batch_op.create_unique_constraint(
            'holding_uniq',
            ['etf_id', 'report_date', 'holding_key', 'filing_date'],
        )

    op.drop_column('fund_snapshot', 'liquidity_pref')


def downgrade() -> None:
    op.add_column('fund_snapshot', sa.Column('liquidity_pref', sa.Numeric(precision=20, scale=2), nullable=True))

    with op.batch_alter_table('holding') as batch_op:
        batch_op.drop_constraint('holding_uniq', type_='unique')
        batch_op.add_column(sa.Column('liquidity_classification', sa.String(length=50), nullable=True))
        batch_op.create_unique_constraint(
            'holding_uniq',
            ['etf_id', 'report_date', 'holding_key', 'liquidity_classification', 'filing_date'],
        )
