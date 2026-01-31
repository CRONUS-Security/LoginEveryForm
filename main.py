"""
LoginEveryForm - Password Breach Verification Tool
Main GUI Application using PySide6
"""

import sys
import asyncio
from pathlib import Path
from typing import Optional, List

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
        submit_selector: Optional[str],
        success_indicator: Optional[str],
        delay: int
    ):
        super().__init__()
        self.url = url
        self.credentials = credentials
        self.browser_type = browser_type
        self.headless = headless
        self.username_selector = username_selector if username_selector else None
        self.password_selector = password_selector if password_selector else None
        self.captcha_selector = captcha_selector if captcha_selector else None
        self.submit_selector = submit_selector if submit_selector else None
        self.success_indicator = success_indicator if success_indicator else None
        self.delay = delay
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
            # Initialize browser
            browser_type_enum = BrowserType[self.browser_type.upper()]
            automation = BrowserAutomation(
                browser_type=browser_type_enum,
                headless=self.headless,
                screenshot_dir=str(Config.SCREENSHOTS_DIR)
            )

            await automation.start()

            results = []
            total = len(self.credentials)

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
                    submit_selector=self.submit_selector,
                    success_indicator=self.success_indicator
                )

                results.append(result)
                self.result.emit(result)

                # Delay between attempts
                if idx < total and self._is_running:
                    await asyncio.sleep(self.delay / 1000)

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


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()

        Config.ensure_directories()
        self.logger = init_logger(str(Config.LOGS_DIR))

        self.password_loader = PasswordLoader()
        self.credentials: List[Credential] = []
        self.worker: Optional[LoginWorker] = None
        self.results: List[LoginResult] = []

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
        self.delay_spin.setValue(Config.DEFAULT_DELAY_BETWEEN_ATTEMPTS)
        browser_layout.addWidget(self.delay_spin)

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

        # Captcha selector
        captcha_selector_layout = QHBoxLayout()
        captcha_selector_layout.addWidget(QLabel("Captcha Field:"))
        self.captcha_selector_input = QLineEdit()
        self.captcha_selector_input.setPlaceholderText("CSS selector, e.g., input[name='captcha']")
        captcha_selector_layout.addWidget(self.captcha_selector_input)
        selector_layout.addLayout(captcha_selector_layout)

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

        selector_group.setLayout(selector_layout)
        layout.addWidget(selector_group)

        # Control Buttons
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
        """Start verification process"""
        # Validate inputs
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Error", "Please enter the target URL")
            return

        if not self.credentials:
            QMessageBox.warning(self, "Error", "Please load credentials first")
            return

        # Get selectors
        username_selector = self.username_selector_input.text().strip() or None
        password_selector = self.password_selector_input.text().strip() or None
        captcha_selector = self.captcha_selector_input.text().strip() or None
        submit_selector = self.submit_selector_input.text().strip() or None
        success_indicator = self.success_indicator_input.text().strip() or None

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
            submit_selector=submit_selector,
            success_indicator=success_indicator,
            delay=self.delay_spin.value()
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
