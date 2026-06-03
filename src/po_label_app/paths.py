from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


APP_DIR_NAME = "PO Label Request App"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path.cwd()


def resource_path(relative_path: str | Path) -> Path:
    candidate = bundle_root() / relative_path
    if candidate.exists():
        return candidate
    return Path(relative_path)


def user_documents_dir() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.exists() else Path.home()


def app_data_dir() -> Path:
    system = platform.system().lower()
    if system == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", user_documents_dir()))
    elif system == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_runs_dir() -> Path:
    path = app_data_dir() / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_screenshot_dir() -> Path | None:
    if platform.system().lower() != "darwin":
        return None
    path = Path(
        "/Users/ni4ka/Desktop/DESKTOP1/DESKTOP/IGROW/AI LEARNING/NIKE/PO checker app/screens"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_tracking_path() -> Path:
    return app_data_dir() / "tracking.xlsx"


def default_browser_profile_dir() -> Path:
    path = app_data_dir() / "browser-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_playwright_browsers_dir() -> Path | None:
    candidates = [
        bundle_root() / "ms-playwright",
        Path(sys.executable).parent / "ms-playwright",
        Path(sys.executable).parent.parent / "Resources" / "ms-playwright",
        Path(sys.executable).parent.parent / "Frameworks" / "ms-playwright",
    ]
    executable_path = Path(sys.executable)
    if len(executable_path.parents) > 3:
        candidates.append(executable_path.parents[3] / "ms-playwright")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
