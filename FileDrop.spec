# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.config import CONF

# Ensure PyInstaller cache stays within the workspace (avoids permission errors).
CONF['cachedir'] = os.path.join(os.path.abspath('.'), 'build_cache')

root_dir = os.path.abspath('.')
onefile = os.environ.get('FILEDROP_ONEFILE') == '1'
is_darwin = sys.platform == 'darwin'
is_win = sys.platform.startswith('win')
if is_darwin:
    exe_icon = 'assets/icon.icns'
elif is_win:
    exe_icon = 'assets/icon.ico'
else:
    exe_icon = None
extra_pathex = []
datas = [
    ('FileDrop_Web/server.py', 'FileDrop_Web'),
    ('FileDrop_Web/static', 'FileDrop_Web/static'),
    ('assets', 'assets'),
]
vendor_dir = os.path.join(root_dir, 'FileDrop_Web', 'vendor')
if os.path.isdir(vendor_dir):
    datas.append((vendor_dir, 'FileDrop_Web/vendor'))


a = Analysis(
    ['FileDrop.py'],
    pathex=extra_pathex,
    binaries=[],
    datas=datas,
hiddenimports=['appdirs', 'zoneinfo', 'http.cookies', 'colorsys', 'html'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if onefile:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
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
        icon=[exe_icon] if exe_icon else None,
    )
else:
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
        icon=[exe_icon] if exe_icon else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='FileDrop',
    )

    if is_darwin:
        app = BUNDLE(
            coll,
            name='FileDrop.app',
            icon='assets/icon.icns',
            bundle_identifier=None,
        )
