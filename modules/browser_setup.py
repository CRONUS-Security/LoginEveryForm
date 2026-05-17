"""
First-run browser installation helper.

When running as a frozen binary (--onefile), Playwright browsers are not
bundled inside the executable.  This module checks whether the required
browsers are already installed in the user-level browsers directory, and
if not, shows a Qt progress dialog and installs them via `playwright install`.

The variant (chromium-only / full) is inferred from the executable's filename
so that different Release binaries install the correct set of browsers.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence

# Maps variant name → browsers to install
VARIANT_BROWSERS: dict[str, list[str]] = {
    "chromium-only": ["chromium"],
    "full": ["chromium", "firefox", "webkit"],
}

# Folder under the user's home that holds all playwright browser binaries
BROWSERS_DIR: Path = Path.home() / ".logineveryform" / "playwright-browsers"


def get_variant() -> str:
    """Infer the build variant from the executable name."""
    stem = Path(sys.executable).stem.lower()
    if "full" in stem:
        return "full"
    return "chromium-only"


def browsers_present(variant: str) -> bool:
    """Return True if every required browser appears to be installed."""
    if not BROWSERS_DIR.exists():
        return False
    required = VARIANT_BROWSERS.get(variant, ["chromium"])
    for browser in required:
        # Playwright stores browsers in versioned sub-directories whose names
        # start with the browser name (e.g. chromium-1097, firefox-1458).
        matches = list(BROWSERS_DIR.glob(f"{browser}-*"))
        if not matches:
            return False
    return True


def install_browsers(variant: str, parent_widget=None) -> bool:
    """
    Install the playwright browsers for *variant* into BROWSERS_DIR.

    Shows a Qt message box while installing.  Returns True on success.
    """
    browsers = VARIANT_BROWSERS.get(variant, ["chromium"])

    # --- Qt dialog -----------------------------------------------------------
    dialog = None
    if parent_widget is not None or True:  # always show even without parent
        try:
            from PySide6.QtWidgets import QMessageBox, QApplication
            from PySide6.QtCore import Qt

            # Make sure a QApplication exists (needed very early in startup)
            app = QApplication.instance()
            if app is None:
                app = QApplication(sys.argv)

            dialog = QMessageBox(parent_widget)
            dialog.setWindowTitle("LoginEveryForm – 首次启动")
            dialog.setText(
                f"正在安装浏览器驱动（{', '.join(browsers)}），请稍候…\n\n"
                "此过程仅在首次运行时执行，可能需要数分钟。"
            )
            dialog.setStandardButtons(QMessageBox.StandardButton.NoButton)
            dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
            dialog.show()
            QApplication.processEvents()
        except Exception:
            dialog = None
    # -------------------------------------------------------------------------

    import os

    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(BROWSERS_DIR)}
    BROWSERS_DIR.mkdir(parents=True, exist_ok=True)

    # Use the playwright Node.js driver binary directly so we never accidentally
    # re-launch the frozen executable itself (sys.executable in a frozen build
    # points to the app binary, not a Python interpreter).
    #
    # compute_driver_executable() returns a (node_exe, cli_js) tuple in modern
    # playwright versions; older versions returned a single Path.
    try:
        from playwright._impl._driver import compute_driver_executable
        _driver = compute_driver_executable()
        if isinstance(_driver, tuple):
            node_exe, cli_js = _driver
            install_cmd = [str(node_exe), str(cli_js), "install"]
        else:
            install_cmd = [str(_driver), "install"]
    except Exception:
        # Fallback for source / dev environments
        install_cmd = [sys.executable, "-m", "playwright", "install"]

    success = True
    for browser in browsers:
        result = subprocess.run(
            install_cmd + [browser],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            success = False
            _show_error(
                f"安装 {browser} 失败：\n{result.stderr[-500:]}",
                parent_widget,
            )
            break

    if dialog is not None:
        try:
            dialog.close()
        except Exception:
            pass

    return success


def _show_error(message: str, parent=None) -> None:
    try:
        from PySide6.QtWidgets import QMessageBox, QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        QMessageBox.critical(parent, "安装失败", message)
    except Exception:
        print(f"[browser_setup] ERROR: {message}", file=sys.stderr)


def ensure_browsers_installed(parent_widget=None) -> bool:
    """
    Entry point called from main.py before the main window is shown.

    Returns True if browsers are ready, False if installation failed.
    Only acts when running as a frozen binary.
    """
    if not getattr(sys, "frozen", False):
        return True  # Running from source – assume dev env has browsers

    variant = get_variant()
    if browsers_present(variant):
        return True

    return install_browsers(variant, parent_widget)
