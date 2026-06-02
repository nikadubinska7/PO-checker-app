from __future__ import annotations

import argparse
from pathlib import Path

from .excel_io import load_input_workbook
from .models import ProcessingResult, STATUS_SKIPPED
from .run_context import configure_logging, create_run_context
from .tracking import TrackingWorkbook
from .ui import main as ui_main


def run_mock_excel(input_path: Path, tracking_path: Path) -> None:
    run_context = create_run_context()
    configure_logging(run_context.log_dir)
    tracking = TrackingWorkbook(tracking_path)
    workbook = load_input_workbook(input_path, run_context.run_id)
    for result in workbook.duplicate_results:
        tracking.append_result(result)
    requested = tracking.requested_pos()
    for order in workbook.orders:
        if order.po in requested:
            result = ProcessingResult.create(
                po=order.po,
                printer=order.printer,
                automation_status=STATUS_SKIPPED,
                error_explanation="Already requested in previous run",
                run_id=run_context.run_id,
            )
        else:
            result = ProcessingResult.create(
                po=order.po,
                printer=order.printer,
                automation_status=STATUS_SKIPPED,
                error_explanation="Mock Excel mode; browser automation was not run",
                run_id=run_context.run_id,
            )
        tracking.append_result(result)
    print(f"Mock Excel run complete: {tracking.path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vendor portal label request automation")
    parser.add_argument("--mock-excel", action="store_true", help="Validate Excel/tracking flow without Playwright")
    parser.add_argument("--input", type=Path, help="Input Excel file for mock mode")
    parser.add_argument("--tracking", type=Path, help="Tracking Excel file for mock mode")
    args = parser.parse_args()

    if args.mock_excel:
        if not args.input or not args.tracking:
            parser.error("--mock-excel requires --input and --tracking")
        run_mock_excel(args.input, args.tracking)
        return

    ui_main()


if __name__ == "__main__":
    main()
