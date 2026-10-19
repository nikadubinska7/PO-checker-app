from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from openpyxl import Workbook

from po_label_app.config import load_config
from po_label_app.models import LABEL_MODE_ALL_AVAILABLE, LABEL_MODE_EXCLUDE_CARTONS, ProcessingResult
from po_label_app.run_context import RunContext
from po_label_app.tracking import TrackingWorkbook
from po_label_app.worker import PortalWorker


class WorkerTrackingTests(unittest.TestCase):
    def test_exclusion_mode_checks_portal_after_previous_price_only_success(self):
        for mode in (LABEL_MODE_ALL_AVAILABLE, LABEL_MODE_EXCLUDE_CARTONS):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                input_path, tracking_path = root / 'input.xlsx', root / 'tracking.xlsx'
                workbook = Workbook()
                workbook.active.append(['PO', 'Printer'])
                workbook.active.append(['123', 'HK'])
                workbook.save(input_path)
                tracking = TrackingWorkbook(tracking_path)
                tracking.append_result(ProcessingResult.create(
                    '123', 'HK', 'requested', '', 'old', label_request_mode='price_only'))
                events = []
                worker = PortalWorker(load_config(), events.append)
                worker.automation = Mock()
                worker.automation.process_order.return_value = ProcessingResult.create(
                    '123', 'HK', 'skipped', 'released before', 'new', label_request_mode=mode)
                worker._handle_start(input_path, tracking_path, False, mode,
                                     RunContext('new', root, root, root))
                self.assertEqual(worker.automation.process_order.call_count,
                                 1 if mode == LABEL_MODE_EXCLUDE_CARTONS else 0)
                result = next(e.payload for e in events if e.event_type == 'result')
                self.assertEqual(result.automation_status, 'skipped')
                self.assertEqual(result.error_explanation, 'released before')
