"""add series_id to fund_snapshot

Revision ID: b1c2d3e4f5a6
Revises: a3739630d4a9
Create Date: 2026-03-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a3739630d4a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table, column):
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result)


def _index_exists(conn, index_name):
    result = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=:name"
    ), {"name": index_name})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # Drop pre-existing index so batch_alter_table can recreate it cleanly
    if _index_exists(conn, 'fund_snapshot_series_id_idx'):
        op.drop_index('fund_snapshot_series_id_idx', table_name='fund_snapshot')

    col_exists = _column_exists(conn, 'fund_snapshot', 'series_id')

    with op.batch_alter_table('fund_snapshot') as batch_op:
        if not col_exists:
            batch_op.add_column(sa.Column('series_id', sa.String(20), nullable=True))
        batch_op.create_index('fund_snapshot_series_id_idx', ['series_id'])
        batch_op.drop_constraint('fund_snapshot_cik_date_uniq', type_='unique')
        batch_op.create_unique_constraint(
            'fund_snapshot_cik_date_uniq',
            ['cik', 'series_id', 'report_date', 'filing_date'],
        )


def downgrade() -> None:
    with op.batch_alter_table('fund_snapshot') as batch_op:
        batch_op.drop_constraint('fund_snapshot_cik_date_uniq', type_='unique')
        batch_op.create_unique_constraint(
            'fund_snapshot_cik_date_uniq',
            ['cik', 'report_date', 'filing_date'],
        )
        batch_op.drop_index('fund_snapshot_series_id_idx')
        batch_op.drop_column('series_id')
