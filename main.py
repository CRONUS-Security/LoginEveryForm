"""
LoginEveryForm - Password Breach Verification Tool
Main GUI Application using PySide6
"""

# NOTE: env vars must be set before ANY playwright import.
import sys
import os
import multiprocessing
from pathlib import Path

# Required for PyInstaller --onefile on Windows: prevents frozen subprocesses
# from re-running the full application instead of acting as worker processes.
if getattr(sys, "frozen", False):
    multiprocessing.freeze_support()
    # Single-file binary: store browsers in a persistent user-level directory.
    _browsers_dir = Path.home() / ".logineveryform" / "playwright-browsers"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_browsers_dir))

import asyncio
import random
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QProgressBar,
    QFileDialog, QGroupBox, QSpinBox, QCheckBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QTextCursor

from config import Config
from modules.logger import init_logger, get_logger
from modules.password_loader import PasswordLoader, Credential
from modules.browser_automation import (
    BrowserAutomation, BrowserType, LoginResult, LoginStatus
)


class LoginWorker(QThread):
    """Worker thread for login operations"""

    progress = Signal(int, int, str)  # current, total, message
    result = Signal(object)  # LoginResult
    finished = Signal(list)  # List of results
    error = Signal(str)

    def __init__(
        self,
        url: str,
        credentials: List[Credential],
        browser_type: str,
        headless: bool,
        username_selector: Optional[str],
        password_selector: Optional[str],
        captcha_selector: Optional[str],
        captcha_image_selector: Optional[str],
        submit_selector: Optional[str],
        success_indicator: Optional[str],
        delay: int,
        delay_jitter: float,
        enable_captcha: bool = True,
        session_isolation: str = "none",
    ):
        super().__init__()
        self.url = url
        self.credentials = credentials
        self.browser_type = browser_type
        self.headless = headless
        self.username_selector = username_selector if username_selector else None
        self.password_selector = password_selector if password_selector else None
        # Honour enable_captcha flag: if disabled, treat captcha fields as absent
        self.captcha_selector = (captcha_selector if captcha_selector else None) if enable_captcha else None
        self.captcha_image_selector = (captcha_image_selector if captcha_image_selector else None) if enable_captcha else None
        self.submit_selector = submit_selector if submit_selector else None
        self.success_indicator = success_indicator if success_indicator else None
        self.delay = delay
        self.delay_jitter = max(0.0, min(1.0, delay_jitter))
        # "none" | "medium" | "high"
        self.session_isolation = session_isolation
        self._is_running = True

    async def _attempt_with_retry(
        self,
        automation: "BrowserAutomation",
        credential: "Credential",
        idx: int,
        total: int,
        **kwargs,
    ) -> "LoginResult":
        """Attempt login up to 3 times, retrying on CAPTCHA_REQUIRED or TIMEOUT."""
        MAX_RETRIES = 3
        result = None
        for attempt in range(MAX_RETRIES):
            result = await automation.attempt_login(credential=credential, **kwargs)
            if result.status not in (LoginStatus.CAPTCHA_REQUIRED, LoginStatus.TIMEOUT):
                return result
            if attempt < MAX_RETRIES - 1:
                self.progress.emit(
                    idx, total,
                    f"[重试 {attempt + 2}/{MAX_RETRIES}] {credential.username}: {result.status.value}",
                )
                await asyncio.sleep(2.0)
        return result  # return last result after exhausting retries

    def run(self):
        """Run the login automation"""
        try:
            asyncio.run(self._async_run())
        except Exception as e:
            self.error.emit(f"Worker error: {str(e)}")

    async def _async_run(self):
        """Async execution"""
        automation = None
        try:
            browser_type_enum = BrowserType[self.browser_type.upper()]

            async def _make_automation() -> BrowserAutomation:
                auto = BrowserAutomation(
                    browser_type=browser_type_enum,
                    headless=self.headless,
                    screenshot_dir=str(Config.SCREENSHOTS_DIR)
                )
                await auto.start()
                return auto

            results = []
            total = len(self.credentials)

            if self.session_isolation == "high":
                # High isolation: fresh browser instance per credential
                for idx, credential in enumerate(self.credentials, 1):
                    if not self._is_running:
                        break

                    self.progress.emit(idx, total, f"Testing: {credential.username}")

                    per_attempt_automation = None
                    try:
                        per_attempt_automation = await _make_automation()
                        result = await self._attempt_with_retry(
                            per_attempt_automation, credential, idx, total,
                            url=self.url,
                            username_selector=self.username_selector,
                            password_selector=self.password_selector,
                            captcha_selector=self.captcha_selector,
                            captcha_image_selector=self.captcha_image_selector,
                            submit_selector=self.submit_selector,
                            success_indicator=self.success_indicator,
                            session_isolation="high",
                        )
                    finally:
                        if per_attempt_automation:
                            await per_attempt_automation.stop()

                    results.append(result)
                    self.result.emit(result)

                    if idx < total and self._is_running:
                        multiplier = random.uniform(1 - self.delay_jitter, 1 + self.delay_jitter)
                        actual_ms = max(0, self.delay * multiplier)
                        await asyncio.sleep(actual_ms / 1000)

            else:
                # "none" or "medium": single shared browser instance
                # Initialize browser
                automation = await _make_automation()

                for idx, credential in enumerate(self.credentials, 1):
                    if not self._is_running:
                        break

                    self.progress.emit(idx, total, f"Testing: {credential.username}")

                    result = await self._attempt_with_retry(
                        automation, credential, idx, total,
                        url=self.url,
                        username_selector=self.username_selector,
                        password_selector=self.password_selector,
                        captcha_selector=self.captcha_selector,
                        captcha_image_selector=self.captcha_image_selector,
                        submit_selector=self.submit_selector,
                        success_indicator=self.success_indicator,
                        session_isolation=self.session_isolation,
                    )

                    results.append(result)
                    self.result.emit(result)

                    # Delay between attempts (with jitter)
                    if idx < total and self._is_running:
                        multiplier = random.uniform(1 - self.delay_jitter, 1 + self.delay_jitter)
                        actual_ms = max(0, self.delay * multiplier)
                        await asyncio.sleep(actual_ms / 1000)

            self.finished.emit(results)

        except Exception as e:
            import traceback
            error_details = f"{str(e)}\n\n{traceback.format_exc()}"
            self.error.emit(error_details)

        finally:
            if automation:
                await automation.stop()

    def stop(self):
        """Stop the worker"""
        self._is_running = False


class CheckFormWorker(QThread):
    """Worker thread: open browser, detect login form elements, emit CSS selectors to GUI.

    Also validates any pre-filled selectors by querying them on the live page.
    Emits: {"detected": Dict[str, str|None], "validation": Dict[str, bool]}
    """

    detected = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        url: str,
        browser_type: str,
        headless: bool,
        existing_selectors: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        self.url = url.strip()
        self.browser_type = browser_type
        self.headless = headless
        self.existing_selectors = existing_selectors or {}

    def run(self):
        try:
            asyncio.run(self._async_run())
        except Exception as e:
            self.error.emit(str(e))

    async def _async_run(self):
        automation = None
        try:
            browser_type_enum = BrowserType[self.browser_type.upper()]
            automation = BrowserAutomation(
                browser_type=browser_type_enum,
                headless=self.headless,
                screenshot_dir=str(Config.SCREENSHOTS_DIR),
            )
            await automation.start()

            page = await automation.context.new_page()
            page.set_default_timeout(automation.timeout)
            await page.goto(self.url, wait_until="domcontentloaded")
            await page.wait_for_load_state("load", timeout=automation.timeout)

            selectors = await automation.detect_login_form(page)

            # Validate any pre-filled selectors against the live page
            validation: Dict[str, bool] = {}
            for key, selector in self.existing_selectors.items():
                if selector:
                    try:
                        el = await page.query_selector(selector)
                        validation[key] = el is not None
                    except Exception:
                        validation[key] = False

            await page.close()
            self.detected.emit({"detected": selectors, "validation": validation})
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
        finally:
            if automation:
                await automation.stop()


class InteractiveSelectorWorker(QThread):
    """Worker thread: open browser, inject element picker JS, wait for user to click an element."""

    selected = Signal(str)   # emits CSS selector on successful pick
    cancelled = Signal()     # emits when user presses Esc or times out
    error = Signal(str)

    # Injected into the page; __FIELD__ is replaced with the field label at runtime.
    _PICKER_JS = r"""
(function() {
    if (window.__selectorPickerActive) return;
    window.__selectorPickerActive = true;

    var banner = document.createElement('div');
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#1565C0;color:#fff;padding:10px 16px;font:bold 14px/1.4 sans-serif;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.45);pointer-events:none;';
    banner.textContent = 'ELEMENT PICKER (__FIELD__): Click the element to select it. Press Esc to cancel.';
    document.body.appendChild(banner);

    var hi = document.createElement('div');
    hi.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483646;background:rgba(21,101,192,.18);border:2px solid #1565C0;box-sizing:border-box;';
    document.body.appendChild(hi);

    function cssEscape(s) {
        if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(s);
        return s.replace(/([\x00-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e])/g, '\\$1');
    }

    function getSelector(el) {
        if (!el || el.nodeType !== 1) return '';
        if (el === document.body) return 'body';
        if (el.id) return '#' + cssEscape(el.id);
        var name = el.getAttribute('name');
        if (name) return el.tagName.toLowerCase() + '[name="' + name + '"]';
        if (el.tagName.toLowerCase() === 'input' && el.type) return 'input[type="' + el.type + '"]';
        var parts = [];
        var cur = el;
        while (cur && cur !== document.body) {
            var seg = cur.tagName.toLowerCase();
            if (cur.id) { parts.unshift('#' + cssEscape(cur.id)); break; }
            var sibs = cur.parentNode ? Array.from(cur.parentNode.children).filter(function(c) { return c.tagName === cur.tagName; }) : [];
            if (sibs.length > 1) seg += ':nth-of-type(' + (sibs.indexOf(cur) + 1) + ')';
            parts.unshift(seg);
            cur = cur.parentElement;
        }
        return parts.join(' > ');
    }

    function onMove(e) {
        var el = document.elementFromPoint(e.clientX, e.clientY);
        while (el && (el === hi || el === banner)) el = el.parentElement;
        if (!el) return;
        var r = el.getBoundingClientRect();
        hi.style.left = (r.left + window.scrollX) + 'px';
        hi.style.top = (r.top + window.scrollY) + 'px';
        hi.style.width = r.width + 'px';
        hi.style.height = r.height + 'px';
    }

    function onClick(e) {
        var el = e.target;
        while (el && (el === hi || el === banner)) el = el.parentElement;
        if (!el) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        var sel = getSelector(el);
        cleanup();
        window.__reportSelector(sel);
    }

    function onKey(e) {
        if (e.key === 'Escape') { cleanup(); window.__reportSelector(''); }
    }

    function cleanup() {
        document.removeEventListener('mousemove', onMove, true);
        document.removeEventListener('click', onClick, true);
        document.removeEventListener('keydown', onKey, true);
        if (hi.parentNode) hi.parentNode.removeChild(hi);
        if (banner.parentNode) banner.parentNode.removeChild(banner);
        window.__selectorPickerActive = false;
    }

    document.addEventListener('mousemove', onMove, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKey, true);
})();
"""

    def __init__(self, url: str, browser_type: str, field_label: str = "Element"):
        super().__init__()
        self.url = url.strip()
        self.browser_type = browser_type
        self.field_label = field_label

    def run(self):
        try:
            asyncio.run(self._async_run())
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")

    async def _async_run(self):
        automation = None
        try:
            browser_type_enum = BrowserType[self.browser_type.upper()]
            automation = BrowserAutomation(
                browser_type=browser_type_enum,
                headless=False,  # interactive picker always requires a visible browser
                screenshot_dir=str(Config.SCREENSHOTS_DIR),
            )
            await automation.start()

            page = await automation.context.new_page()
            page.set_default_timeout(automation.timeout)
            await page.goto(self.url, wait_until="domcontentloaded")
            await page.wait_for_load_state("load", timeout=automation.timeout)

            selected_event = asyncio.Event()
            selected_value: Dict[str, Optional[str]] = {"selector": None}

            async def on_selector_reported(selector: str) -> None:
                selected_value["selector"] = selector
                selected_event.set()

            await page.expose_function("__reportSelector", on_selector_reported)

            js = self._PICKER_JS.replace("__FIELD__", self.field_label)
            await page.evaluate(js)

            try:
                await asyncio.wait_for(selected_event.wait(), timeout=300)
            except asyncio.TimeoutError:
                self.cancelled.emit()
                return

            await page.close()
            selector = selected_value["selector"]
            if selector:
                self.selected.emit(selector)
            else:
                self.cancelled.emit()

        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
        finally:
            if automation:
                await automation.stop()


class GuidedPickerWorker(QThread):
    """Worker thread: open browser once, guide user through multiple fields sequentially."""

    field_selected = Signal(str, str)  # (field_key, css_selector)
    field_skipped = Signal(str)        # field_key skipped by Esc / timeout
    all_done = Signal()
    error = Signal(str)

    # Same picker JS; __FIELD__ is replaced per-field at runtime.
    _PICKER_JS = InteractiveSelectorWorker._PICKER_JS

    def __init__(self, url: str, browser_type: str, fields: List[tuple]):
        """
        fields: ordered list of (field_key, field_label) pairs, e.g.
                [("username", "Username Field"), ("password", "Password Field"), ...]
        """
        super().__init__()
        self.url = url.strip()
        self.browser_type = browser_type
        self.fields = fields

    def run(self):
        try:
            asyncio.run(self._async_run())
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")

    async def _async_run(self):
        automation = None
        try:
            browser_type_enum = BrowserType[self.browser_type.upper()]
            automation = BrowserAutomation(
                browser_type=browser_type_enum,
                headless=False,
                screenshot_dir=str(Config.SCREENSHOTS_DIR),
            )
            await automation.start()

            page = await automation.context.new_page()
            page.set_default_timeout(automation.timeout)
            await page.goto(self.url, wait_until="domcontentloaded")
            await page.wait_for_load_state("load", timeout=automation.timeout)

            queue: asyncio.Queue = asyncio.Queue()

            async def on_selector_reported(selector: str) -> None:
                await queue.put(selector)

            await page.expose_function("__reportSelector", on_selector_reported)

            for field_key, field_label in self.fields:
                js = self._PICKER_JS.replace("__FIELD__", field_label)
                await page.evaluate(js)

                try:
                    selector = await asyncio.wait_for(queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    self.field_skipped.emit(field_key)
                    break

                if selector:
                    self.field_selected.emit(field_key, selector)
                else:
                    self.field_skipped.emit(field_key)

            await page.close()
            self.all_done.emit()

        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
        finally:
            if automation:
                await automation.stop()


class ResponseProbeWorker(QThread):
    """Worker thread: probe the login form with two scenarios to distinguish server responses.

    Scenario 1 (captcha present): wrong credentials + deliberately wrong captcha
    Scenario 2 (captcha present): wrong credentials + correctly solved captcha
    Scenario   (no captcha):      wrong credentials only

    Retries automatically on timeout or failed captcha recognition.
    """

    probe_log = Signal(str)       # incremental log messages
    probe_done = Signal(list)     # List[Dict] – one dict per scenario
    error = Signal(str)

    _PROBE_USERNAME = "probe_invalid_9x7k2@test.invalid"
    _PROBE_PASSWORD = "Probe!Invalid_p4ss9x7k2"
    _WRONG_CAPTCHA = "XXXXX"

    def __init__(
        self,
        url: str,
        browser_type: str,
        headless: bool,
        username_selector: str,
        password_selector: str,
        captcha_selector: str,
        captcha_image_selector: str,
        submit_selector: str,
    ):
        super().__init__()
        self.url = url
        self.browser_type = browser_type
        self.headless = headless
        self.username_selector = username_selector
        self.password_selector = password_selector
        self.captcha_selector = captcha_selector
        self.captcha_image_selector = captcha_image_selector
        self.submit_selector = submit_selector

    def run(self):
        try:
            asyncio.run(self._async_run())
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")

    async def _async_run(self):
        from playwright.async_api import TimeoutError as PlaywrightTimeout  # local import
        automation = None
        try:
            browser_type_enum = BrowserType[self.browser_type.upper()]
            automation = BrowserAutomation(
                browser_type=browser_type_enum,
                headless=self.headless,
                screenshot_dir=str(Config.SCREENSHOTS_DIR),
            )
            await automation.start()

            results: List[Dict] = []

            if self.captcha_selector:
                self.probe_log.emit("▶ 场景1: 错误账号密码 + 故意错误验证码...")
                r1 = await self._probe_scenario(
                    automation, PlaywrightTimeout,
                    "wrong_creds_wrong_captcha", use_wrong_captcha=True,
                )
                results.append(r1)
                await asyncio.sleep(1.5)

                self.probe_log.emit("▶ 场景2: 错误账号密码 + 正确验证码...")
                r2 = await self._probe_scenario(
                    automation, PlaywrightTimeout,
                    "wrong_creds_correct_captcha", use_wrong_captcha=False,
                )
                results.append(r2)
            else:
                self.probe_log.emit("▶ 场景: 错误账号密码（无验证码）...")
                r1 = await self._probe_scenario(
                    automation, PlaywrightTimeout,
                    "wrong_creds_no_captcha", use_wrong_captcha=False,
                )
                results.append(r1)

            self.probe_done.emit(results)

        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
        finally:
            if automation:
                await automation.stop()

    async def _probe_scenario(
        self, automation, PlaywrightTimeout, scenario_name: str, use_wrong_captcha: bool
    ) -> Dict:
        import time as _time
        MAX_RETRIES = 3
        for attempt in range(MAX_RETRIES):
            page = None
            try:
                page = await automation.context.new_page()
                page.set_default_timeout(automation.timeout)

                # Wrap selectors so Playwright targets only visible elements,
                # avoiding hidden duplicates (e.g. input[type='text'][name*='account']
                # may match both a visible and a hidden input).
                def _vis(sel: str) -> str:
                    return f"{sel}:visible"

                self.probe_log.emit(f"  [步骤1] 导航到页面...")
                await page.goto(self.url, wait_until="commit", timeout=automation.timeout)
                for state in ("domcontentloaded", "load"):
                    try:
                        await page.wait_for_load_state(state, timeout=5000)
                    except PlaywrightTimeout:
                        self.probe_log.emit(f"  [步骤1] wait_for_load_state({state!r}) 超时，继续")
                        break

                self.probe_log.emit(f"  [步骤2] 等待用户名框可见...")
                if self.username_selector:
                    try:
                        await page.wait_for_selector(
                            _vis(self.username_selector), timeout=10000
                        )
                    except PlaywrightTimeout:
                        self.probe_log.emit("  [步骤2] 用户名框等待超时，尝试继续...")
                    await page.locator(_vis(self.username_selector)).first.fill(
                        self._PROBE_USERNAME, timeout=10000
                    )
                    await page.wait_for_timeout(200)
                self.probe_log.emit(f"  [步骤3] 等待密码框可见...")
                if self.password_selector:
                    try:
                        await page.wait_for_selector(
                            _vis(self.password_selector), timeout=10000
                        )
                    except PlaywrightTimeout:
                        self.probe_log.emit("  [步骤3] 密码框等待超时，尝试继续...")
                    await page.locator(_vis(self.password_selector)).first.fill(
                        self._PROBE_PASSWORD, timeout=10000
                    )
                    await page.wait_for_timeout(200)

                captcha_status = "N/A"
                if self.captcha_selector:
                    if use_wrong_captcha:
                        self.probe_log.emit(f"  [步骤4] 填写错误验证码...")
                        try:
                            await page.wait_for_selector(
                                _vis(self.captcha_selector), timeout=10000
                            )
                        except PlaywrightTimeout:
                            self.probe_log.emit("  [步骤4] 验证码框等待超时，尝试继续...")
                        await page.locator(_vis(self.captcha_selector)).first.fill(
                            self._WRONG_CAPTCHA, timeout=10000
                        )
                        captcha_status = f"故意错误 ({self._WRONG_CAPTCHA})"
                        await page.wait_for_timeout(200)
                    else:
                        self.probe_log.emit(f"  [步骤4] 识别验证码...")
                        captcha_text = await automation.solve_captcha(
                            page, self.captcha_image_selector or None
                        )
                        if not captcha_text:
                            await page.close()
                            page = None
                            if attempt < MAX_RETRIES - 1:
                                self.probe_log.emit(
                                    f"  验证码识别失败，重试 ({attempt + 2}/{MAX_RETRIES})..."
                                )
                                await asyncio.sleep(1.5)
                                continue
                            return {
                                "scenario": scenario_name,
                                "captcha": "识别失败",
                                "url": self.url,
                                "error_messages": ["验证码识别失败，无法完成场景探测"],
                                "network_records": [],
                                "screenshot": "",
                                "status": "captcha_failed",
                            }
                        await page.locator(_vis(self.captcha_selector)).first.fill(
                            captcha_text, timeout=10000
                        )
                        captcha_status = f"已识别 ({captcha_text})"
                        await page.wait_for_timeout(200)

                # ── Network capture: register handler before submit ──────────
                network_records: List[Dict] = []

                async def _on_response(response) -> None:
                    try:
                        # Skip static assets that may still be in-flight from the initial page load
                        resource_type = response.request.resource_type
                        if resource_type in ("script", "stylesheet", "image", "font", "media", "other"):
                            return

                        url      = response.url
                        method   = response.request.method
                        status   = response.status
                        ct       = response.headers.get("content-type", "")
                        location = response.headers.get("location", "")

                        post_data: Optional[str] = None
                        try:
                            raw_post = response.request.post_data
                            if raw_post:
                                post_data = raw_post[:600] + ("…" if len(raw_post) > 600 else "")
                        except Exception:
                            pass

                        body_text: Optional[str] = None
                        if any(t in ct for t in ["json", "text/plain", "text/html", "xml"]):
                            try:
                                raw_body = await response.text()
                                body_text = raw_body[:1200] + ("…" if len(raw_body) > 1200 else "")
                            except Exception:
                                pass

                        network_records.append({
                            "url": url,
                            "method": method,
                            "status": status,
                            "content_type": ct,
                            "location": location,
                            "post_data": post_data,
                            "body": body_text,
                        })
                    except Exception:
                        pass

                page.on("response", _on_response)
                # ─────────────────────────────────────────────────────────────

                self.probe_log.emit(f"  [步骤5] 提交表单...")
                if self.submit_selector:
                    await page.click(self.submit_selector)
                elif self.password_selector:
                    await page.press(self.password_selector, "Enter")

                await page.wait_for_timeout(3000)
                self.probe_log.emit(f"  [步骤6] 收集页面信息...")

                page.remove_listener("response", _on_response)

                current_url = page.url
                error_messages: List[str] = []
                seen: set = set()
                for sel in [
                    ".error", ".alert-error", ".alert-danger", ".alert",
                    "#error", "[class*='error']", "[class*='alert']",
                    "[class*='tip']", "[class*='msg']", "[class*='message']",
                    "[class*='warn']",
                ]:
                    try:
                        for el in await page.query_selector_all(sel):
                            try:
                                txt = (await el.inner_text()).strip()
                                if txt and txt not in seen and len(txt) < 300:
                                    seen.add(txt)
                                    error_messages.append(txt)
                            except Exception:
                                pass
                    except Exception:
                        pass

                screenshot_path = ""
                try:
                    screenshot_path = str(
                        Config.SCREENSHOTS_DIR / f"probe_{scenario_name}_{int(_time.time())}.png"
                    )
                    await page.screenshot(path=screenshot_path)
                except Exception:
                    screenshot_path = ""

                await page.close()
                page = None
                return {
                    "scenario": scenario_name,
                    "captcha": captcha_status,
                    "url": current_url,
                    "error_messages": error_messages[:10],
                    "network_records": network_records,
                    "screenshot": screenshot_path,
                    "status": "ok",
                }

            except PlaywrightTimeout as e:
                self.probe_log.emit(f"  超时详情: {str(e)[:120]}")
                if attempt < MAX_RETRIES - 1:
                    self.probe_log.emit(f"  超时，重试 ({attempt + 2}/{MAX_RETRIES})...")
                    await asyncio.sleep(2)
                    continue
                return {
                    "scenario": scenario_name,
                    "captcha": "超时",
                    "url": self.url,
                    "error_messages": ["请求超时"],
                    "network_records": [],
                    "screenshot": "",
                    "status": "timeout",
                }
            except Exception as e:
                return {
                    "scenario": scenario_name,
                    "captcha": "错误",
                    "url": self.url,
                    "error_messages": [str(e)[:150]],
                    "network_records": [],
                    "screenshot": "",
                    "status": "error",
                }
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:
                        pass

        return {"scenario": scenario_name, "status": "unknown", "error_messages": [], "network_records": [], "url": self.url}


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()

        Config.ensure_directories()
        log_level = getattr(logging, Config.LOG_LEVEL, logging.DEBUG)
        self.logger = init_logger(str(Config.LOGS_DIR), log_level)

        self.password_loader = PasswordLoader()
        self.credentials: List[Credential] = []
        self.worker: Optional[LoginWorker] = None
        self.check_worker: Optional[CheckFormWorker] = None
        self.results: List[LoginResult] = []

        self._guided_picker_worker: Optional[GuidedPickerWorker] = None
        self._response_probe_worker = None        # ResponseProbeWorker (defined after MainWindow)
        self._field_statuses: Dict[str, str] = {} # field_key -> "green"/"red"/"yellow"/"none"

        self.init_ui()
        self.logger.info("Application started")

    def init_ui(self):
        """Initialize user interface"""
        self.setWindowTitle(Config.WINDOW_TITLE)
        self.setGeometry(100, 100, Config.WINDOW_WIDTH, Config.WINDOW_HEIGHT)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Create tabs
        tabs = QTabWidget()
        tabs.addTab(self._create_config_tab(), "Configuration")
        tabs.addTab(self._create_results_tab(), "Results")

        main_layout.addWidget(tabs)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Status bar
        self.statusBar().showMessage("Ready")

    def _create_config_tab(self) -> QWidget:
        """Create configuration tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Target URL Group
        url_group = QGroupBox("Target Login Page URL")
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com/login")
        self.url_input.returnPressed.connect(self.check_form)  # Enter in URL field = Check (no credentials)
        url_layout.addWidget(self.url_input)
        url_group.setLayout(url_layout)
        layout.addWidget(url_group)

        # Credentials File Group
        file_group = QGroupBox("Credentials File (Excel / CSV)")
        file_layout = QVBoxLayout()

        file_select_layout = QHBoxLayout()
        file_select_layout.addWidget(QLabel("Excel / CSV File:"))
        self.file_path_input = QLineEdit()
        file_select_layout.addWidget(self.file_path_input)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse_file)
        file_select_layout.addWidget(self.browse_button)
        file_layout.addLayout(file_select_layout)

        # Excel column configuration
        column_layout = QHBoxLayout()
        column_layout.addWidget(QLabel("Username Column:"))
        self.username_column_spin = QSpinBox()
        self.username_column_spin.setMinimum(0)
        self.username_column_spin.setValue(Config.DEFAULT_USERNAME_COLUMN)
        column_layout.addWidget(self.username_column_spin)

        column_layout.addWidget(QLabel("Password Column:"))
        self.password_column_spin = QSpinBox()
        self.password_column_spin.setMinimum(0)
        self.password_column_spin.setValue(Config.DEFAULT_PASSWORD_COLUMN)
        column_layout.addWidget(self.password_column_spin)

        self.skip_header_check = QCheckBox("Skip Header Row")
        self.skip_header_check.setChecked(Config.DEFAULT_SKIP_HEADER)
        column_layout.addWidget(self.skip_header_check)

        self.load_button = QPushButton("Load Credentials")
        self.load_button.clicked.connect(self.load_credentials)
        column_layout.addWidget(self.load_button)

        file_layout.addLayout(column_layout)

        self.credentials_label = QLabel("Credentials not loaded")
        file_layout.addWidget(self.credentials_label)

        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Browser Settings Group
        browser_group = QGroupBox("Browser Settings")
        browser_layout = QHBoxLayout()

        browser_layout.addWidget(QLabel("Browser:"))
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["chromium", "firefox", "webkit"])
        browser_layout.addWidget(self.browser_combo)

        self.headless_check = QCheckBox("Headless Mode")
        self.headless_check.setChecked(Config.DEFAULT_HEADLESS)
        browser_layout.addWidget(self.headless_check)

        browser_layout.addWidget(QLabel("Delay (ms):"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setMinimum(0)
        self.delay_spin.setMaximum(10000)
        self.delay_spin.setSingleStep(100)
        self.delay_spin.setValue(Config.ATTEMPT_DELAY_MS)
        browser_layout.addWidget(self.delay_spin)

        browser_layout.addWidget(QLabel("Delay jitter (%):"))
        self.delay_jitter_spin = QSpinBox()
        self.delay_jitter_spin.setMinimum(0)
        self.delay_jitter_spin.setMaximum(100)
        self.delay_jitter_spin.setSuffix("%")
        self.delay_jitter_spin.setValue(int(Config.ATTEMPT_DELAY_JITTER * 100))
        self.delay_jitter_spin.setToolTip("Random jitter applied to delay (e.g. 30% → delay × 0.7~1.3)")
        browser_layout.addWidget(self.delay_jitter_spin)

        # Session isolation
        browser_layout.addWidget(QLabel("Session Isolation:"))
        self.session_isolation_check = QCheckBox("Enable")
        self.session_isolation_check.setChecked(Config.DEFAULT_SESSION_ISOLATION_ENABLED)
        self.session_isolation_check.setToolTip(
            "Enable session isolation between credential attempts.\n"
            "When disabled, the browser/context is fully reused across all attempts."
        )
        self.session_isolation_check.toggled.connect(self._on_session_isolation_toggled)
        browser_layout.addWidget(self.session_isolation_check)

        self.session_isolation_combo = QComboBox()
        self.session_isolation_combo.addItem("最低 – 仅重填表单（不重置 Context/Page）", "none")
        self.session_isolation_combo.addItem("中等 – 重置会话上下文（清除 Cookie 等）", "medium")
        self.session_isolation_combo.addItem("最强 – 每次凭据尝试使用全新浏览器实例", "high")
        _default_level_index = {"none": 0, "medium": 1, "high": 2}.get(
            Config.DEFAULT_SESSION_ISOLATION_LEVEL, 0
        )
        self.session_isolation_combo.setCurrentIndex(_default_level_index)
        self.session_isolation_combo.setEnabled(Config.DEFAULT_SESSION_ISOLATION_ENABLED)
        self.session_isolation_combo.setToolTip(
            "最低: 不关闭浏览器/Context/Page，仅重新填写表单字段并提交。\n"
            "中等: 每次尝试前清除 Cookie 和会话数据，但保持浏览器进程运行。\n"
            "最强: 为每一条凭据单独启动并销毁一个全新的浏览器实例。"
        )
        browser_layout.addWidget(self.session_isolation_combo)

        browser_group.setLayout(browser_layout)
        layout.addWidget(browser_group)

        # Form Selectors Group (Optional)
        selector_group = QGroupBox("Form Selectors (Optional - Leave Blank for Auto Detection)")
        selector_layout = QVBoxLayout()

        # Username selector
        username_selector_layout = QHBoxLayout()
        username_selector_layout.addWidget(QLabel("Username Field:"))
        self.username_selector_input = QLineEdit()
        self.username_selector_input.setPlaceholderText("CSS selector, e.g., input[name='username']")
        username_selector_layout.addWidget(self.username_selector_input)
        selector_layout.addLayout(username_selector_layout)

        # Password selector
        password_selector_layout = QHBoxLayout()
        password_selector_layout.addWidget(QLabel("Password Field:"))
        self.password_selector_input = QLineEdit()
        self.password_selector_input.setPlaceholderText("CSS selector, e.g., input[type='password']")
        password_selector_layout.addWidget(self.password_selector_input)
        selector_layout.addLayout(password_selector_layout)

        # Enable captcha recognition toggle (placed before captcha selectors so state is readable)
        captcha_enable_layout = QHBoxLayout()
        self.enable_captcha_check = QCheckBox("Enable captcha recognition and auto-fill")
        self.enable_captcha_check.setChecked(True)
        self.enable_captcha_check.setToolTip(
            "When checked, the captcha image will be solved automatically and filled into the captcha field.\n"
            "Uncheck to skip captcha handling entirely (captcha selectors below will be ignored)."
        )
        self.enable_captcha_check.toggled.connect(self._on_captcha_enable_toggled)
        captcha_enable_layout.addWidget(self.enable_captcha_check)
        captcha_enable_layout.addStretch()
        selector_layout.addLayout(captcha_enable_layout)

        # Captcha selector
        captcha_selector_layout = QHBoxLayout()
        captcha_selector_layout.addWidget(QLabel("Captcha Field:"))
        self.captcha_selector_input = QLineEdit()
        self.captcha_selector_input.setPlaceholderText("CSS selector, e.g., input[name='captcha']")
        captcha_selector_layout.addWidget(self.captcha_selector_input)
        selector_layout.addLayout(captcha_selector_layout)

        # Captcha image selector
        captcha_image_selector_layout = QHBoxLayout()
        captcha_image_selector_layout.addWidget(QLabel("Captcha Image:"))
        self.captcha_image_selector_input = QLineEdit()
        self.captcha_image_selector_input.setPlaceholderText("CSS selector, e.g., img.captcha-img")
        captcha_image_selector_layout.addWidget(self.captcha_image_selector_input)
        selector_layout.addLayout(captcha_image_selector_layout)

        # Submit selector
        submit_selector_layout = QHBoxLayout()
        submit_selector_layout.addWidget(QLabel("Submit Button:"))
        self.submit_selector_input = QLineEdit()
        self.submit_selector_input.setPlaceholderText("CSS selector, e.g., button[type='submit']")
        submit_selector_layout.addWidget(self.submit_selector_input)
        selector_layout.addLayout(submit_selector_layout)

        # Success indicator
        success_indicator_layout = QHBoxLayout()
        success_indicator_layout.addWidget(QLabel("Success Indicator:"))
        self.success_indicator_input = QLineEdit()
        self.success_indicator_input.setPlaceholderText("CSS selector or URL, e.g., #dashboard or /dashboard")
        success_indicator_layout.addWidget(self.success_indicator_input)
        selector_layout.addLayout(success_indicator_layout)

        # Single guided "Pick All" button — opens the browser once and walks through all fields
        pick_all_layout = QHBoxLayout()
        self._pick_all_btn = QPushButton("🖱 Pick All Elements Interactively")
        self._pick_all_btn.setToolTip(
            "Open a browser window and guide you through selecting each form element in order.\n"
            "Captcha fields are included only when 'Enable captcha recognition' is checked above."
        )
        self._pick_all_btn.clicked.connect(lambda: self._start_guided_picker())
        pick_all_layout.addWidget(self._pick_all_btn)

        self._reset_all_btn = QPushButton("↺ Reset All")
        self._reset_all_btn.setToolTip("Clear all selector inputs and reset background colours.")
        self._reset_all_btn.clicked.connect(self._reset_all_selectors)
        pick_all_layout.addWidget(self._reset_all_btn)

        selector_layout.addLayout(pick_all_layout)

        selector_group.setLayout(selector_layout)
        layout.addWidget(selector_group)

        # Control Buttons
        # Row 1: Check + its companion checkbox
        check_layout = QHBoxLayout()
        self.check_button = QPushButton("Check")
        self.check_button.clicked.connect(self.check_form)
        self.check_button.setStyleSheet("QPushButton { background-color: #2196F3; color: white; padding: 10px; font-weight: bold; }")
        self.check_button.setToolTip("Only URL needed (no credentials). Open browser, detect login form controls, and fill CSS selectors above.")
        check_layout.addWidget(self.check_button, 1)

        self.auto_response_check = QCheckBox("Auto-detect response patterns")
        self.auto_response_check.setChecked(True)
        self.auto_response_check.setToolTip(
            "After all fields turn green, automatically send two probe requests:\n"
            "  Scenario 1: wrong credentials + deliberately wrong captcha\n"
            "  Scenario 2: wrong credentials + correctly solved captcha\n"
            "Compares server responses to distinguish captcha errors from credential errors."
        )
        check_layout.addWidget(self.auto_response_check, 1)
        layout.addLayout(check_layout)

        # Row 2: Start / Stop
        control_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Verification")
        self.start_button.clicked.connect(self.start_verification)
        self.start_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 10px; font-weight: bold; }")
        control_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Verification")
        self.stop_button.clicked.connect(self.stop_verification)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("QPushButton { background-color: #f44336; color: white; padding: 10px; font-weight: bold; }")
        control_layout.addWidget(self.stop_button)

        layout.addLayout(control_layout)

        # Log display
        log_group = QGroupBox("Logs")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        return widget

    def _create_results_tab(self) -> QWidget:
        """Create results tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Statistics
        stats_group = QGroupBox("Statistics")
        stats_layout = QHBoxLayout()

        self.total_label = QLabel("Total: 0")
        stats_layout.addWidget(self.total_label)

        self.success_label = QLabel("Success: 0")
        self.success_label.setStyleSheet("QLabel { color: green; font-weight: bold; }")
        stats_layout.addWidget(self.success_label)

        self.failed_label = QLabel("Failed: 0")
        self.failed_label.setStyleSheet("QLabel { color: red; font-weight: bold; }")
        stats_layout.addWidget(self.failed_label)

        self.error_label = QLabel("Error: 0")
        self.error_label.setStyleSheet("QLabel { color: orange; font-weight: bold; }")
        stats_layout.addWidget(self.error_label)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(["Username", "Status", "Message", "URL", "Screenshot"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.results_table)

        # Export button
        export_button = QPushButton("Export Results")
        export_button.clicked.connect(self.export_results)
        layout.addWidget(export_button)

        return widget

    # ─── Field colour helpers ────────────────────────────────────────────────

    _FIELD_COLORS = {
        "green":  "QLineEdit { background-color: #c8e6c9; }",
        "red":    "QLineEdit { background-color: #ffcdd2; }",
        "yellow": "QLineEdit { background-color: #fff9c4; }",
        "none":   "",
    }

    def _set_field_color(self, field_key: str, status: str):
        """Set the background colour of a selector input widget."""
        inputs_map = self._field_inputs_map()
        if field_key in inputs_map:
            inputs_map[field_key].setStyleSheet(self._FIELD_COLORS.get(status, ""))
            self._field_statuses[field_key] = status

    def _reset_all_selectors(self):
        """Clear all selector inputs and reset their background colours."""
        for key, widget in self._field_inputs_map().items():
            widget.clear()
            widget.setStyleSheet("")
        self._field_statuses.clear()
        self.log("All selectors reset.")
        self.statusBar().showMessage("All selectors cleared.")

    def _check_all_required_green(self) -> bool:
        """Return True when username, password, submit (and captcha if enabled) are all green."""
        required = ["username", "password", "submit"]
        if self.enable_captcha_check.isChecked():
            required.append("captcha")
        inputs_map = self._field_inputs_map()
        for key in required:
            if self._field_statuses.get(key) != "green":
                return False
            widget = inputs_map.get(key)
            if widget is None or not widget.text().strip():
                return False
        return True

    # ─── Response probe ──────────────────────────────────────────────────────

    def _start_response_probe(self):
        """Start the ResponseProbeWorker to distinguish server responses."""
        if self._response_probe_worker is not None:
            self.log("响应包探测已在进行中，跳过...")
            return

        url = self.url_input.text().strip()
        if not url:
            return

        selectors = {k: w.text().strip() for k, w in self._field_inputs_map().items()}

        self._response_probe_worker = ResponseProbeWorker(
            url=url,
            browser_type=self.browser_combo.currentText(),
            headless=self.headless_check.isChecked(),
            username_selector=selectors.get("username", ""),
            password_selector=selectors.get("password", ""),
            captcha_selector=selectors.get("captcha", ""),
            captcha_image_selector=selectors.get("captcha_image", ""),
            submit_selector=selectors.get("submit", ""),
        )
        self._response_probe_worker.probe_log.connect(self.log)
        self._response_probe_worker.probe_done.connect(self._on_probe_done)
        self._response_probe_worker.error.connect(self._on_probe_error)
        self._response_probe_worker.finished.connect(self._on_probe_finished)
        self._response_probe_worker.start()

        self.check_button.setEnabled(False)
        self.statusBar().showMessage("响应包探测进行中...")

    def _on_probe_done(self, results: list):
        """Display response probe comparison in the log, including network-level diff."""
        import json
        import difflib
        from urllib.parse import urlparse

        self.log("━" * 40)
        self.log("响应包探测完成，结果如下：")

        scenario_labels = {
            "wrong_creds_wrong_captcha":   "场景1: 错误账号密码 + 故意错误验证码",
            "wrong_creds_correct_captcha": "场景2: 错误账号密码 + 正确验证码",
            "wrong_creds_no_captcha":      "场景: 错误账号密码（无验证码）",
        }

        for r in results:
            label = scenario_labels.get(r.get("scenario", ""), r.get("scenario", "未知场景"))
            self.log(f"\n▶ {label}")
            self.log(f"  验证码状态 : {r.get('captcha', 'N/A')}")
            self.log(f"  最终 URL   : {r.get('url', 'N/A')}")
            errs = r.get("error_messages", [])
            if errs:
                self.log("  页面错误信息 :")
                for e in errs:
                    self.log(f"    • {e[:120]}")
            else:
                self.log("  页面错误信息 : (未检测到)")

            nets = r.get("network_records", [])
            self.log(f"  捕获请求数 : {len(nets)}")
            for rec in nets:
                status  = rec.get("status", "?")
                method  = rec.get("method", "?")
                url     = rec.get("url", "")
                loc     = rec.get("location", "")
                loc_str = f"  → {loc}" if loc else ""
                self.log(f"    [{method}] {status}{loc_str}  {url[:100]}")

            sc = r.get("screenshot", "")
            if sc:
                self.log(f"  截图        : {sc}")

        # ── Network diff (only when two scenarios are available) ──────────
        if len(results) == 2:
            r1, r2 = results[0], results[1]

            # --- Classic page-text diff ---
            e1 = set(r1.get("error_messages", []))
            e2 = set(r2.get("error_messages", []))
            self.log("\n📊 场景对比分析:")

            if e1 != e2:
                diff1 = e1 - e2
                diff2 = e2 - e1
                if diff1:
                    self.log(f"  场景1 独有页面错误: {' | '.join(list(diff1)[:3])}")
                if diff2:
                    self.log(f"  场景2 独有页面错误: {' | '.join(list(diff2)[:3])}")
                self.log("  ✅ 两种场景页面响应不同，可区分验证码错误与密码错误")
            else:
                self.log("  ⚠ 两种场景页面错误信息相同")

            if r1.get("url") != r2.get("url"):
                self.log(f"  URL 差异: 场景1 → {r1.get('url')} | 场景2 → {r2.get('url')}")

            # --- Network-level diff ---
            nets1: List[Dict] = r1.get("network_records", [])
            nets2: List[Dict] = r2.get("network_records", [])

            def _key(rec: Dict) -> str:
                parsed = urlparse(rec.get("url", ""))
                return f"{rec.get('method','?')} {parsed.path or rec.get('url','')}"

            idx1 = {_key(rec): rec for rec in nets1}
            idx2 = {_key(rec): rec for rec in nets2}

            all_keys = sorted(set(idx1) | set(idx2))
            if not all_keys:
                self.log("\n  (无捕获到的网络请求，无法进行网络层 diff)")
            else:
                self.log("\n🔎 网络请求 Diff:")
                has_diff = False
                for k in all_keys:
                    rec1 = idx1.get(k)
                    rec2 = idx2.get(k)

                    if rec1 is None:
                        self.log(f"  ＋[仅场景2] {k}")
                        has_diff = True
                        continue
                    if rec2 is None:
                        self.log(f"  －[仅场景1] {k}")
                        has_diff = True
                        continue

                    diffs_for_key = []

                    # Status code
                    if rec1.get("status") != rec2.get("status"):
                        diffs_for_key.append(
                            f"状态码: {rec1.get('status')} → {rec2.get('status')}"
                        )

                    # Location header (redirect)
                    if rec1.get("location") != rec2.get("location"):
                        diffs_for_key.append(
                            f"Location: {rec1.get('location') or '(无)'} → {rec2.get('location') or '(无)'}"
                        )

                    # Response body diff
                    body1 = rec1.get("body") or ""
                    body2 = rec2.get("body") or ""
                    if body1 != body2:
                        ct = rec1.get("content_type", "")
                        if "json" in ct:
                            # JSON key-level diff
                            try:
                                j1 = json.loads(body1.rstrip("…"))
                                j2 = json.loads(body2.rstrip("…"))
                                changed_keys = [
                                    f'"{kk}": {j1.get(kk)!r} → {j2.get(kk)!r}'
                                    for kk in sorted(set(j1) | set(j2))
                                    if j1.get(kk) != j2.get(kk)
                                ]
                                if changed_keys:
                                    diffs_for_key.append(
                                        "JSON diff: " + " | ".join(changed_keys[:5])
                                    )
                            except Exception:
                                # Fallback: unified diff on lines
                                ud = list(difflib.unified_diff(
                                    body1.splitlines(), body2.splitlines(),
                                    lineterm="", n=1
                                ))[:12]
                                if ud:
                                    diffs_for_key.append("响应体变化 (unified diff):\n      " + "\n      ".join(ud))
                        else:
                            ud = list(difflib.unified_diff(
                                body1.splitlines(), body2.splitlines(),
                                lineterm="", n=1
                            ))[:12]
                            if ud:
                                diffs_for_key.append("响应体变化:\n      " + "\n      ".join(ud))

                    # Post-data diff (request body)
                    pd1 = rec1.get("post_data") or ""
                    pd2 = rec2.get("post_data") or ""
                    if pd1 != pd2:
                        diffs_for_key.append(
                            f"请求体变化: {pd1[:80] or '(空)'} → {pd2[:80] or '(空)'}"
                        )

                    if diffs_for_key:
                        self.log(f"  ≠ {k}")
                        for d in diffs_for_key:
                            for line in d.splitlines():
                                self.log(f"      {line}")
                        has_diff = True

                if not has_diff:
                    self.log("  (两场景网络请求/响应完全相同，服务端可能不区分)")
                else:
                    self.log("  ✅ 网络层存在差异，可用于自动区分响应类型")

        self.log("━" * 40)
        self.statusBar().showMessage("响应包探测完成")

    def _on_probe_error(self, error_msg: str):
        self.log(f"响应包探测错误: {error_msg}")
        self.statusBar().showMessage("响应包探测失败")

    def _on_probe_finished(self):
        self._response_probe_worker = None
        self.check_button.setEnabled(True)

    def browse_file(self):
        """Browse for Data Table file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Data Table File",
            "",
            "Data Table File (*.xlsx *.xls *.csv);"
        )

        if file_path:
            self.file_path_input.setText(file_path)

    def load_credentials(self):
        """Load credentials from Data Table file"""
        file_path = self.file_path_input.text()

        if not file_path:
            QMessageBox.warning(self, "Error", "Please select a Data Table file")
            return

        try:
            if file_path.lower().endswith(('.xlsx', '.xls')):
                self.credentials = self.password_loader.load_from_excel(
                    file_path=file_path,
                    username_column=self.username_column_spin.value(),
                    password_column=self.password_column_spin.value(),
                    skip_header=self.skip_header_check.isChecked()
                )
            elif file_path.lower().endswith('.csv'):
                self.credentials = self.password_loader.load_from_csv(
                    file_path=file_path,
                    username_column=self.username_column_spin.value(),
                    password_column=self.password_column_spin.value(),
                    skip_header=self.skip_header_check.isChecked()
                )
            else:
                raise ValueError("Unsupported file format. Please select an Excel or CSV file.")

            count = len(self.credentials)
            self.credentials_label.setText(f"Loaded {count} credentials")
            self.log(f"Successfully loaded {count} credentials")

            if count == 0:
                QMessageBox.warning(self, "Warning", "No valid credentials found")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load credentials: {str(e)}")
            self.log(f"Error: {str(e)}")

    def start_verification(self):
        """Start verification process (requires credentials loaded)."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter the target URL")
            return

        if not self.credentials:
            QMessageBox.warning(
                self,
                "Start Verification",
                "Please load credentials first.\n\nTip: Use \"Check (URL only)\" to detect form fields without loading credentials.",
            )
            return

        # Get selectors
        username_selector = self.username_selector_input.text().strip() or None
        password_selector = self.password_selector_input.text().strip() or None
        captcha_selector = self.captcha_selector_input.text().strip() or None
        captcha_image_selector = self.captcha_image_selector_input.text().strip() or None
        submit_selector = self.submit_selector_input.text().strip() or None
        success_indicator = self.success_indicator_input.text().strip() or None
        enable_captcha = self.enable_captcha_check.isChecked()

        # Determine session isolation level
        if self.session_isolation_check.isChecked():
            session_isolation = self.session_isolation_combo.currentData()
        else:
            session_isolation = "none"

        # Clear previous results
        self.results.clear()
        self.results_table.setRowCount(0)
        self.update_statistics()

        # Start worker thread
        self.worker = LoginWorker(
            url=url,
            credentials=self.credentials,
            browser_type=self.browser_combo.currentText(),
            headless=self.headless_check.isChecked(),
            username_selector=username_selector,
            password_selector=password_selector,
            captcha_selector=captcha_selector,
            captcha_image_selector=captcha_image_selector,
            submit_selector=submit_selector,
            success_indicator=success_indicator,
            delay=self.delay_spin.value(),
            delay_jitter=self.delay_jitter_spin.value() / 100.0,
            enable_captcha=enable_captcha,
            session_isolation=session_isolation,
        )

        self.worker.progress.connect(self.update_progress)
        self.worker.result.connect(self.add_result)
        self.worker.finished.connect(self.verification_finished)
        self.worker.error.connect(self.handle_error)

        self.worker.start()

        # Update UI
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(self.credentials))
        self.progress_bar.setValue(0)

        self.log(f"Starting verification of {len(self.credentials)} credentials...")

    def stop_verification(self):
        """Stop verification process"""
        if self.worker:
            self.worker.stop()
            self.log("Stopping verification...")

    def check_form(self):
        """Open browser, detect login form elements, and fill selector inputs. Requires only URL (no credentials)."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter the target URL (no credentials required for Check).")
            return

        self.check_button.setEnabled(False)
        self.statusBar().showMessage("Detecting login form...")
        self.log("Check: Opening browser and detecting form elements...")

        # Snapshot current selector values so the worker can validate pre-filled selectors
        existing_selectors = {
            key: widget.text().strip()
            for key, widget in self._field_inputs_map().items()
        }

        self.check_worker = CheckFormWorker(
            url=url,
            browser_type=self.browser_combo.currentText(),
            headless=self.headless_check.isChecked(),
            existing_selectors=existing_selectors,
        )
        self.check_worker.detected.connect(self._on_check_detected)
        self.check_worker.error.connect(self._on_check_error)
        self.check_worker.finished.connect(self._on_check_finished)
        self.check_worker.start()

    def _on_check_detected(self, data: Dict[str, Any]):
        """Apply colour feedback to each selector field and fill auto-detected values."""
        detected: Dict[str, Any] = data.get("detected", {})
        validation: Dict[str, bool] = data.get("validation", {})

        inputs_map = self._field_inputs_map()

        for field_key, input_widget in inputs_map.items():
            existing_val = input_widget.text().strip()
            detected_sel = detected.get(field_key) or ""

            if existing_val:
                # Field already has a value — validate it against the live page
                if validation.get(field_key, False):
                    self._set_field_color(field_key, "green")
                else:
                    self._set_field_color(field_key, "red")
            else:
                # Field is empty
                if detected_sel:
                    input_widget.setText(detected_sel)
                    self._set_field_color(field_key, "green")
                else:
                    self._set_field_color(field_key, "yellow")

        # Log summary
        self.log("Check: 字段识别结果：")
        for field_key in inputs_map:
            val = inputs_map[field_key].text().strip() or "(none)"
            status = self._field_statuses.get(field_key, "none")
            icon = {"green": "✅", "red": "❌", "yellow": "⚠", "none": "—"}.get(status, "")
            self.log(f"  {icon} {field_key:16s}: {val}")

        self.statusBar().showMessage("Detection complete.")

        # Check if we can auto-start response probe
        if self._check_all_required_green():
            if self.auto_response_check.isChecked():
                self.log("━" * 40)
                self.log("所有必填字段已验证（全绿），自动启动响应包探测...")
                self._start_response_probe()
        else:
            # Prompt guided picker for fields that are red or yellow
            missing = [
                k for k in ["username", "password", "submit"]
                if self._field_statuses.get(k) in ("red", "yellow")
            ]
            if missing:
                field_labels = {
                    "username": "Username Field",
                    "password": "Password Field",
                    "submit": "Submit Button",
                }
                missing_labels = ", ".join(field_labels[k] for k in missing)
                reply = QMessageBox.question(
                    self,
                    "Auto-Detection Incomplete",
                    f"Could not auto-detect the following required elements:\n  {missing_labels}\n\n"
                    "Launch the interactive element picker to select them manually?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    self._start_guided_picker(missing)

    def _on_check_error(self, error_msg: str):
        """Handle check worker error."""
        self.log(f"Check error: {error_msg}")
        QMessageBox.critical(self, "Check Failed", error_msg)
        self.statusBar().showMessage("Check failed")

    def _on_check_finished(self):
        """Re-enable Check button when worker finishes (unless response probe is still running)."""
        if self._response_probe_worker is None:
            self.check_button.setEnabled(True)
        if self.check_worker and self.check_worker.isFinished():
            self.check_worker = None

    def _on_captcha_enable_toggled(self, enabled: bool):
        """Enable or disable captcha selector inputs based on the checkbox state."""
        self.captcha_selector_input.setEnabled(enabled)
        self.captcha_image_selector_input.setEnabled(enabled)

    def _on_session_isolation_toggled(self, enabled: bool):
        """Enable or disable the session isolation strength combo based on the checkbox."""
        self.session_isolation_combo.setEnabled(enabled)

    def _field_inputs_map(self) -> Dict[str, QLineEdit]:
        return {
            "username": self.username_selector_input,
            "password": self.password_selector_input,
            "captcha": self.captcha_selector_input,
            "captcha_image": self.captcha_image_selector_input,
            "submit": self.submit_selector_input,
        }

    def _start_guided_picker(self, field_keys: Optional[List[str]] = None):
        """Open the browser once and guide the user through selecting each field in order."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter the target URL first.")
            return

        if self._guided_picker_worker and self._guided_picker_worker.isRunning():
            QMessageBox.information(
                self, "Picker Active",
                "A guided picker is already running. Please complete or cancel it first."
            )
            return

        field_labels: Dict[str, str] = {
            "username": "Username Field",
            "password": "Password Field",
            "captcha": "Captcha Field",
            "captcha_image": "Captcha Image",
            "submit": "Submit Button",
        }

        if field_keys is None:
            # Build the full ordered list, respecting the captcha toggle
            field_keys = ["username", "password"]
            if self.enable_captcha_check.isChecked():
                field_keys += ["captcha", "captcha_image"]
            field_keys.append("submit")

        fields = [(k, field_labels[k]) for k in field_keys if k in field_labels]
        if not fields:
            return

        self._guided_picker_worker = GuidedPickerWorker(
            url=url,
            browser_type=self.browser_combo.currentText(),
            fields=fields,
        )
        self._guided_picker_worker.field_selected.connect(self._on_guided_field_selected)
        self._guided_picker_worker.field_skipped.connect(self._on_guided_field_skipped)
        self._guided_picker_worker.all_done.connect(self._on_guided_all_done)
        self._guided_picker_worker.error.connect(self._on_guided_error)
        self._guided_picker_worker.finished.connect(self._on_guided_finished)
        self._guided_picker_worker.start()

        field_names = " → ".join(field_labels[k] for k in field_keys if k in field_labels)
        self.statusBar().showMessage(f"Guided picker: {field_names}")
        self.log(f"Guided picker started. Browser will open — click each element in order: {field_names}")
        self._pick_all_btn.setEnabled(False)

    def _on_guided_field_selected(self, field_key: str, selector: str):
        inputs_map = self._field_inputs_map()
        if field_key in inputs_map:
            inputs_map[field_key].setText(selector)
            self.log(f"  [{field_key}] Selector picked: {selector}")

    def _on_guided_field_skipped(self, field_key: str):
        self.log(f"  [{field_key}] Skipped (Esc or timeout).")

    def _on_guided_all_done(self):
        self.statusBar().showMessage("Guided picker complete.")
        self.log("Guided picker: all fields processed.")

    def _on_guided_error(self, error_msg: str):
        self.log(f"Guided picker error: {error_msg}")
        QMessageBox.critical(self, "Picker Error", error_msg)

    def _on_guided_finished(self):
        self._guided_picker_worker = None
        self._pick_all_btn.setEnabled(True)

    def update_progress(self, current: int, total: int, message: str):
        """Update progress"""
        self.progress_bar.setValue(current)
        self.statusBar().showMessage(f"[{current}/{total}] {message}")
        self.log(message)

    def add_result(self, result: LoginResult):
        """Add result to table"""
        self.results.append(result)

        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        # Username
        self.results_table.setItem(row, 0, QTableWidgetItem(result.credential.username))

        # Status
        status_item = QTableWidgetItem(result.status.value)
        if result.status == LoginStatus.SUCCESS:
            status_item.setForeground(Qt.green)
        elif result.status == LoginStatus.FAILED:
            status_item.setForeground(Qt.red)
        else:
            status_item.setForeground(Qt.darkYellow)
        self.results_table.setItem(row, 1, status_item)

        # Message
        self.results_table.setItem(row, 2, QTableWidgetItem(result.message))

        # URL
        self.results_table.setItem(row, 3, QTableWidgetItem(result.url))

        # Screenshot
        screenshot = result.screenshot_path if result.screenshot_path else "N/A"
        self.results_table.setItem(row, 4, QTableWidgetItem(screenshot))

        self.update_statistics()

    def update_statistics(self):
        """Update statistics labels"""
        total = len(self.results)
        success = sum(1 for r in self.results if r.status == LoginStatus.SUCCESS)
        failed = sum(1 for r in self.results if r.status == LoginStatus.FAILED)
        errors = total - success - failed

        self.total_label.setText(f"总计: {total}")
        self.success_label.setText(f"成功: {success}")
        self.failed_label.setText(f"失败: {failed}")
        self.error_label.setText(f"错误: {errors}")

    def verification_finished(self, results: List[LoginResult]):
        """Handle verification completion"""
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)

        self.log("Verification finished!")
        self.statusBar().showMessage("Verification finished")

        # Show summary
        success = sum(1 for r in results if r.status == LoginStatus.SUCCESS)
        if success > 0:
            QMessageBox.warning(
                self,
                "Leaked Passwords Found!",
                f"Warning: {success} valid credentials found!\nPlease take immediate action to protect these accounts."
            )

    def handle_error(self, error_msg: str):
        """Handle worker error"""
        self.log(f"Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)

    def log(self, message: str):
        """Add log message"""
        self.log_text.append(message)
        self.log_text.moveCursor(QTextCursor.End)

    def export_results(self):
        """Export results to CSV"""
        if not self.results:
            QMessageBox.information(self, "Info", "No results to export")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            "verification_results.csv",
            "CSV Files (*.csv);;All Files (*.*)"
        )

        if file_path:
            try:
                import csv
                with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Username", "Password", "Status", "Message", "URL", "Screenshot Path", "Timestamp"])

                    for result in self.results:
                        writer.writerow([
                            result.credential.username,
                            result.credential.password,
                            result.status.value,
                            result.message,
                            result.url,
                            result.screenshot_path or "",
                            result.timestamp
                        ])

                QMessageBox.information(self, "Success", f"Results exported to: {file_path}")
                self.log(f"Results exported to: {file_path}")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Export failed: {str(e)}")


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # First-run check: install playwright browsers if not already present.
    from modules.browser_setup import ensure_browsers_installed
    if not ensure_browsers_installed():
        sys.exit(1)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
