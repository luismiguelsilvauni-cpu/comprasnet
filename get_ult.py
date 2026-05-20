from app import app
from models import ConfigPHC
from phc_sync import get_phc_connection
with app.app_context():
    cfg = ConfigPHC.query.first()
    conn = get_phc_connection(cfg)
    cur = conn.cursor()
    cur.execute("""
        SELECT ref, evu FROM (
            SELECT RTRIM(sl.ref) AS ref, sl.evu,
                   ROW_NUMBER() OVER (PARTITION BY RTRIM(sl.ref) ORDER BY sl.datalc DESC, sl.lno DESC) AS rn
            FROM sl
            WHERE sl.qtt>0 AND (sl.cmdesc='Compra' OR RTRIM(ISNULL(sl.fnstamp,''))<>'') AND sl.evu>0
        ) t WHERE rn=1 AND RTRIM(ref)='CU5527131'
    """)
    r = cur.fetchone()
    print('Ultimo preco compra (sl.evu):', r)
    conn.close()
