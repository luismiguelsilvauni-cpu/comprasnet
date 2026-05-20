"""inventario_exclusoes

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('inventario_exclusoes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('referencia', sa.String(50), nullable=False),
        sa.Column('motivo', sa.String(200), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('referencia')
    )
    op.create_index('ix_inventario_exclusoes_referencia', 'inventario_exclusoes', ['referencia'])


def downgrade():
    op.drop_index('ix_inventario_exclusoes_referencia', 'inventario_exclusoes')
    op.drop_table('inventario_exclusoes')
