from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


STATUS_REQUESTED = "requested"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"
STATUS_DRY_RUN_SUCCESS = "dry_run_success"


@dataclass(frozen=True)
class PurchaseOrder:
    po: str
    printer: str
    source_row: int


@dataclass(frozen=True)
class ProcessingResult:
    po: str
    printer: str
    automation_status: str
    error_explanation: str
    processed_date: str
    processed_timestamp: str
    screenshot_path: str
    run_id: str

    @classmethod
    def create(
        cls,
        po: str,
        printer: str,
        automation_status: str,
        error_explanation: str,
        run_id: str,
        screenshot_path: Optional[Path] = None,
    ) -> "ProcessingResult":
        from datetime import datetime

        now = datetime.now()
        return cls(
            po=po,
            printer=printer,
            automation_status=automation_status,
            error_explanation=error_explanation,
            processed_date=now.strftime("%Y-%m-%d"),
            processed_timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            screenshot_path=str(screenshot_path) if screenshot_path else "",
            run_id=run_id,
        )
