from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .paths import default_runs_dir, default_screenshot_dir


@dataclass(frozen=True)
class RunContext:
    run_id: str
    run_dir: Path
    screenshot_dir: Path
    log_dir: Path


def create_run_context(base_dir: str | Path | None = None) -> RunContext:
    if base_dir is None:
        base_dir = default_runs_dir()
    root = Path(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    index = 1
    while True:
        run_id = f"{timestamp}_run{index:03d}"
        run_dir = root / run_id
        if not run_dir.exists():
            break
        index += 1
    screenshot_dir = default_screenshot_dir() or run_dir / "screenshots"
    log_dir = run_dir / "logs"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(run_id=run_id, run_dir=run_dir, screenshot_dir=screenshot_dir, log_dir=log_dir)


def configure_logging(log_dir: Path) -> None:
    log_path = log_dir / "automation.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
