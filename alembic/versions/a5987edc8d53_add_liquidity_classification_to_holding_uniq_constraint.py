"""Add liquidity_classification to holding_uniq constraint

Revision ID: a5987edc8d53
Revises: a4b2fe0cb4ef
Create Date: 2026-02-22 22:35:29.449146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5987edc8d53'
down_revision: Union[str, None] = 'a4b2fe0cb4ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("holding_uniq", "holding", type_="unique")
    op.create_unique_constraint(
        "holding_uniq",
        "holding",
        ["etf_id", "report_date", "holding_key", "liquidity_classification", "filing_date"],
    )


def downgrade() -> None:
    op.drop_constraint("holding_uniq", "holding", type_="unique")
    op.create_unique_constraint(
        "holding_uniq",
        "holding",
        ["etf_id", "report_date", "holding_key", "filing_date"],
    )
