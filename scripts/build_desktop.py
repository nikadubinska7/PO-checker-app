from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "PO Label Request App"


def data_separator() -> str:
    return ";" if platform.system().lower() == "windows" else ":"


def add_data_arg(source: Path, target: str) -> str:
    return f"{source}{data_separator()}{target}"


def playwright_cache_dir() -> Path | None:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    candidates: list[Path] = []
    if override and override != "0":
        candidates.append(Path(override))
    if platform.system().lower() == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "ms-playwright")
    elif platform.system().lower() == "darwin":
        candidates.append(Path.home() / "Library" / "Caches" / "ms-playwright")
    else:
        candidates.append(Path.home() / ".cache" / "ms-playwright")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def main() -> None:
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit("PyInstaller is not installed. Run: pip install -r requirements-build.txt") from exc

    browser_dir = playwright_cache_dir()
    if not browser_dir:
        raise SystemExit("Playwright Chromium is not installed. Run: python -m playwright install chromium")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--paths",
        str(ROOT / "src"),
        "--add-data",
        add_data_arg(ROOT / "config.yaml", "."),
        "--add-data",
        add_data_arg(ROOT / "examples" / "example_input.xlsx", "examples"),
        "--hidden-import",
        "playwright.sync_api",
        "--collect-all",
        "playwright",
        str(ROOT / "src" / "po_label_app" / "__main__.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    copy_browser_files(browser_dir)
    print(f"Built desktop app in: {ROOT / 'dist'}")


def copy_browser_files(browser_dir: Path) -> None:
    system = platform.system().lower()
    if system == "darwin":
        target = ROOT / "dist" / f"{APP_NAME}.app" / "Contents" / "Resources" / "ms-playwright"
    elif system == "windows":
        target = ROOT / "dist" / APP_NAME / "ms-playwright"
    else:
        target = ROOT / "dist" / APP_NAME / "ms-playwright"

    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(browser_dir, target)
    print(f"Copied Playwright browsers to: {target}")


if __name__ == "__main__":
    main()
