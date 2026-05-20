"""phc_bak_folder

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('config_phc', schema=None) as batch_op:
        batch_op.add_column(sa.Column('phc_bak_folder', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('config_phc', schema=None) as batch_op:
        batch_op.drop_column('phc_bak_folder')
