from __future__ import annotations

import logging
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .config import AppConfig
from .models import (
    ProcessingResult,
    PurchaseOrder,
    STATUS_DRY_RUN_SUCCESS,
    STATUS_ERROR,
    STATUS_REQUESTED,
)
from .run_context import RunContext


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
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=False)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
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
            page.get_by_text(re.compile(re.escape(found_text), re.I)).first.wait_for(timeout=5000)
        except PlaywrightTimeoutError:
            try:
                page.get_by_text(po).first.wait_for(timeout=5000)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError("Timeout after refresh; order result did not appear") from exc

    def _po_found(self, po: str) -> bool:
        page = self._page()
        content = page.locator("body").inner_text(timeout=5000)
        zero_indicator = str(self.config.texts.get("zero_orders_indicator", "0 Order/s found")).lower()
        if zero_indicator in content.lower():
            return False
        if po in content:
            return True
        found_indicator = str(self.config.texts.get("found_indicator", "Order/s found")).lower()
        return found_indicator in content.lower() and "0 order/s found" not in content.lower()

    def _check_labels_checkbox(self, po: str) -> None:
        locator = self._first_locator("labels_checkbox", po=po)
        if locator.is_checked(timeout=3000):
            return
        locator.check()
        self._interaction_delay()

    def _extract_status_text(self, po: str) -> str:
        page = self._page()
        selectors = self.config.selectors.get("status_cells", {})
        lines: list[str] = []
        for css in selectors.get("css", []):
            rendered = self._render_selector(css, po=po)
            locator = page.locator(rendered)
            count = min(locator.count(), 10)
            for index in range(count):
                item = locator.nth(index)
                try:
                    if item.is_visible(timeout=1000):
                        text = item.inner_text(timeout=2000).strip()
                        if text:
                            lines.append(text)
                except PlaywrightError:
                    continue
        if lines:
            combined = " | ".join(dict.fromkeys(lines))
            if len(combined) > 250:
                return combined[:247] + "..."
            return combined
        body_text = page.locator("body").inner_text(timeout=5000)
        available_text = str(self.config.texts.get("available_status", "available"))
        if re.search(re.escape(available_text), body_text, re.I):
            return available_text
        return "Status is not available"

    def _select_printer(self, printer_code: str) -> None:
        target = self.config.printer_target(printer_code)
        dropdown = self._first_locator("printer_dropdown")
        tag_name = dropdown.evaluate("element => element.tagName.toLowerCase()")
        if tag_name == "select":
            try:
                dropdown.select_option(label=target)
                self._interaction_delay()
                return
            except PlaywrightError:
                options = dropdown.locator("option").all_inner_texts()
                match = next((option for option in options if target.lower() in option.lower()), None)
                if match:
                    dropdown.select_option(label=match)
                    self._interaction_delay()
                    return
                raise RuntimeError(f"Printer option missing: {target}")

        dropdown.click()
        self._interaction_delay()
        page = self._page()
        option = page.get_by_text(re.compile(re.escape(target), re.I)).first
        if not option.is_visible(timeout=5000):
            raise RuntimeError(f"Printer option missing: {target}")
        option.click()
        self._interaction_delay()

    def _wait_for_success_popup(self) -> None:
        page = self._page()
        success = str(self.config.texts.get("success_popup", "Labels requested successfully."))
        timeout = int(self.config.timing.get("success_timeout_ms", 20000))
        page.get_by_text(re.compile(re.escape(success), re.I)).first.wait_for(timeout=timeout)
        self._click_configured("ok_button")

    def _ensure_logged_in(self) -> None:
        if self._looks_like_login_page():
            raise SessionExpiredError("Portal session appears expired. Log in again, then resume.")

    def _looks_like_login_page(self) -> bool:
        page = self._page()
        try:
            content = page.locator("body").inner_text(timeout=3000).lower()
        except PlaywrightError:
            return False
        indicators = self.config.texts.get("login_indicators", [])
        return any(str(indicator).strip().lower() in content for indicator in indicators if indicator)

    def _click_configured(self, selector_key: str) -> None:
        locator = self._first_locator(selector_key)
        locator.click()
        self._interaction_delay()

    def _first_locator(self, selector_key: str, po: str = "") -> Locator:
        page = self._page()
        selectors = self.config.selectors.get(selector_key, {})
        candidates: list[Locator] = []

        for label in selectors.get("labels", []):
            candidates.append(page.get_by_label(re.compile(re.escape(str(label)), re.I)).first)
        for role_config in selectors.get("roles", []):
            role = role_config.get("role")
            name = role_config.get("name")
            if role and name:
                candidates.append(page.get_by_role(role, name=re.compile(re.escape(str(name)), re.I)).first)
        for text in selectors.get("texts", []):
            candidates.append(page.get_by_text(re.compile(re.escape(str(text)), re.I)).first)
        for css in selectors.get("css", []):
            candidates.append(page.locator(self._render_selector(css, po=po)).first)

        for locator in candidates:
            try:
                if locator.is_visible(timeout=2500):
                    return locator
            except PlaywrightError:
                continue
        raise RuntimeError(f"Could not find portal element for selector group '{selector_key}'")

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
