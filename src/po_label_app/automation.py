from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .config import AppConfig
from .models import (
    ProcessingResult,
    PurchaseOrder,
    STATUS_DRY_RUN_SUCCESS,
    STATUS_ERROR,
    STATUS_REQUESTED,
)
from .run_context import RunContext
from .paths import bundled_playwright_browsers_dir, default_browser_profile_dir


LOGGER = logging.getLogger(__name__)


class SessionExpiredError(RuntimeError):
    pass


class StopRequestedError(RuntimeError):
    pass


class PortalAutomation:
    def __init__(
        self,
        config: AppConfig,
        run_context: RunContext,
        pause_event: threading.Event,
        stop_event: threading.Event,
        status_callback: Optional[Callable[[str], None]] = None,
    ):
        self.config = config
        self.run_context = run_context
        self.pause_event = pause_event
        self.stop_event = stop_event
        self.status_callback = status_callback or (lambda _message: None)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page: Optional[Page] = None

    def open_portal(self) -> None:
        browsers_dir = bundled_playwright_browsers_dir()
        if browsers_dir:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(default_browser_profile_dir()),
            headless=False,
        )
        self.browser = None
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(int(self.config.timing.get("default_timeout_ms", 15000)))
        self.page.goto(self.config.portal_url, wait_until="domcontentloaded")
        self._load_delay()
        self.status_callback("Portal opened. Log in manually, then click Start Processing.")

    def close(self) -> None:
        for item in (self.context, self.browser):
            if item:
                try:
                    item.close()
                except PlaywrightError:
                    LOGGER.exception("Failed to close Playwright item")
        if self.playwright:
            try:
                self.playwright.stop()
            except PlaywrightError:
                LOGGER.exception("Failed to stop Playwright")

    def process_order(self, order: PurchaseOrder, dry_run: bool) -> ProcessingResult:
        if not self.page:
            raise RuntimeError("Portal browser is not open")

        try:
            self._guard_control_state()
            self._ensure_logged_in()
            self.status_callback(f"Processing PO {order.po}")
            self._fill_po(order.po)
            self._click_configured("refresh_button")
            self._load_delay()
            self._wait_for_refresh_result(order.po)

            if not self._po_found(order.po):
                screenshot = self._screenshot(order.po, "error")
                return ProcessingResult.create(
                    po=order.po,
                    printer=order.printer,
                    automation_status=STATUS_ERROR,
                    error_explanation="PO not found",
                    run_id=self.run_context.run_id,
                    screenshot_path=screenshot,
                )

            self._check_labels_checkbox(order.po)
            self._click_configured("request_labels_button")
            self._load_delay()
            status_text = self._extract_status_text(order.po)
            available_text = str(self.config.texts.get("available_status", "available")).strip().lower()
            if available_text not in status_text.lower():
                screenshot = self._screenshot(order.po, "error")
                return ProcessingResult.create(
                    po=order.po,
                    printer=order.printer,
                    automation_status=STATUS_ERROR,
                    error_explanation=status_text or "Status is not available",
                    run_id=self.run_context.run_id,
                    screenshot_path=screenshot,
                )

            self._select_printer(order.printer)
            if dry_run:
                screenshot = self._screenshot(order.po, "dry_run_success")
                return ProcessingResult.create(
                    po=order.po,
                    printer=order.printer,
                    automation_status=STATUS_DRY_RUN_SUCCESS,
                    error_explanation="Dry run reached final Request step; Request was not clicked",
                    run_id=self.run_context.run_id,
                    screenshot_path=screenshot,
                )

            self._click_configured("final_request_button")
            self._wait_for_success_popup()
            screenshot = None
            if bool(self.config.debug.get("screenshot_successes", False)):
                screenshot = self._screenshot(order.po, "requested")
            return ProcessingResult.create(
                po=order.po,
                printer=order.printer,
                automation_status=STATUS_REQUESTED,
                error_explanation="",
                run_id=self.run_context.run_id,
                screenshot_path=screenshot,
            )
        except SessionExpiredError:
            raise
        except StopRequestedError:
            raise
        except Exception as exc:
            LOGGER.exception("PO %s failed", order.po)
            screenshot = self._screenshot(order.po, "error")
            return ProcessingResult.create(
                po=order.po,
                printer=order.printer,
                automation_status=STATUS_ERROR,
                error_explanation=str(exc),
                run_id=self.run_context.run_id,
                screenshot_path=screenshot,
            )

    def _fill_po(self, po: str) -> None:
        input_locator = self._first_locator("po_input")
        input_locator.fill("")
        self._interaction_delay()
        input_locator.fill(po)
        self._interaction_delay()

    def _wait_for_refresh_result(self, po: str) -> None:
        page = self._page()
        timeout = int(self.config.timing.get("refresh_timeout_ms", 30000))
        found_text = str(self.config.texts.get("found_indicator", "Order/s found"))
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except PlaywrightTimeoutError:
            LOGGER.info("Network idle timeout after refresh; continuing with content checks")
        try:
            self._first_text_locator(found_text).wait_for(timeout=5000)
        except PlaywrightTimeoutError:
            try:
                self._first_text_locator(po).wait_for(timeout=5000)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError("Timeout after refresh; order result did not appear") from exc

    def _po_found(self, po: str) -> bool:
        content = self._body_text()
        zero_indicator = str(self.config.texts.get("zero_orders_indicator", "0 Order/s found")).lower()
        if zero_indicator in content.lower():
            return False
        if po in content:
            return True
        found_indicator = str(self.config.texts.get("found_indicator", "Order/s found")).lower()
        return found_indicator in content.lower() and "0 order/s found" not in content.lower()

    def _check_labels_checkbox(self, po: str) -> None:
        locator = self._first_locator("labels_checkbox", po=po)
        if self._is_checked(locator):
            return
        try:
            locator.scroll_into_view_if_needed(timeout=5000)
            locator.check(timeout=5000)
        except PlaywrightError:
            LOGGER.info("Normal checkbox check failed for PO %s; retrying with force", po)
            try:
                locator.check(force=True, timeout=5000)
            except PlaywrightError:
                try:
                    locator.click(force=True, timeout=5000)
                except PlaywrightError:
                    self._check_with_dom_fallback(locator)
        if not self._is_checked(locator):
            raise RuntimeError("Labels checkbox did not become checked")
        self._interaction_delay()

    def _extract_status_text(self, po: str) -> str:
        table_status = self._status_text_from_label_rows(po)
        if table_status:
            return table_status

        selectors = self.config.selectors.get("status_cells", {})
        lines: list[str] = []
        for context in self._search_contexts():
            for xpath in selectors.get("xpaths", []):
                lines.extend(self._visible_texts(context.locator(f"xpath={self._render_selector(xpath, po=po)}")))
        if lines:
            return self._combine_status_lines(lines)

        body_text = self._body_text()
        available_text = str(self.config.texts.get("available_status", "available"))
        if re.search(re.escape(available_text), body_text, re.I):
            return available_text
        return "Status is not available"

    def _status_text_from_label_rows(self, po: str) -> str:
        statuses: list[str] = []
        script = """
        po => {
            const labelTypes = new Set(['PRICE', 'INFO', 'CARTON', 'MASTER-CARTON']);
            const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
            const cellText = element => {
                const parts = [];
                const visit = node => {
                    if (node.nodeType === Node.TEXT_NODE) {
                        parts.push(node.textContent || '');
                        return;
                    }
                    if (node.nodeType !== Node.ELEMENT_NODE || node.tagName === 'TABLE') {
                        return;
                    }
                    for (const child of node.childNodes) {
                        visit(child);
                    }
                };
                for (const child of element.childNodes) {
                    visit(child);
                }
                return normalize(parts.join(' '));
            };
            const directCells = row => Array.from(row.children)
                .filter(child => child.tagName === 'TD' || child.tagName === 'TH');
            const canonical = value => normalize(value).toLowerCase();
            const statuses = [];

            for (const table of document.querySelectorAll('table')) {
                const rows = Array.from(table.querySelectorAll('tr'));
                let headerRowIndex = -1;
                let poIndex = -1;
                let statusIndex = -1;

                for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
                    const headers = directCells(rows[rowIndex]).map(cell => canonical(cellText(cell)));
                    const possiblePoIndex = headers.findIndex(text => text === 'p.o.' || text === 'p.o' || text === 'po');
                    const possibleStatusIndex = headers.findIndex(text => text === 'status');
                    if (possiblePoIndex >= 0 && possibleStatusIndex >= 0) {
                        headerRowIndex = rowIndex;
                        poIndex = possiblePoIndex;
                        statusIndex = possibleStatusIndex;
                        break;
                    }
                }

                if (headerRowIndex < 0) {
                    continue;
                }

                for (const row of rows.slice(headerRowIndex + 1)) {
                    const cells = directCells(row);
                    const texts = cells.map(cell => cellText(cell));
                    if (texts.length <= Math.max(poIndex, statusIndex)) {
                        continue;
                    }
                    const poCell = texts[poIndex] || '';
                    if (!poCell.includes(po) && !texts.some(text => text.includes(po))) {
                        continue;
                    }
                    if (!texts.some(text => labelTypes.has(text))) {
                        continue;
                    }
                    const status = texts[statusIndex] || '';
                    if (status) {
                        statuses.push(status);
                    }
                }
            }

            return Array.from(new Set(statuses));
        }
        """
        for context in self._search_contexts():
            try:
                found = context.evaluate(script, po)
            except PlaywrightError:
                continue
            if isinstance(found, list):
                statuses.extend(str(status).strip() for status in found if str(status).strip())
        return self._combine_status_lines(statuses) if statuses else ""

    def _select_printer(self, printer_code: str) -> None:
        target = self.config.printer_target(printer_code)
        try:
            dropdown = self._first_locator("printer_dropdown")
            if self._select_option_from_select(dropdown, target):
                return

            if not self._is_select_locator(dropdown):
                dropdown.click()
                self._interaction_delay()
                page = self._page()
                option = page.get_by_text(re.compile(re.escape(target), re.I)).first
                if option.is_visible(timeout=5000):
                    option.click()
                    self._interaction_delay()
                    return
        except PlaywrightError:
            LOGGER.info("Configured printer dropdown did not select %s; scanning all selects", target)

        if self._select_printer_from_visible_selects(target):
            return

        raise RuntimeError(f"Printer option missing: {target}")

    def _select_printer_from_visible_selects(self, target: str) -> bool:
        for context in self._search_contexts():
            selects = context.locator("select")
            try:
                count = min(selects.count(), 30)
            except PlaywrightError:
                continue
            for index in range(count):
                select = selects.nth(index)
                try:
                    if not select.is_visible(timeout=1000):
                        continue
                except PlaywrightError:
                    continue
                if self._select_option_from_select(select, target):
                    return True
        return False

    def _select_option_from_select(self, select: Locator, target: str) -> bool:
        try:
            if select.evaluate("element => element.tagName.toLowerCase()") != "select":
                return False
            options = select.locator("option").all_inner_texts()
        except PlaywrightError:
            return False

        normalized_target = self._normalize_option_text(target)
        match_index = next(
            (
                index
                for index, option in enumerate(options)
                if self._normalize_option_text(option) == normalized_target
            ),
            None,
        )
        if match_index is None:
            match_index = next(
                (
                    index
                    for index, option in enumerate(options)
                    if normalized_target in self._normalize_option_text(option)
                ),
                None,
            )
        if match_index is None:
            return False

        try:
            select.select_option(index=match_index, timeout=5000)
        except PlaywrightError:
            select.evaluate(
                """
                (select, index) => {
                    select.selectedIndex = index;
                    select.dispatchEvent(new Event('input', { bubbles: true }));
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """,
                match_index,
            )
        self._interaction_delay()
        return True

    def _is_select_locator(self, locator: Locator) -> bool:
        try:
            return locator.evaluate("element => element.tagName.toLowerCase()") == "select"
        except PlaywrightError:
            return False

    def _normalize_option_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text)).strip().lower()

    def _wait_for_success_popup(self) -> None:
        success = str(self.config.texts.get("success_popup", "Labels requested successfully."))
        timeout = int(self.config.timing.get("success_timeout_ms", 20000))
        self._first_text_locator(success).wait_for(timeout=timeout)
        self._click_configured("ok_button")

    def _ensure_logged_in(self) -> None:
        if self._looks_like_login_page():
            raise SessionExpiredError("Portal session appears expired. Log in again, then resume.")

    def _looks_like_login_page(self) -> bool:
        content = self._body_text(timeout=3000).lower()
        indicators = self.config.texts.get("login_indicators", [])
        return any(str(indicator).strip().lower() in content for indicator in indicators if indicator)

    def _click_configured(self, selector_key: str) -> None:
        locator = self._first_locator(selector_key)
        try:
            locator.scroll_into_view_if_needed(timeout=5000)
            locator.click(timeout=5000)
        except PlaywrightError:
            LOGGER.info("Normal click failed for selector group %s; retrying with force", selector_key)
            locator.click(force=True, timeout=5000)
        self._interaction_delay()

    def _first_locator(self, selector_key: str, po: str = "") -> Locator:
        selectors = self.config.selectors.get(selector_key, {})
        for context in self._search_contexts():
            candidates: list[Locator] = []
            for xpath in selectors.get("xpaths", []):
                candidates.append(context.locator(f"xpath={self._render_selector(xpath, po=po)}").first)
            for label in selectors.get("labels", []):
                candidates.append(context.get_by_label(re.compile(re.escape(str(label)), re.I)).first)
            for role_config in selectors.get("roles", []):
                role = role_config.get("role")
                name = role_config.get("name")
                if role and name:
                    candidates.append(context.get_by_role(role, name=re.compile(re.escape(str(name)), re.I)).first)
            for text in selectors.get("texts", []):
                candidates.append(context.get_by_text(re.compile(re.escape(str(text)), re.I)).first)
            for css in selectors.get("css", []):
                candidates.append(context.locator(self._render_selector(css, po=po)).first)

            for locator in candidates:
                try:
                    if locator.is_visible(timeout=2500):
                        return locator
                except PlaywrightError:
                    continue

        page = self._page()
        raise RuntimeError(
            f"Could not find portal element for selector group '{selector_key}' "
            f"on page '{page.title()}' at {page.url}"
        )

    def _search_contexts(self) -> list[Page | Frame]:
        page = self._page()
        contexts: list[Page | Frame] = [page]
        for frame in page.frames:
            try:
                if not frame.is_detached():
                    contexts.append(frame)
            except PlaywrightError:
                continue
        return contexts

    def _first_text_locator(self, text: str) -> Locator:
        for context in self._search_contexts():
            locator = context.get_by_text(re.compile(re.escape(text), re.I)).first
            try:
                if locator.is_visible(timeout=1000):
                    return locator
            except PlaywrightError:
                continue
        return self._page().get_by_text(re.compile(re.escape(text), re.I)).first

    def _body_text(self, timeout: int = 5000) -> str:
        text_parts: list[str] = []
        for context in self._search_contexts():
            try:
                text_parts.append(context.locator("body").inner_text(timeout=timeout))
            except PlaywrightError:
                continue
        return "\n".join(text_parts)

    def _visible_texts(self, locator: Locator) -> list[str]:
        lines: list[str] = []
        try:
            count = min(locator.count(), 10)
        except PlaywrightError:
            return lines
        for index in range(count):
            item = locator.nth(index)
            try:
                if item.is_visible(timeout=1000):
                    text = item.inner_text(timeout=2000).strip()
                    if text:
                        lines.append(text)
            except PlaywrightError:
                continue
        return lines

    def _combine_status_lines(self, lines: list[str]) -> str:
        combined = " | ".join(dict.fromkeys(line for line in lines if line))
        if len(combined) > 250:
            return combined[:247] + "..."
        return combined

    def _is_checked(self, locator: Locator) -> bool:
        try:
            return locator.is_checked(timeout=1000)
        except PlaywrightError:
            return False

    def _check_with_dom_fallback(self, locator: Locator) -> None:
        locator.evaluate(
            """
            element => {
                element.scrollIntoView({ block: 'center', inline: 'center' });
                if (element.disabled) {
                    throw new Error('Labels checkbox is disabled');
                }
                element.click();
                if (!element.checked) {
                    element.checked = true;
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
            """
        )

    def _render_selector(self, selector: str, po: str = "") -> str:
        return selector.replace("{{PO}}", po)

    def _screenshot(self, po: str, status: str) -> Optional[Path]:
        page = self.page
        if not page:
            return None
        safe_po = re.sub(r"[^A-Za-z0-9_.-]+", "_", po)
        timestamp = time.strftime("%Y-%m-%d_%H%M%S")
        path = self.run_context.screenshot_dir / f"PO_{safe_po}_{status}_{timestamp}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            return path
        except PlaywrightError:
            LOGGER.exception("Failed to save screenshot for PO %s", po)
            return None

    def _guard_control_state(self) -> None:
        if self.stop_event.is_set():
            raise StopRequestedError("Stop requested")
        while self.pause_event.is_set():
            self.status_callback("Paused")
            time.sleep(0.3)
            if self.stop_event.is_set():
                raise StopRequestedError("Stop requested")

    def _interaction_delay(self) -> None:
        self._guard_control_state()
        timing = self.config.timing
        time.sleep(
            random.uniform(
                float(timing.get("interaction_delay_min_seconds", 0.5)),
                float(timing.get("interaction_delay_max_seconds", 2.0)),
            )
        )

    def _load_delay(self) -> None:
        self._guard_control_state()
        timing = self.config.timing
        time.sleep(
            random.uniform(
                float(timing.get("load_delay_min_seconds", 1.0)),
                float(timing.get("load_delay_max_seconds", 3.0)),
            )
        )

    def _page(self) -> Page:
        if not self.page:
            raise RuntimeError("Portal page is not available")
        return self.page
