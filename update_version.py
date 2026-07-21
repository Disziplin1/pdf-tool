import re, sys
ver = sys.argv[1]
with open('pdf_tool.py', 'r', encoding='utf-8') as f:
    c = f.read()
pattern = re.compile(r'^VERSION\s*=\s*(["\'])[^"\']*\1', re.MULTILINE)
c, n = pattern.subn(f'VERSION = "{ver}"', c, count=1)
if n == 0:
    raise ValueError("pdf_tool.py 에서 VERSION 선언을 찾지 못했습니다.")
with open('pdf_tool.py', 'w', encoding='utf-8') as f:
    f.write(c)
print('VERSION =', ver)
