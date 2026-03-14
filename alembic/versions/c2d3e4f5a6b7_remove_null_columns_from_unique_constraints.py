"""remove null columns from unique constraints

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Remove holding duplicates before tightening constraint
    conn.execute(text("""
        DELETE FROM holding WHERE id NOT IN (
            SELECT MAX(id) FROM holding
            GROUP BY etf_id, report_date, holding_key, filing_date
        )
    """))
    conn.execute(text("""
        DELETE FROM nport_monthly_flow WHERE id NOT IN (
            SELECT MAX(id) FROM nport_monthly_flow
            GROUP BY etf_id, report_date, filing_date
        )
    """))

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
