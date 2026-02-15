"""add credit_spread_risk table

Revision ID: 5dab63ae21c8
Revises: 832998c69d8b
Create Date: 2026-02-15 01:26:27.902725

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dab63ae21c8'
down_revision: Union[str, None] = '832998c69d8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'credit_spread_risk',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('etf_id', sa.Integer(), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('filing_date', sa.Date(), nullable=False),
        sa.Column('invst_grade_3m', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('invst_grade_1y', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('invst_grade_5y', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('invst_grade_10y', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('invst_grade_30y', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('non_invst_grade_3m', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('non_invst_grade_1y', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('non_invst_grade_5y', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('non_invst_grade_10y', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.Column('non_invst_grade_30y', sa.Numeric(precision=24, scale=2), nullable=True),
        sa.ForeignKeyConstraint(['etf_id'], ['etf.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('etf_id', 'report_date', 'filing_date', name='credit_spread_risk_uniq')
    )


def downgrade() -> None:
    op.drop_table('credit_spread_risk')
