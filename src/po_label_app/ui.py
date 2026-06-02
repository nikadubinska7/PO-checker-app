from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import load_config
from .paths import default_tracking_path
from .run_context import configure_logging, create_run_context
from .tracking import ensure_tracking_path
from .worker import PortalWorker, WorkerEvent


class LabelRequestApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Vendor Portal Label Requests")
        self.geometry("1180x720")
        self.minsize(980, 620)

        self.config_model = load_config()
        self.event_queue: queue.Queue[WorkerEvent] = queue.Queue()
        self.worker = PortalWorker(self.config_model, self.event_queue.put)
        self.worker.start()

        self.input_path = tk.StringVar()
        self.tracking_path = tk.StringVar(value=str(default_tracking_path()))
        self.dry_run = tk.BooleanVar(value=True)
        self.progress = tk.StringVar(value="0 / 0")
        self.current_po = tk.StringVar(value="-")
        self.status_text = tk.StringVar(value="Open the portal, log in manually, then start processing.")
        self.run_id = tk.StringVar(value="-")
        self.screenshot_dir = tk.StringVar(value="-")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self._drain_events)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        file_frame = ttk.LabelFrame(self, text="Files")
        file_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        file_frame.columnconfigure(1, weight=1)

        ttk.Label(file_frame, text="Input Excel").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(file_frame, textvariable=self.input_path).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(file_frame, text="Browse", command=self._browse_input).grid(row=0, column=2, padx=8, pady=8)

        ttk.Label(file_frame, text="Tracking Excel").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(file_frame, textvariable=self.tracking_path).grid(row=1, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(file_frame, text="Choose", command=self._choose_tracking).grid(row=1, column=2, padx=8, pady=8)

        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        for index in range(8):
            controls.columnconfigure(index, weight=0)
        controls.columnconfigure(8, weight=1)

        ttk.Button(controls, text="Open Portal", command=self._open_portal).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(controls, text="Start Processing", command=self._start_processing).grid(row=0, column=1, padx=8)
        ttk.Button(controls, text="Pause", command=self.worker.pause).grid(row=0, column=2, padx=8)
        ttk.Button(controls, text="Resume", command=self.worker.resume).grid(row=0, column=3, padx=8)
        ttk.Button(controls, text="Stop", command=self.worker.stop_processing).grid(row=0, column=4, padx=8)
        ttk.Checkbutton(controls, text="Dry Run", variable=self.dry_run).grid(row=0, column=5, padx=16)

        summary = ttk.LabelFrame(self, text="Run Status")
        summary.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        for index in range(4):
            summary.columnconfigure(index, weight=1)
        self._status_pair(summary, "Progress", self.progress, 0, 0)
        self._status_pair(summary, "Current PO", self.current_po, 0, 1)
        self._status_pair(summary, "Run ID", self.run_id, 0, 2)
        self._status_pair(summary, "Screenshots", self.screenshot_dir, 0, 3)

        ttk.Label(self, textvariable=self.status_text).grid(row=3, column=0, sticky="ew", padx=12, pady=6)

        table_frame = ttk.Frame(self)
        table_frame.grid(row=4, column=0, sticky="nsew", padx=12, pady=(6, 12))
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        columns = ("po", "printer", "status", "explanation", "timestamp", "screenshot")
        self.result_table = ttk.Treeview(table_frame, columns=columns, show="headings")
        headings = {
            "po": "PO",
            "printer": "Printer",
            "status": "Automation Status",
            "explanation": "Error Explanation",
            "timestamp": "Processed Timestamp",
            "screenshot": "Screenshot Path",
        }
        widths = {
            "po": 110,
            "printer": 80,
            "status": 150,
            "explanation": 310,
            "timestamp": 160,
            "screenshot": 360,
        }
        for column in columns:
            self.result_table.heading(column, text=headings[column])
            self.result_table.column(column, width=widths[column], anchor="w")
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.result_table.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.result_table.xview)
        self.result_table.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.result_table.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

    def _status_pair(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, column: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=column, sticky="ew", padx=8, pady=8)
        ttk.Label(frame, text=label).pack(anchor="w")
        ttk.Label(frame, textvariable=variable).pack(anchor="w")

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Select input Excel file",
            filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if path:
            self.input_path.set(path)

    def _choose_tracking(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Select or create tracking Excel file",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialfile="tracking.xlsx",
        )
        if path:
            self.tracking_path.set(path)

    def _open_portal(self) -> None:
        run_context = create_run_context()
        configure_logging(run_context.log_dir)
        self.run_id.set(run_context.run_id)
        self.screenshot_dir.set(str(run_context.screenshot_dir))
        self.status_text.set("Opening portal browser...")
        self.worker.open_portal(run_context)

    def _start_processing(self) -> None:
        try:
            input_path = Path(self.input_path.get()).expanduser()
            tracking_path = ensure_tracking_path(Path(self.tracking_path.get()).expanduser())
            if not input_path.exists():
                raise FileNotFoundError("Select an existing input Excel file")
            run_context = create_run_context()
            configure_logging(run_context.log_dir)
            self.run_id.set(run_context.run_id)
            self.screenshot_dir.set(str(run_context.screenshot_dir))
            self.result_table.delete(*self.result_table.get_children())
            self.progress.set("0 / 0")
            self.current_po.set("-")
            self.status_text.set("Starting processing...")
            self.worker.start_processing(input_path, tracking_path, self.dry_run.get(), run_context)
        except Exception as exc:
            messagebox.showerror("Cannot start processing", str(exc))

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)
        self.after(150, self._drain_events)

    def _handle_event(self, event: WorkerEvent) -> None:
        if event.event_type == "status":
            self.status_text.set(str(event.payload))
        elif event.event_type == "error":
            self.status_text.set(str(event.payload))
            messagebox.showerror("Automation error", str(event.payload))
        elif event.event_type == "portal_opened":
            self.status_text.set("Portal opened. Log in manually, then click Start Processing.")
        elif event.event_type == "run_started":
            payload = dict(event.payload)
            self.run_id.set(str(payload["run_id"]))
            self.screenshot_dir.set(str(payload["screenshot_dir"]))
            self.progress.set(f"0 / {payload['total']}")
            self.status_text.set(
                f"Run started. Pending: {payload['pending']}; skipped before browser actions: {payload['skipped']}."
            )
        elif event.event_type == "current_po":
            self.current_po.set(str(event.payload))
        elif event.event_type == "result":
            result = event.payload
            self.result_table.insert(
                "",
                0,
                values=(
                    result.po,
                    result.printer,
                    result.automation_status,
                    result.error_explanation,
                    result.processed_timestamp,
                    result.screenshot_path,
                ),
            )
        elif event.event_type == "progress":
            payload = dict(event.payload)
            self.progress.set(f"{payload['processed']} / {payload['total']}")
        elif event.event_type == "session_expired":
            self.status_text.set(str(event.payload))
            messagebox.showwarning(
                "Portal session expired",
                "The portal appears to be on a login page. Log in again in the browser, then click Resume.",
            )
        elif event.event_type == "run_finished":
            payload = dict(event.payload)
            self.status_text.set(f"Run finished. Processed {payload['processed']} of {payload['total']} rows.")
            self.current_po.set("-")

    def _on_close(self) -> None:
        self.worker.shutdown()
        self.destroy()


def main() -> None:
    app = LabelRequestApp()
    app.mainloop()
