"""
Local build script for LoginEveryForm.

Usage:
    python build/build.py --variant chromium-only
    python build/build.py --variant full

Steps:
  1. Run PyInstaller with the spec file (--onefile mode)
  2. Print the path to the produced single-file executable
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"

VARIANTS = ["chromium-only", "full"]


def run(cmd: list[str], env: dict | None = None, **kwargs):
    merged_env = {**os.environ, **(env or {})}
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, env=merged_env, check=True, **kwargs)


def build_pyinstaller(variant: str):
    print(f"\n[1/1] Running PyInstaller (variant={variant}, onefile) ...")
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(BUILD_DIR / "LoginEveryForm.spec"),
        ],
        env={"BUILD_VARIANT": variant},
        cwd=str(ROOT),
    )


def _platform_suffix() -> str:
    if sys.platform == "win32":
        return ".exe"
    return ""


def main():
    parser = argparse.ArgumentParser(description="Build LoginEveryForm single-file binary")
    parser.add_argument(
        "--variant",
        choices=VARIANTS,
        default="chromium-only",
        help="Browser variant to build",
    )
    args = parser.parse_args()

    build_pyinstaller(args.variant)

    suffix = _platform_suffix()
    exe = DIST_DIR / f"LoginEveryForm-{args.variant}{suffix}"
    if exe.exists():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"\nBuild complete: {exe}  ({size_mb:.1f} MB)")
    else:
        print(f"\nBuild complete. Expected output: {exe}")


if __name__ == "__main__":
    main()
