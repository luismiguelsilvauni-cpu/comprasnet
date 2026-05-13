"""fix_rtrim.py - Force strip on supplier ref keys"""

with open('app.py', 'r', encoding='utf-8') as f:
    src = f.read()

fixes = 0

# Fix 1: strip refs when building dict
old1 = "for ref, forn_nome, forn_no in rows:\n                if ref not in contagens:"
new1 = "for ref, forn_nome, forn_no in rows:\n                ref = (ref or '').strip()\n                if not ref: continue\n                if ref not in contagens:"
if old1.replace('\\n', '\n') in src.replace('\n', '\n'):
    pass

# Force strip in building dict - find the loop
import re
old = r"for ref, forn_nome, forn_no in rows:.*?if ref not in contagens:"
def replacer(m):
    return "for ref, forn_nome, forn_no in rows:\n                ref = (ref or '').strip()\n                if not ref: continue\n                if ref not in contagens:"

if "ref = (ref or '').strip()" not in src:
    src = re.sub(
        r"for ref, forn_nome, forn_no in rows:
                if ref not in contagens:",
        "for ref, forn_nome, forn_no in rows:\n                ref = (ref or '').strip()\n                if not ref: continue\n                if ref not in contagens:",
        src
    )
    fixes += 1
    print("OK: strip added to ref loop")
else:
    print("OK: strip already present")

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(src)
print(f"Done ({fixes} fixes). Restart server.")
