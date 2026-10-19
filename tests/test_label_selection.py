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
        self.assertEqual(result.skip_explanation, 'released before')

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

    def test_nested_portal_layout_with_order_line_and_summary_rows(self):
        # Portal P.O. cells include a line number and the result table sits
        # inside layout tables alongside the printer and shipping controls.
        self.table([
            ('123 1', 'PRICE', 'available', ''),
            ('123 1', 'INFO', 'available', ''),
            ('123 1', 'SOURCE-TAGGED', 'available', ''),
            ('123 1', 'CARTON', 'available', ''),
            ('123 1', 'MASTER-CARTON', 'available', ''),
        ])
        table = self.page.locator('table').evaluate('(e) => e.outerHTML')
        self.page.set_content('<table><tr><td>' + table +
            '<table><tr><td>Select printing station</td><td>Pick up</td></tr>'
            '<tr><td><select><option>Hong Kong [20]</option></select></td><td></td></tr>'
            '</table></td></tr><tr><td></td><td></td><td></td><td>Request Back</td></tr></table>')
        result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.selected_count, 3)
        self.assertEqual(self.page.locator('input').evaluate_all('(els) => els.map(e => e.checked)'),
                         [True, True, True, False, False])

    def test_all_released_types_are_skipped(self):
        self.table([('123 1', label, status, '') for label, status in
                    [('PRICE', 'requested'), ('INFO', 'released'), ('SOURCE-TAGGED', 'printed'),
                     ('CARTON', 'available')]])
        result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.skip_explanation, 'released before')
        self.assertEqual(result.selected_count, 0)

    def test_available_labels_still_run_when_others_released(self):
        self.table([('123 1', label, status, '') for label, status in
                    [('PRICE', 'requested'), ('INFO', 'available'), ('SOURCE-TAGGED', 'available'),
                     ('MASTER-CARTON', 'available')]])
        result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.selected_count, 2)
        self.assertEqual(result.skip_explanation, '')

    def test_real_unavailable_status_is_not_reported_as_released(self):
        self.table([('123', 'PRICE', 'requested', ''), ('123', 'INFO', 'blocked by factory', '')])
        result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.skip_explanation, '')
        self.assertIn('blocked by factory', result.status_text)
        self.assertEqual(result.selected_count, 0)

    def test_unknown_status_is_not_reported_as_released(self):
        self.table([('123', 'PRICE', 'requested', ''), ('123', 'INFO', '', '')])
        result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.skip_explanation, '')
        self.assertIn('unknown status', result.status_text)

    def test_frame_replacements_during_checkbox_clicks_are_recovered(self):
        self.page.evaluate('''() => {
            window.labelRows = [
                ['PRICE', false], ['INFO', false], ['SOURCE-TAGGED', false],
                ['CARTON', true], ['MASTER-CARTON', true]
            ];
            window.replacements = 0;
            window.renderLabels = () => {
                document.querySelector('#labels')?.remove();
                const frame = document.createElement('iframe');
                frame.id = 'labels';
                frame.srcdoc = '<table><tr><th>P.O.</th><th>Select</th><th>Label Type</th><th>Status</th></tr>'
                    + window.labelRows.map(([label, checked], i) =>
                        `<tr><td>123 1</td><td><input type="checkbox" ${checked ? 'checked' : ''}
                         onclick="parent.changeLabel(${i}, this.checked)"></td><td>${label}</td><td>available</td></tr>`
                      ).join('') + '</table>';
                document.body.append(frame);
            };
            window.changeLabel = (i, checked) => {
                window.labelRows[i][1] = checked;
                window.replacements += 1;
                window.renderLabels();
            };
            window.renderLabels();
        }''')
        self.page.frame_locator('#labels').locator('input').first.wait_for()
        result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.selected_count, 3)
        self.assertEqual(self.page.evaluate('labelRows.map(r => r[1])'),
                         [True, True, True, False, False])
        self.assertGreater(self.page.evaluate('replacements'), 0)

    def test_detached_unrelated_frame_does_not_fail_valid_label_frame(self):
        from unittest.mock import Mock
        from playwright.sync_api import Error
        self.table([('123', 'PRICE', 'available', '')])
        detached = Mock()
        detached.evaluate.side_effect = Error('Frame.evaluate: Frame was detached')
        with patch.object(self.automation, '_search_contexts', return_value=[detached, self.page]):
            result = self.automation._select_non_carton_labels('123')
        self.assertEqual(result.selected_count, 1)

    def test_frames_after_valid_label_frame_are_not_evaluated(self):
        from unittest.mock import Mock
        from playwright.sync_api import Error
        self.table([('123', 'PRICE', 'requested', '')])
        detached = Mock()
        detached.evaluate.side_effect = Error('Frame.evaluate: Frame was detached')
        with patch.object(self.automation, '_search_contexts', return_value=[self.page, detached]):
            result = self.automation._select_non_carton_labels('123')
        detached.evaluate.assert_not_called()
        self.assertEqual(result.skip_explanation, 'released before')

    def test_persistent_frame_replacements_fail_with_specific_timeout(self):
        from unittest.mock import Mock
        from playwright.sync_api import Error
        self.automation.config.data['timing']['default_timeout_ms'] = 20
        detached = Mock()
        detached.evaluate.side_effect = Error('Frame.evaluate: Frame was detached')
        with patch.object(self.automation, '_search_contexts', return_value=[detached]), \
             patch.object(self.automation, '_ensure_logged_in'):
            with self.assertRaisesRegex(RuntimeError, 'Label table did not become stable.*Frame was detached'):
                self.automation._select_non_carton_labels('123')

    def test_real_script_error_is_not_hidden_as_frame_refresh(self):
        from unittest.mock import Mock
        from playwright.sync_api import Error
        bad_frame = Mock()
        bad_frame.evaluate.side_effect = Error('Frame.evaluate: TypeError: unexpected portal markup')
        with patch.object(self.automation, '_search_contexts', return_value=[bad_frame]):
            with self.assertRaisesRegex(RuntimeError, 'TypeError: unexpected portal markup'):
                self.automation._select_non_carton_labels('123')
