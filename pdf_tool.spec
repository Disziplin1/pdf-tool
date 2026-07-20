# -*- mode: python ; coding: utf-8 -*-
# PDF 도구 — PyInstaller 빌드 스펙
# 사용법:  pyinstaller pdf_tool.spec --clean --noconfirm
import sys, os

block_cipher = None

# ── tkinterdnd2 DLL 경로 처리 ────────────────────────────
# tkinterdnd2 는 네이티브 DLL 을 포함하므로 패키지 폴더 전체를 data 로 포함해야 함
dnd_datas = []
try:
    import tkinterdnd2 as _dnd
    _dnd_dir = os.path.dirname(_dnd.__file__)
    dnd_datas = [(_dnd_dir, 'tkinterdnd2')]
    print(f"[spec] tkinterdnd2 경로: {_dnd_dir}")
except ImportError:
    print("[spec] tkinterdnd2 없음 — DnD 기능 비활성화")

a = Analysis(
    ['pdf_tool.py'],
    pathex=['.'],
    binaries=[],
    datas=dnd_datas,
    hiddenimports=[
        'tkinterdnd2',
        'PIL._tkinter_finder',
        'PIL.ImageTk',
        'PIL.Image',
        'PIL.ImageOps',
        'fitz',
        'pypdf',
        'pypdf._crypt_filters',
        'pypdf._crypt_filters.pub_key_filters',
        'pypdf.filters',
        'pypdf.generic',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 배포 크기 줄이기: 사용하지 않는 대형 패키지 제외
    excludes=[
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'IPython', 'notebook', 'jupyter',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'wx', 'gtk',
        'test', 'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PDF 편집기',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,          # UPX 압축 (없으면 자동 스킵)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,     # 콘솔 창 없이 GUI 만 표시
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,         # 아이콘 파일 경로 (예: 'icon.ico') 로 교체 가능
)
