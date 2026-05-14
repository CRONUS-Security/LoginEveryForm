"""
LoginEveryForm - Password Breach Verification Tool
Main GUI Application using PySide6
"""

import sys
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
                        result = await per_attempt_automation.attempt_login(
                            url=self.url,
                            credential=credential,
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

                    result = await automation.attempt_login(
                        url=self.url,
                        credential=credential,
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
    """Worker thread: open browser, detect login form elements, emit CSS selectors to GUI."""

    detected = Signal(object)  # Dict[str, Optional[str]]: username, password, captcha, submit
    error = Signal(str)

    def __init__(self, url: str, browser_type: str, headless: bool):
        super().__init__()
        self.url = url.strip()
        self.browser_type = browser_type
        self.headless = headless

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
            await page.close()

            self.detected.emit(selectors)
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

        self._picker_worker: Optional[InteractiveSelectorWorker] = None
        self._picker_target_input: Optional[QLineEdit] = None
        self._pending_picker_fields: List[tuple] = []  # list of (field_key, QLineEdit)

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

        def _make_pick_btn(field_key: str, input_widget: QLineEdit) -> QPushButton:
            btn = QPushButton("Pick")
            btn.setToolTip("Interactively select this element in the browser")
            btn.setFixedWidth(48)
            btn.clicked.connect(lambda: self._start_interactive_picker(field_key, input_widget))
            return btn

        # Username selector
        username_selector_layout = QHBoxLayout()
        username_selector_layout.addWidget(QLabel("Username Field:"))
        self.username_selector_input = QLineEdit()
        self.username_selector_input.setPlaceholderText("CSS selector, e.g., input[name='username']")
        username_selector_layout.addWidget(self.username_selector_input)
        username_selector_layout.addWidget(_make_pick_btn("username", self.username_selector_input))
        selector_layout.addLayout(username_selector_layout)

        # Password selector
        password_selector_layout = QHBoxLayout()
        password_selector_layout.addWidget(QLabel("Password Field:"))
        self.password_selector_input = QLineEdit()
        self.password_selector_input.setPlaceholderText("CSS selector, e.g., input[type='password']")
        password_selector_layout.addWidget(self.password_selector_input)
        password_selector_layout.addWidget(_make_pick_btn("password", self.password_selector_input))
        selector_layout.addLayout(password_selector_layout)

        # Captcha selector
        captcha_selector_layout = QHBoxLayout()
        captcha_selector_layout.addWidget(QLabel("Captcha Field:"))
        self.captcha_selector_input = QLineEdit()
        self.captcha_selector_input.setPlaceholderText("CSS selector, e.g., input[name='captcha']")
        captcha_selector_layout.addWidget(self.captcha_selector_input)
        captcha_selector_layout.addWidget(_make_pick_btn("captcha", self.captcha_selector_input))
        selector_layout.addLayout(captcha_selector_layout)

        # Captcha image selector
        captcha_image_selector_layout = QHBoxLayout()
        captcha_image_selector_layout.addWidget(QLabel("Captcha Image:"))
        self.captcha_image_selector_input = QLineEdit()
        self.captcha_image_selector_input.setPlaceholderText("CSS selector, e.g., img.captcha-img")
        captcha_image_selector_layout.addWidget(self.captcha_image_selector_input)
        captcha_image_selector_layout.addWidget(_make_pick_btn("captcha_image", self.captcha_image_selector_input))
        selector_layout.addLayout(captcha_image_selector_layout)

        # Enable captcha recognition toggle
        captcha_enable_layout = QHBoxLayout()
        self.enable_captcha_check = QCheckBox("Enable captcha recognition and auto-fill")
        self.enable_captcha_check.setChecked(True)
        self.enable_captcha_check.setToolTip(
            "When checked, the captcha image will be solved automatically and filled into the captcha field.\n"
            "Uncheck to skip captcha handling entirely (captcha selectors above will be ignored)."
        )
        self.enable_captcha_check.toggled.connect(self._on_captcha_enable_toggled)
        captcha_enable_layout.addWidget(self.enable_captcha_check)
        captcha_enable_layout.addStretch()
        selector_layout.addLayout(captcha_enable_layout)

        # Submit selector
        submit_selector_layout = QHBoxLayout()
        submit_selector_layout.addWidget(QLabel("Submit Button:"))
        self.submit_selector_input = QLineEdit()
        self.submit_selector_input.setPlaceholderText("CSS selector, e.g., button[type='submit']")
        submit_selector_layout.addWidget(self.submit_selector_input)
        submit_selector_layout.addWidget(_make_pick_btn("submit", self.submit_selector_input))
        selector_layout.addLayout(submit_selector_layout)

        # Success indicator
        success_indicator_layout = QHBoxLayout()
        success_indicator_layout.addWidget(QLabel("Success Indicator:"))
        self.success_indicator_input = QLineEdit()
        self.success_indicator_input.setPlaceholderText("CSS selector or URL, e.g., #dashboard or /dashboard")
        success_indicator_layout.addWidget(self.success_indicator_input)
        selector_layout.addLayout(success_indicator_layout)

        selector_group.setLayout(selector_layout)
        layout.addWidget(selector_group)

        # Control Buttons
        control_layout = QHBoxLayout()
        self.check_button = QPushButton("Check")
        self.check_button.clicked.connect(self.check_form)
        self.check_button.setStyleSheet("QPushButton { background-color: #2196F3; color: white; padding: 10px; font-weight: bold; }")
        self.check_button.setToolTip("Only URL needed (no credentials). Open browser, detect login form controls, and fill CSS selectors above.")
        control_layout.addWidget(self.check_button)

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

        self.check_worker = CheckFormWorker(
            url=url,
            browser_type=self.browser_combo.currentText(),
            headless=self.headless_check.isChecked(),
        )
        self.check_worker.detected.connect(self._on_check_detected)
        self.check_worker.error.connect(self._on_check_error)
        self.check_worker.finished.connect(self._on_check_finished)
        self.check_worker.start()

    def _on_check_detected(self, selectors: Dict[str, Any]):
        """Fill GUI selector inputs with detected CSS expressions."""
        username = selectors.get("username") or ""
        password = selectors.get("password") or ""
        captcha = selectors.get("captcha") or ""
        captcha_image = selectors.get("captcha_image") or ""
        submit = selectors.get("submit") or ""

        self.username_selector_input.setText(username)
        self.password_selector_input.setText(password)
        self.captcha_selector_input.setText(captcha)
        self.captcha_image_selector_input.setText(captcha_image)
        self.submit_selector_input.setText(submit)

        self.log("Check: Detected selectors filled.")
        self.log(f"  Username:      {username or '(none)'}")
        self.log(f"  Password:      {password or '(none)'}")
        self.log(f"  Captcha:       {captcha or '(none)'}")
        self.log(f"  Captcha Image: {captcha_image or '(none)'}")
        self.log(f"  Submit:        {submit or '(none)'}")
        self.statusBar().showMessage("Detection complete. Selectors filled.")

        # Prompt interactive picker when required fields could not be located
        missing = []
        if not username:
            missing.append(("username", self.username_selector_input))
        if not password:
            missing.append(("password", self.password_selector_input))
        if not submit:
            missing.append(("submit", self.submit_selector_input))

        if missing:
            missing_labels = ", ".join(k for k, _ in missing)
            reply = QMessageBox.question(
                self,
                "Auto-Detection Incomplete",
                f"Could not auto-detect the following required elements:\n  {missing_labels}\n\n"
                "Launch the interactive element picker to select them manually?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self._pending_picker_fields = list(missing[1:])
                self._start_interactive_picker(missing[0][0], missing[0][1])

    def _on_check_error(self, error_msg: str):
        """Handle check worker error."""
        self.log(f"Check error: {error_msg}")
        QMessageBox.critical(self, "Check Failed", error_msg)
        self.statusBar().showMessage("Check failed")

    def _on_check_finished(self):
        """Re-enable Check button when worker finishes."""
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

    def _start_interactive_picker(self, field_key: str, input_widget: QLineEdit):
        """Launch the interactive element picker for the specified field."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter the target URL first.")
            return

        if self._picker_worker and self._picker_worker.isRunning():
            QMessageBox.information(
                self, "Picker Active",
                "An interactive picker is already running. Please complete or cancel it first."
            )
            return

        field_labels: Dict[str, str] = {
            "username": "Username Field",
            "password": "Password Field",
            "captcha": "Captcha Field",
            "captcha_image": "Captcha Image",
            "submit": "Submit Button",
        }
        label = field_labels.get(field_key, field_key)

        self._picker_target_input = input_widget
        self._picker_worker = InteractiveSelectorWorker(
            url=url,
            browser_type=self.browser_combo.currentText(),
            field_label=label,
        )
        self._picker_worker.selected.connect(self._on_picker_selected)
        self._picker_worker.cancelled.connect(self._on_picker_cancelled)
        self._picker_worker.error.connect(self._on_picker_error)
        self._picker_worker.finished.connect(self._on_picker_finished)
        self._picker_worker.start()

        self.statusBar().showMessage(f"Interactive picker active: click the {label} in the browser...")
        self.log(f"Interactive picker started for '{label}'. Click the element in the browser window, or press Esc to cancel.")

    def _on_picker_selected(self, selector: str):
        """Fill the target input with the picked CSS selector."""
        if self._picker_target_input is not None:
            self._picker_target_input.setText(selector)
            self.log(f"  Selector picked: {selector}")
        self._continue_pending_picker()

    def _on_picker_cancelled(self):
        """Handle picker cancellation."""
        self.log("Interactive picker cancelled.")
        self._continue_pending_picker()

    def _on_picker_error(self, error_msg: str):
        """Handle picker error."""
        self.log(f"Interactive picker error: {error_msg}")
        self._continue_pending_picker()

    def _on_picker_finished(self):
        """Clean up picker worker reference after it has finished."""
        self._picker_worker = None
        self._picker_target_input = None

    def _continue_pending_picker(self):
        """Start the next queued field picker, or mark the workflow complete."""
        if self._pending_picker_fields:
            field_key, input_widget = self._pending_picker_fields.pop(0)
            self._start_interactive_picker(field_key, input_widget)
        else:
            self.statusBar().showMessage("Interactive picker workflow complete.")

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

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
