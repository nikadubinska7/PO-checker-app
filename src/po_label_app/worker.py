from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .automation import PortalAutomation, SessionExpiredError, StopRequestedError
from .config import AppConfig
from .excel_io import load_input_workbook
from .models import ProcessingResult, STATUS_SKIPPED
from .run_context import RunContext
from .tracking import TrackingWorkbook


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerEvent:
    event_type: str
    payload: object = None


class PortalWorker(threading.Thread):
    def __init__(self, config: AppConfig, event_callback: Callable[[WorkerEvent], None]):
        super().__init__(daemon=True)
        self.config = config
        self.event_callback = event_callback
        self.commands: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.automation: Optional[PortalAutomation] = None
        self.run_context: Optional[RunContext] = None

    def open_portal(self, run_context: RunContext) -> None:
        self.commands.put(("open_portal", {"run_context": run_context}))

    def start_processing(
        self,
        input_path: Path,
        tracking_path: Path,
        dry_run: bool,
        run_context: RunContext,
    ) -> None:
        self.commands.put(
            (
                "start_processing",
                {
                    "input_path": input_path,
                    "tracking_path": tracking_path,
                    "dry_run": dry_run,
                    "run_context": run_context,
                },
            )
        )

    def pause(self) -> None:
        self.pause_event.set()
        self.event_callback(WorkerEvent("status", "Pause requested"))

    def resume(self) -> None:
        self.pause_event.clear()
        self.event_callback(WorkerEvent("status", "Resume requested"))

    def stop_processing(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        self.event_callback(WorkerEvent("status", "Stop requested"))

    def shutdown(self) -> None:
        self.commands.put(("shutdown", {}))

    def run(self) -> None:
        while True:
            command, payload = self.commands.get()
            try:
                if command == "shutdown":
                    self._close_automation()
                    return
                if command == "open_portal":
                    self._handle_open(payload["run_context"])
                if command == "start_processing":
                    self._handle_start(**payload)
            except Exception as exc:
                LOGGER.exception("Worker command failed: %s", command)
                self.event_callback(WorkerEvent("error", str(exc)))

    def _handle_open(self, run_context: RunContext) -> None:
        self.run_context = run_context
        self.stop_event.clear()
        self.pause_event.clear()
        self._close_automation()
        self.automation = PortalAutomation(
            config=self.config,
            run_context=run_context,
            pause_event=self.pause_event,
            stop_event=self.stop_event,
            status_callback=lambda message: self.event_callback(WorkerEvent("status", message)),
        )
        self.automation.open_portal()
        self.event_callback(WorkerEvent("portal_opened", None))

    def _handle_start(
        self,
        input_path: Path,
        tracking_path: Path,
        dry_run: bool,
        run_context: RunContext,
    ) -> None:
        if not self.automation:
            raise RuntimeError("Open the portal before starting processing")
        self.run_context = run_context
        self.automation.run_context = run_context
        self.stop_event.clear()
        self.pause_event.clear()

        tracking = TrackingWorkbook(tracking_path)
        input_workbook = load_input_workbook(input_path, run_context.run_id)
        requested = tracking.requested_pos()
        pending = []
        skipped: list[ProcessingResult] = list(input_workbook.duplicate_results)

        for order in input_workbook.orders:
            if order.po in requested:
                skipped.append(
                    ProcessingResult.create(
                        po=order.po,
                        printer=order.printer,
                        automation_status=STATUS_SKIPPED,
                        error_explanation="Already requested in previous run",
                        run_id=run_context.run_id,
                    )
                )
            else:
                pending.append(order)

        total = len(pending) + len(skipped)
        processed = 0
        self.event_callback(
            WorkerEvent(
                "run_started",
                {
                    "run_id": run_context.run_id,
                    "total": total,
                    "pending": len(pending),
                    "skipped": len(skipped),
                    "tracking_path": str(tracking.path),
                    "screenshot_dir": str(run_context.screenshot_dir),
                },
            )
        )

        for result in skipped:
            tracking.append_result(result)
            processed += 1
            self.event_callback(WorkerEvent("result", result))
            self.event_callback(WorkerEvent("progress", {"processed": processed, "total": total}))

        for order in pending:
            if self.stop_event.is_set():
                break
            self.event_callback(WorkerEvent("current_po", order.po))
            try:
                result = self.automation.process_order(order, dry_run=dry_run)
            except SessionExpiredError as exc:
                self.pause_event.set()
                self.event_callback(WorkerEvent("session_expired", str(exc)))
                while self.pause_event.is_set() and not self.stop_event.is_set():
                    time.sleep(0.5)
                if self.stop_event.is_set():
                    break
                result = self.automation.process_order(order, dry_run=dry_run)
            except StopRequestedError:
                break

            tracking.append_result(result)
            processed += 1
            self.event_callback(WorkerEvent("result", result))
            self.event_callback(WorkerEvent("progress", {"processed": processed, "total": total}))

        self.event_callback(WorkerEvent("run_finished", {"processed": processed, "total": total}))

    def _close_automation(self) -> None:
        if self.automation:
            self.automation.close()
            self.automation = None
