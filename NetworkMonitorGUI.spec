# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = []
binaries = []
hiddenimports = []

# Optionally include a bundled speedtest CLI if provided at extras/speedtest.exe
import os
proj_root = os.getcwd()
extras_path = os.path.join(proj_root, 'extras', 'speedtest.exe')
if os.path.exists(extras_path):
    # copy into root of the bundled app
    datas.append((extras_path, '.'))

# Collect for various libraries
# Avoid collecting large optional packages and test suites that aren't used at runtime.
# Removing 'scipy' from this list prevents noisy warnings when it's not installed
for pkg in ['pyqtgraph', 'requests', 'plotly', 'psutil', 'numpy']:
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception as e:
        print(f"Warning: Could not collect for {pkg}: {e}")

# Additional data for plotly
try:
    datas += collect_data_files('plotly')
except Exception as e:
    print(f"Warning: Could not collect plotly data: {e}")

# Collect only data files for pandas (avoid pulling test-suite hiddenimports)
try:
    datas += collect_data_files('pandas')
except Exception as e:
    print(f"Warning: Could not collect pandas data files: {e}")

# Add any missing modules
hiddenimports += [
    'plotly.express',
    'plotly.graph_objects',
    'plotly.subplots',
    'pandas.io.formats.style',
    'psutil._psutil_windows',
    'matplotlib.backends.backend_qt5agg',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'pyqtgraph.GraphicsScene',
    'pyqtgraph.ViewBox',
    'pyqtgraph.PlotItem',
    'pyqtgraph.PlotCurveItem',
    'pyqtgraph.GraphicsLayout',
    'dns.resolver',
    'dns.exception',
    'urllib3.util.retry',
    'requests.adapters',
    'chardet',
    'charset_normalizer',
    'json',
    'datetime',
    'os',
    'subprocess',
    'threading',
    'sys',
    'time',
    'collections',
]

a = Analysis(
    ['NetworkMonitorGUI.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['rthooks/fix_pandas_numba.py'],
    # Exclude optional or test-only modules that are not required by the app
    excludes=[
        'pyqtgraph.opengl',
        'OpenGL',
        'pandas.tests',
        'numpy.tests',
        'scipy',
        'scipy.tests',
        'psutil.tests',
        'pyqtgraph.opengl',
        'dns.resolver',
        'dns.exception',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NetworkMonitor_build2',
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
