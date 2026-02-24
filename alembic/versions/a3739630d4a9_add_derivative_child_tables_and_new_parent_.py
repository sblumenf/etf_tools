"""add derivative child tables and new parent columns

Revision ID: a3739630d4a9
Revises: a5987edc8d53
Create Date: 2026-02-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3739630d4a9'
down_revision: Union[str, None] = 'a5987edc8d53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New columns on derivative table
    op.add_column('derivative', sa.Column('unrealized_appreciation', sa.Numeric(precision=20, scale=2), nullable=True))
    op.add_column('derivative', sa.Column('currency', sa.String(length=3), nullable=True))
    op.add_column('derivative', sa.Column('underlying_title', sa.String(length=150), nullable=True))
    op.add_column('derivative', sa.Column('underlying_isin', sa.String(length=12), nullable=True))
    op.add_column('derivative', sa.Column('underlying_ticker', sa.String(length=20), nullable=True))
    op.add_column('derivative', sa.Column('underlying_other_id', sa.String(length=50), nullable=True))
    op.add_column('derivative', sa.Column('underlying_other_id_type', sa.String(length=50), nullable=True))
    op.add_column('derivative', sa.Column('payoff_profile', sa.String(length=10), nullable=True))

    # derivative_swap table
    op.create_table(
        'derivative_swap',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('derivative_id', sa.Integer(), nullable=False),
        sa.Column('upfront_payment', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('upfront_payment_currency', sa.String(length=3), nullable=True),
        sa.Column('upfront_receipt', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('upfront_receipt_currency', sa.String(length=3), nullable=True),
        sa.Column('swap_flag', sa.String(length=1), nullable=True),
        sa.ForeignKeyConstraint(['derivative_id'], ['derivative.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('derivative_id'),
    )
    op.create_index('derivative_swap_derivative_idx', 'derivative_swap', ['derivative_id'])

    # derivative_swap_leg table
    op.create_table(
        'derivative_swap_leg',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('swap_id', sa.Integer(), nullable=False),
        sa.Column('direction', sa.String(length=7), nullable=False),
        sa.Column('leg_type', sa.String(length=10), nullable=True),
        sa.Column('fixed_rate', sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column('fixed_amount', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('fixed_currency', sa.String(length=3), nullable=True),
        sa.Column('floating_index', sa.String(length=100), nullable=True),
        sa.Column('floating_spread', sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column('floating_amount', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('floating_currency', sa.String(length=3), nullable=True),
        sa.Column('tenor', sa.String(length=20), nullable=True),
        sa.Column('tenor_unit', sa.String(length=10), nullable=True),
        sa.Column('reset_date_tenor', sa.String(length=20), nullable=True),
        sa.Column('reset_date_unit', sa.String(length=10), nullable=True),
        sa.Column('other_description', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['swap_id'], ['derivative_swap.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('swap_id', 'direction', name='swap_leg_uniq'),
    )
    op.create_index('derivative_swap_leg_swap_idx', 'derivative_swap_leg', ['swap_id'])

    # derivative_option table
    op.create_table(
        'derivative_option',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('derivative_id', sa.Integer(), nullable=False),
        sa.Column('put_or_call', sa.String(length=4), nullable=True),
        sa.Column('written_or_purchased', sa.String(length=10), nullable=True),
        sa.Column('share_number', sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column('exercise_price', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('exercise_price_currency', sa.String(length=3), nullable=True),
        sa.Column('index_name', sa.String(length=150), nullable=True),
        sa.Column('index_identifier', sa.String(length=50), nullable=True),
        sa.Column('nested_deriv_type', sa.String(length=20), nullable=True),
        sa.Column('nested_deriv_notional', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('nested_deriv_counterparty', sa.String(length=500), nullable=True),
        sa.Column('nested_deriv_currency', sa.String(length=3), nullable=True),
        sa.ForeignKeyConstraint(['derivative_id'], ['derivative.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('derivative_id'),
    )
    op.create_index('derivative_option_derivative_idx', 'derivative_option', ['derivative_id'])

    # derivative_forward table
    op.create_table(
        'derivative_forward',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('derivative_id', sa.Integer(), nullable=False),
        sa.Column('currency_sold', sa.String(length=3), nullable=True),
        sa.Column('amount_sold', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('currency_purchased', sa.String(length=3), nullable=True),
        sa.Column('amount_purchased', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('settlement_date', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['derivative_id'], ['derivative.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('derivative_id'),
    )
    op.create_index('derivative_forward_derivative_idx', 'derivative_forward', ['derivative_id'])


def downgrade() -> None:
    op.drop_index('derivative_forward_derivative_idx', table_name='derivative_forward')
    op.drop_table('derivative_forward')

    op.drop_index('derivative_option_derivative_idx', table_name='derivative_option')
    op.drop_table('derivative_option')

    op.drop_index('derivative_swap_leg_swap_idx', table_name='derivative_swap_leg')
    op.drop_table('derivative_swap_leg')

    op.drop_index('derivative_swap_derivative_idx', table_name='derivative_swap')
    op.drop_table('derivative_swap')

    op.drop_column('derivative', 'payoff_profile')
    op.drop_column('derivative', 'underlying_other_id_type')
    op.drop_column('derivative', 'underlying_other_id')
    op.drop_column('derivative', 'underlying_ticker')
    op.drop_column('derivative', 'underlying_isin')
    op.drop_column('derivative', 'underlying_title')
    op.drop_column('derivative', 'currency')
    op.drop_column('derivative', 'unrealized_appreciation')
