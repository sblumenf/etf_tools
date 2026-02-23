"""Add expiration_date to derivative_uniq constraint

Revision ID: a4b2fe0cb4ef
Revises: 072714b23b2a
Create Date: 2026-02-22 22:26:56.578648

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b2fe0cb4ef'
down_revision: Union[str, None] = '072714b23b2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("derivative_uniq", "derivative", type_="unique")
    op.create_unique_constraint(
        "derivative_uniq",
        "derivative",
        ["etf_id", "report_date", "derivative_type", "underlying_name", "expiration_date", "filing_date", "counterparty"],
    )


def downgrade() -> None:
    op.drop_constraint("derivative_uniq", "derivative", type_="unique")
    op.create_unique_constraint(
        "derivative_uniq",
        "derivative",
        ["etf_id", "report_date", "derivative_type", "underlying_name", "filing_date", "counterparty"],
    )
