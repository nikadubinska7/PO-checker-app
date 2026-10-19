from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from po_label_app.automation import PortalAutomation
from po_label_app.config import load_config
from po_label_app.models import LABEL_MODE_EXCLUDE_CARTONS, PurchaseOrder
from po_label_app.run_context import RunContext


class LabelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.automation = PortalAutomation(
            load_config(), RunContext('test', Path('.'), Path('.'), Path('.')),
            threading.Event(), threading.Event(),
        )
        self.automation.page = self.page
        self.automation._interaction_delay = lambda: None

    def tearDown(self):
        self.page.close()

    def table(self, rows):
        self.page.set_content('<table><tr><th>P.O.</th><th>Select</th>'
                              '<th>Label Type</th><th>Status</th></tr>' + ''.join(
            f'<tr><td>{po}</td><td><input type="checkbox" checked {disabled}></td>'
            f'<td>{label}</td><td>{status}</td></tr>'
            for po, label, status, disabled in rows
        ) + '</table>')

    def test_all_eligible_types_and_exact_available_status(self):
        self.table([
            ('123', 'PRICE', 'available', ''),
            ('123', 'INFO', 'available', ''),
            ('123', 'NEW TYPE', ' Available ', ''),
            ('123', 'CARTON', 'available', ''),
            ('123', 'MASTER-CARTON', 'available', ''),
            ('123', 'OTHER', 'unavailable', ''),
            ('999', 'PRICE', 'available', ''),
        ])
        result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.selected_count, 3)
        self.assertEqual(self.page.locator('input').evaluate_all('(els) => els.map(e => e.checked)'),
                         [True, True, True, False, False, False, True])

    def test_disabled_selected_carton_blocks_request(self):
        self.table([('123', 'PRICE', 'available', ''), ('123', 'CARTON', 'available', 'disabled')])
        with self.assertRaisesRegex(RuntimeError, 'checkbox disabled'):
            self.automation._select_non_carton_labels('123')

    def test_already_requested_is_skipped(self):
        self.table([('123', 'PRICE', 'requested', ''), ('123', 'CARTON', 'available', '')])
        result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.selected_count, 0)
        self.assertEqual(result.skip_explanation, 'Eligible labels already requested')

    def test_speed_scales_delays_without_shortening_timeouts(self):
        del self.automation._interaction_delay
        with patch('po_label_app.automation.random.uniform', return_value=1.5), patch('po_label_app.automation.time.sleep') as sleep:
            self.automation._interaction_delay()
            sleep.assert_called_once_with(0.5)
        self.assertEqual(self.automation.config.timing['refresh_timeout_ms'], 30000)

    def test_dry_run_does_not_click_final_request(self):
        self.table([('123', 'PRICE', 'available', ''), ('123', 'CARTON', 'available', '')])
        automation = self.automation
        with patch.object(automation, '_ensure_logged_in'), \
             patch.object(automation, '_fill_po'), \
             patch.object(automation, '_click_configured') as click, \
             patch.object(automation, '_load_delay'), \
             patch.object(automation, '_wait_for_refresh_result'), \
             patch.object(automation, '_po_found', return_value=True), \
             patch.object(automation, '_check_labels_checkbox'), \
             patch.object(automation, '_select_printer'), \
             patch.object(automation, '_screenshot', return_value=None):
            result = automation.process_order(PurchaseOrder('123', 'HK', 2), True, LABEL_MODE_EXCLUDE_CARTONS)
        self.assertEqual(result.automation_status, 'dry_run_success')
        self.assertNotIn('final_request_button', [call.args[0] for call in click.call_args_list])
