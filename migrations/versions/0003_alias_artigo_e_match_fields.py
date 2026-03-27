"""alias_artigo_e_match_fields

Revision ID: 0003
Revises: 0001
Create Date: 2026-03-27 15:05:22.983188

"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # Create aliases_artigo table
    op.create_table('aliases_artigo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('artigo_ref', sa.String(length=50), nullable=False),
        sa.Column('fornecedor', sa.String(length=200), nullable=True),
        sa.Column('descricao_orig', sa.String(length=500), nullable=True),
        sa.Column('descricao_norm', sa.String(length=500), nullable=True),
        sa.Column('referencia_forn', sa.String(length=100), nullable=True),
        sa.Column('confianca', sa.Float(), nullable=True),
        sa.Column('criado_por', sa.Integer(), nullable=True),
        sa.Column('data_criacao', sa.DateTime(), nullable=True),
        sa.Column('vezes_usado', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('aliases_artigo', schema=None) as batch_op:
        batch_op.create_index('ix_aliases_artigo_artigo_ref', ['artigo_ref'], unique=False)

    # Add match columns to items_orcamento
    with op.batch_alter_table('items_orcamento', schema=None) as batch_op:
        batch_op.add_column(sa.Column('artigo_ref_match', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('match_confianca', sa.Float(), nullable=True))

    # NOTE: FK on linhas_pedido.artigo_ref omitted — SQLite handles it implicitly


def downgrade():
    with op.batch_alter_table('items_orcamento', schema=None) as batch_op:
        batch_op.drop_column('match_confianca')
        batch_op.drop_column('artigo_ref_match')

    with op.batch_alter_table('aliases_artigo', schema=None) as batch_op:
        batch_op.drop_index('ix_aliases_artigo_artigo_ref')

    op.drop_table('aliases_artigo')
