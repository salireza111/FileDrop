# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.config import CONF

# Ensure PyInstaller cache stays within the workspace (avoids permission errors).
CONF['cachedir'] = os.path.join(os.path.abspath('.'), 'build_cache')

root_dir = os.path.abspath('.')
extra_pathex = []
datas = [
    ('FileDrop_Web/server.py', 'FileDrop_Web'),
    ('FileDrop_Web/static', 'FileDrop_Web/static'),
    ('FileDrop_V1/assets', 'assets'),
]
vendor_dir = os.path.join(root_dir, 'FileDrop_Web', 'vendor')
if os.path.isdir(vendor_dir):
    datas.append((vendor_dir, 'FileDrop_Web/vendor'))


a = Analysis(
    ['FileDrop_V1/FileDrop.py'],
    pathex=extra_pathex,
    binaries=[],
    datas=datas,
    hiddenimports=['appdirs', 'zoneinfo'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FileDrop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['FileDrop_V1/assets/icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FileDrop',
)
app = BUNDLE(
    coll,
    name='FileDrop.app',
    icon='FileDrop_V1/assets/icon.icns',
    bundle_identifier=None,
)
