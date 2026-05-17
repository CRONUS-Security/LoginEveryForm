# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for LoginEveryForm — single-file (--onefile) build.

Usage:
    BUILD_VARIANT=chromium-only pyinstaller build/LoginEveryForm.spec
    BUILD_VARIANT=full          pyinstaller build/LoginEveryForm.spec

The variant name is embedded in the output executable filename so that
modules/browser_setup.py can detect which browsers to install on first run.
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(SPECPATH).parent  # repo root (spec lives in build/)
SRC = ROOT

variant = os.environ.get("BUILD_VARIANT", "chromium-only")

# ---------------------------------------------------------------------------
# Data files to bundle
# ---------------------------------------------------------------------------
datas = []

# Playwright package data (driver binaries, etc.)
pw_datas, pw_binaries, pw_hidden = collect_all("playwright")
datas += pw_datas

# PySide6 data (translations, plugins, etc.)
pyside6_datas, pyside6_binaries, pyside6_hidden = collect_all("PySide6")
datas += pyside6_datas

# Filter out PySide6.scripts which contains dev/build tools, not runtime dependencies
pyside6_hidden = [m for m in pyside6_hidden if not m.startswith("PySide6.scripts")]

# Ensure PySide6 main module is included even if collect_all misses it
if "PySide6" not in pyside6_hidden:
    pyside6_hidden.insert(0, "PySide6")

# Ensure runtime data directories exist (created at first launch if absent)
for data_dir in ["data", "logs", "screenshots"]:
    dir_path = SRC / data_dir
    dir_path.mkdir(exist_ok=True)
    datas.append((str(dir_path), data_dir))

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
hiddenimports = []
hiddenimports += pw_hidden
hiddenimports += [
    "playwright",
    "playwright.async_api",
    "playwright.sync_api",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtWidgets",
    "PySide6.QtGui",
    "asyncio",
    "aiofiles",
    "openpyxl",
    "rich",
    "Pillow",
    "PIL",
    "xml",
    "xml.etree",
    "xml.etree.ElementTree",
]

# ---------------------------------------------------------------------------
# Additional binaries
# ---------------------------------------------------------------------------
binaries = []
binaries += pw_binaries
binaries += pyside6_binaries

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(SRC / "main.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "build")],  # picks up hook-playwright.py
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "email",
        "html",
        "http",
        "pydoc",
        "doctest",
        "difflib",
        "_pytest",
        "pytest",
        "PySide6.scripts",
        "PySide6.scripts.deploy_lib",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# Single-file EXE — all binaries and data are embedded directly.
# No COLLECT step; the output is one standalone executable.
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,   # embed all native libs
    a.datas,      # embed all data files
    [],
    name=f"LoginEveryForm-{variant}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
