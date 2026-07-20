import re, sys
ver = sys.argv[1]
with open('pdf_tool.py', 'r', encoding='utf-8') as f:
    c = f.read()
c = re.sub(r"VERSION\s*=\s*'[^']*'", f"VERSION = '{ver}'", c)
with open('pdf_tool.py', 'w', encoding='utf-8') as f:
    f.write(c)
print('VERSION =', ver)
