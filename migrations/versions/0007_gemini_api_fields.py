"""gemini_api_fields

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-30 11:16:51.042709

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    # Check existing columns before adding (safe for re-runs)
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = [c['name'] for c in inspector.get_columns('config_ia')]

    with op.batch_alter_table('config_ia', schema=None) as batch_op:
        if 'gemini_api_key' not in existing:
            batch_op.add_column(sa.Column('gemini_api_key', sa.String(length=200), nullable=True))
        if 'gemini_model' not in existing:
            batch_op.add_column(sa.Column('gemini_model', sa.String(length=100), nullable=True))

    # Skip unnamed FK on linhas_pedido (SQLite incompatible)


def downgrade():
    with op.batch_alter_table('config_ia', schema=None) as batch_op:
        batch_op.drop_column('gemini_model')
        batch_op.drop_column('gemini_api_key')
