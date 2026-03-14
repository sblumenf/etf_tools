"""fix nullable constraints and return precision

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-03-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Backfill NULLs before making columns non-nullable
    conn.execute(text("UPDATE derivative SET underlying_name = '' WHERE underlying_name IS NULL"))
    conn.execute(text("UPDATE derivative SET counterparty = '' WHERE counterparty IS NULL"))
    conn.execute(text("UPDATE fund_snapshot SET series_id = '' WHERE series_id IS NULL"))
    conn.execute(text("UPDATE derivative SET expiration_date = '9999-12-31' WHERE expiration_date IS NULL"))

    # Derivative: make underlying_name and counterparty non-nullable
    with op.batch_alter_table('derivative') as batch_op:
        batch_op.alter_column('underlying_name', existing_type=sa.String(500), nullable=False, server_default='')
        batch_op.alter_column('counterparty', existing_type=sa.String(500), nullable=False, server_default='')
        batch_op.alter_column('expiration_date', existing_type=sa.Date, nullable=False, server_default='9999-12-31')

    # FundSnapshot: make series_id non-nullable
    with op.batch_alter_table('fund_snapshot') as batch_op:
        batch_op.alter_column('series_id', existing_type=sa.String(20), nullable=False, server_default='')

    # NPORTMonthlyReturn: change return column precision
    with op.batch_alter_table('nport_monthly_return') as batch_op:
        batch_op.alter_column('month_1_return', existing_type=sa.Numeric(24, 2), type_=sa.Numeric(10, 6))
        batch_op.alter_column('month_2_return', existing_type=sa.Numeric(24, 2), type_=sa.Numeric(10, 6))
        batch_op.alter_column('month_3_return', existing_type=sa.Numeric(24, 2), type_=sa.Numeric(10, 6))


def downgrade() -> None:
    with op.batch_alter_table('derivative') as batch_op:
        batch_op.alter_column('underlying_name', existing_type=sa.String(500), nullable=True, server_default=None)
        batch_op.alter_column('counterparty', existing_type=sa.String(500), nullable=True, server_default=None)
        batch_op.alter_column('expiration_date', existing_type=sa.Date, nullable=True, server_default=None)

    with op.batch_alter_table('fund_snapshot') as batch_op:
        batch_op.alter_column('series_id', existing_type=sa.String(20), nullable=True, server_default=None)

    with op.batch_alter_table('nport_monthly_return') as batch_op:
        batch_op.alter_column('month_1_return', existing_type=sa.Numeric(10, 6), type_=sa.Numeric(24, 2))
        batch_op.alter_column('month_2_return', existing_type=sa.Numeric(10, 6), type_=sa.Numeric(24, 2))
        batch_op.alter_column('month_3_return', existing_type=sa.Numeric(10, 6), type_=sa.Numeric(24, 2))
