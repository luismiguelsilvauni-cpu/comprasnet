"""Update backlog and changelog with recent work."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app, db, BacklogItem, ChangelogEntry
from datetime import datetime

with app.app_context():
    # === CHANGELOG ===
    entries = [
        ('2.5.0', 'feat', 'Módulo Salários: importação Excel, recibos PDF, email com anexo'),
        ('2.5.1', 'feat', 'Módulo Funcionários: ficha completa, documentos, formações, faltas'),
        ('2.5.2', 'feat', 'Pedidos de Compra: artigos PHC, múltiplas linhas, cliente por linha'),
        ('2.5.3', 'feat', 'Pedidos: status por artigo (não enc./pendente/recebido/cancelado) + histórico'),
        ('2.5.4', 'feat', 'Dashboard: widget artigos pedidos com status clicável e histórico'),
        ('2.5.5', 'feat', 'Menu Conectividade: QR code mobile + acesso externo unificados'),
        ('2.5.6', 'feat', 'Calendário: fuso horário corrigido, título visível, tooltip com criador'),
        ('2.5.7', 'feat', 'Módulo Partilha: upload/download/preview de ficheiros até 5GB'),
        ('2.5.8', 'fix',  'Recibo PDF: PROCESSAMENTO, horas, IRS taxas marginal/efetiva/parcela'),
        ('2.5.9', 'fix',  'Email recibo: encoding UTF-8 corrigido, HTML/PDF em anexo'),
    ]
    for versao, tipo, desc in entries:
        exists = ChangelogEntry.query.filter_by(versao=versao, descricao=desc).first()
        if not exists:
            db.session.add(ChangelogEntry(versao=versao, tipo=tipo, descricao=desc, criado_em=datetime.now()))
    
    # === BACKLOG ===
    concluidos = [
        ('Módulo Salários completo', 'Importação XLS, recibos PDF, email anexo, IRS correcto', 'large', 'done'),
        ('Módulo Funcionários', 'Ficha, docs, formações, faltas, situação profissional', 'large', 'done'),
        ('Pedidos: artigos PHC multi-linha', 'Pesquisa PHC, múltiplos artigos, cliente por linha', 'medium', 'done'),
        ('Pedidos: status artigo + histórico', 'Estados por artigo com registo de utilizador e data', 'medium', 'done'),
        ('Dashboard: artigos pedidos', 'Widget com tabela de artigos, status clicável, histórico', 'medium', 'done'),
        ('Menu Conectividade', 'QR code mobile + acesso externo unificados', 'small', 'done'),
        ('Calendário: fuso horário', 'Data correcta em Portugal (UTC+1), título visível', 'small', 'done'),
        ('Módulo Partilha ficheiros', 'Upload/download/preview, 5GB, visibilidade por utilizador', 'medium', 'done'),
    ]
    pendentes = [
        ('Instalação wkhtmltopdf servidor', 'Para gerar PDF real no email do recibo de salário', 'small', 'pending'),
        ('Configuração servidor final', 'waitress + arranque automático Windows 11/Server', 'medium', 'pending'),
        ('Cancelar/Eliminar pedidos de compra', 'Botão funcional para cancelar e eliminar pedidos', 'small', 'pending'),
        ('Importação Excel todos funcionários', 'Importar recibos de todos os funcionários de uma vez', 'medium', 'pending'),
    ]
    for titulo, desc, tipo, estado in concluidos + pendentes:
        exists = BacklogItem.query.filter_by(titulo=titulo).first()
        if not exists:
            db.session.add(BacklogItem(titulo=titulo, descricao=desc, tipo=tipo, estado=estado,
                                       criado_em=datetime.now(), atualizado_em=datetime.now()))
    
    db.session.commit()
    print(f"Backlog e Changelog actualizados.")
