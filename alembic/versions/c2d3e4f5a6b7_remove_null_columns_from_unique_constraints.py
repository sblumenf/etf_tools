"""remove null columns from unique constraints

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('holding') as batch_op:
        batch_op.drop_constraint('holding_uniq', type_='unique')
        batch_op.create_unique_constraint(
            'holding_uniq',
            ['etf_id', 'report_date', 'holding_key', 'filing_date'],
        )

    with op.batch_alter_table('nport_monthly_flow') as batch_op:
        batch_op.drop_constraint('nport_monthly_flow_uniq', type_='unique')
        batch_op.create_unique_constraint(
            'nport_monthly_flow_uniq',
            ['etf_id', 'report_date', 'filing_date'],
        )


def downgrade() -> None:
    with op.batch_alter_table('holding') as batch_op:
        batch_op.drop_constraint('holding_uniq', type_='unique')
        batch_op.create_unique_constraint(
            'holding_uniq',
            ['etf_id', 'report_date', 'holding_key', 'liquidity_classification', 'filing_date'],
        )

    with op.batch_alter_table('nport_monthly_flow') as batch_op:
        batch_op.drop_constraint('nport_monthly_flow_uniq', type_='unique')
        batch_op.create_unique_constraint(
            'nport_monthly_flow_uniq',
            ['etf_id', 'report_date', 'class_id', 'filing_date'],
        )
