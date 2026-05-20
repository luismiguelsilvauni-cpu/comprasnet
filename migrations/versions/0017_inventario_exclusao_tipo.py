"""inventario_exclusao_tipo

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('inventario_exclusoes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tipo', sa.String(20), nullable=True, server_default='total'))


def downgrade():
    with op.batch_alter_table('inventario_exclusoes', schema=None) as batch_op:
        batch_op.drop_column('tipo')
