# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

added_files = [
    ('app/templates', 'app/templates'),
    ('app/static', 'app/static'),
    ('assets', 'assets'),
    ('GIFs', 'GIFs'),
]


hidden_imports = [
    'waitress',
    'sqlalchemy.sql.default_comparator',
    'app',
    'app.models',
    'app.routes.main',
    'app.routes.api',
    'app.routes.stats',
    'app.routes.rewards',
    'app.routes.settings',
    'app.routes.notebook',
]

a = Analysis(
    ['desktop.py'],
    pathex=['.'],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas'],
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
    name='foco',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
