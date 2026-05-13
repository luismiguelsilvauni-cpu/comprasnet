import sys
print("Python:", sys.version)
try:
    import flask; print("flask OK")
except Exception as e: print("flask ERRO:", e)
try:
    import pdfplumber; print("pdfplumber OK")
except Exception as e: print("pdfplumber ERRO:", e)
try:
    from models import db; print("models OK")
except Exception as e: print("models ERRO:", e)
try:
    import app; print("app OK")
except Exception as e: print("app ERRO:", e)
