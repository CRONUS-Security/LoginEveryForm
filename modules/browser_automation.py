"""
Browser Automation Module
Using Playwright for automated login testing
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, List, Literal
from enum import Enum

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout
)

from .logger import get_logger
from .captcha_solver import CaptchaSolver
from .password_loader import Credential
from .form_detection import detect_login_form, wait_for_login_form, get_captcha_image_patterns


class LoginStatus(Enum):
    """Login attempt status"""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ERROR = "ERROR"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    TIMEOUT = "TIMEOUT"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"


class BrowserType(Enum):
    """Supported browser types"""
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class LoginResult:
    """Result of a login attempt"""

    def __init__(
        self,
        status: LoginStatus,
        credential: Credential,
        url: str,
        message: str = "",
        screenshot_path: Optional[str] = None
    ):
        self.status = status
        self.credential = credential
        self.url = url
        self.message = message
        self.screenshot_path = screenshot_path
        self.timestamp = time.time()

    def __repr__(self):
        return f"LoginResult(status={self.status.value}, username={self.credential.username}, url={self.url})"


class BrowserAutomation:
    """Browser automation for login form testing"""

    def __init__(
        self,
        browser_type: BrowserType = BrowserType.CHROMIUM,
        headless: bool = False,
        timeout: int = 30000,
        screenshot_dir: str = "screenshots"
    ):
        """
        Initialize browser automation

        Args:
            browser_type: Browser to use (chromium, firefox, webkit)
            headless: Run browser in headless mode
            timeout: Default timeout in milliseconds
            screenshot_dir: Directory to save screenshots
        """
        self.logger = get_logger()
        self.browser_type = browser_type
        self.headless = headless
        self.timeout = timeout
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(exist_ok=True)

        self.playwright_manager = None
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.captcha_solver = CaptchaSolver()

        self.logger.info(f"Browser automation initialized (type={browser_type.value}, headless={headless})")

    async def start(self):
        """Start browser instance"""
        try:
            self.playwright_manager = async_playwright()
            self.playwright = await self.playwright_manager.__aenter__()

            browser_launch_options = {
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ]
            }

            if self.browser_type == BrowserType.CHROMIUM:
                self.browser = await self.playwright.chromium.launch(**browser_launch_options)
            elif self.browser_type == BrowserType.FIREFOX:
                self.browser = await self.playwright.firefox.launch(**browser_launch_options)
            elif self.browser_type == BrowserType.WEBKIT:
                self.browser = await self.playwright.webkit.launch(**browser_launch_options)

            # Create context with realistic settings
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            self.logger.success(f"Browser started: {self.browser_type.value}")

        except Exception as e:
            self.logger.error(f"Failed to start browser: {e}")
            raise

    async def stop(self):
        """Stop browser instance"""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright_manager:
                await self.playwright_manager.__aexit__(None, None, None)

            self.logger.info("Browser stopped")

        except Exception as e:
            self.logger.error(f"Error stopping browser: {e}")

    async def detect_login_form(self, page: Page) -> Dict[str, Optional[str]]:
        """
        自动检测登录表单控件（规则见 modules/form_detection/ 下各文件）。
        """
        self.logger.debug("Detecting login form elements (form-scoped + autocomplete priority)...")
        await wait_for_login_form(page, timeout_ms=5000)
        return await detect_login_form(page, self.logger)

    async def get_captcha_image(self, page: Page, captcha_selector: Optional[str] = None) -> Optional[bytes]:
        """
        Get captcha image from page

        Args:
            page: Playwright page object
            captcha_selector: CSS selector for captcha image (optional)

        Returns:
            Image bytes or None
        """
        try:
            # Common captcha image selectors (from form_detection/captcha_image.py)
            if not captcha_selector:
                for pattern in get_captcha_image_patterns():
                    captcha_element = await page.query_selector(pattern)
                    if captcha_element:
                        captcha_selector = pattern
                        break

            if not captcha_selector:
                self.logger.warning("Captcha image not found")
                return None

            # Get captcha image
            captcha_element = await page.query_selector(captcha_selector)
            if captcha_element:
                image_bytes = await captcha_element.screenshot()
                self.logger.debug("Captcha image captured")
                return image_bytes

            return None

        except Exception as e:
            self.logger.error(f"Error getting captcha image: {e}")
            return None

    async def solve_captcha(self, page: Page, captcha_selector: Optional[str] = None) -> Optional[str]:
        """
        Solve captcha on page

        Args:
            page: Playwright page object
            captcha_selector: CSS selector for captcha image (optional)

        Returns:
            Solved captcha text or None
        """
        try:
            image_bytes = await self.get_captcha_image(page, captcha_selector)
            if not image_bytes:
                return None

            captcha_text = self.captcha_solver.solve_from_bytes(image_bytes)
            if captcha_text:
                self.logger.info(f"Captcha solved: {captcha_text}")
            else:
                self.logger.warning("Failed to solve captcha")

            return captcha_text

        except Exception as e:
            self.logger.error(f"Error solving captcha: {e}")
            return None

    async def attempt_login(
        self,
        url: str,
        credential: Credential,
        username_selector: Optional[str] = None,
        password_selector: Optional[str] = None,
        captcha_selector: Optional[str] = None,
        submit_selector: Optional[str] = None,
        success_indicator: Optional[str] = None,
        wait_after_submit: int = 3000
    ) -> LoginResult:
        """
        Attempt login with provided credentials

        Args:
            url: Login page URL
            credential: Credential object with username/password
            username_selector: CSS selector for username field (auto-detect if None)
            password_selector: CSS selector for password field (auto-detect if None)
            captcha_selector: CSS selector for captcha field (auto-detect if None)
            submit_selector: CSS selector for submit button (auto-detect if None)
            success_indicator: CSS selector or URL pattern to verify success
            wait_after_submit: Time to wait after submit (milliseconds)

        Returns:
            LoginResult object
        """
        page = None
        screenshot_path = None

        try:
            # 每次测试前清空 cookie 和 session，保证独立登录环境，窗口保持不关
            if self.context:
                await self.context.clear_cookies()
                self.logger.debug("Cleared cookies and session state for this attempt")

            # Create new page
            page = await self.context.new_page()
            page.set_default_timeout(self.timeout)

            # Navigate to login page
            self.logger.info(f"Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("load", timeout=self.timeout)

            # Auto-detect form elements if not provided
            if not username_selector or not password_selector:
                self.logger.debug("Auto-detecting form elements...")
                detected = await self.detect_login_form(page)

                if not username_selector:
                    username_selector = detected["username"]
                if not password_selector:
                    password_selector = detected["password"]
                if not captcha_selector:
                    captcha_selector = detected["captcha"]
                if not submit_selector:
                    submit_selector = detected["submit"]

            # Validate required fields
            if not username_selector or not password_selector:
                msg = "Username or password field not found"
                self.logger.error(msg)
                return LoginResult(LoginStatus.ELEMENT_NOT_FOUND, credential, url, msg)

            # Fill username
            self.logger.debug(f"Filling username: {credential.username}")
            await page.fill(username_selector, credential.username)
            await page.wait_for_timeout(500)

            # Fill password
            self.logger.debug("Filling password")
            await page.fill(password_selector, credential.password)
            await page.wait_for_timeout(500)

            # Handle captcha if present
            if captcha_selector:
                self.logger.info("Captcha field detected, attempting to solve...")
                captcha_text = await self.solve_captcha(page)

                if captcha_text:
                    await page.fill(captcha_selector, captcha_text)
                    await page.wait_for_timeout(500)
                else:
                    msg = "Failed to solve captcha"
                    self.logger.warning(msg)
                    screenshot_path = await self._save_screenshot(page, credential.username, "captcha_failed")
                    return LoginResult(LoginStatus.CAPTCHA_REQUIRED, credential, url, msg, screenshot_path)

            # Submit form
            if submit_selector:
                self.logger.debug("Clicking submit button")
                await page.click(submit_selector)
            else:
                self.logger.debug("Pressing Enter to submit")
                await page.press(password_selector, "Enter")

            # Wait for navigation/response
            await page.wait_for_timeout(wait_after_submit)

            # Take screenshot
            screenshot_path = await self._save_screenshot(page, credential.username, "after_submit")

            # Check if login was successful
            is_success = await self._verify_login_success(page, url, success_indicator)

            if is_success:
                msg = "Login successful"
                self.logger.success(f"✓ {credential.username} @ {url}")
                status = LoginStatus.SUCCESS
            else:
                msg = "Login failed - incorrect credentials or other error"
                self.logger.failed(f"✗ {credential.username} @ {url}")
                status = LoginStatus.FAILED

            return LoginResult(status, credential, url, msg, screenshot_path)

        except PlaywrightTimeout as e:
            msg = f"Timeout: {str(e)}"
            self.logger.error(msg)
            if page:
                screenshot_path = await self._save_screenshot(page, credential.username, "timeout")
            return LoginResult(LoginStatus.TIMEOUT, credential, url, msg, screenshot_path)

        except Exception as e:
            msg = f"Error: {str(e)}"
            self.logger.error(msg)
            if page:
                screenshot_path = await self._save_screenshot(page, credential.username, "error")
            return LoginResult(LoginStatus.ERROR, credential, url, msg, screenshot_path)

        finally:
            if page:
                await page.close()

    async def _verify_login_success(
        self,
        page: Page,
        original_url: str,
        success_indicator: Optional[str] = None
    ) -> bool:
        """
        Verify if login was successful

        Args:
            page: Playwright page object
            original_url: Original login page URL
            success_indicator: CSS selector or URL pattern for success verification

        Returns:
            True if login successful, False otherwise
        """
        try:
            current_url = page.url

            # 先检测页面上的失败提示（避免仅因 URL 变化误判为成功）
            error_patterns = [
                "text=/错误|失败|error|failed|invalid|incorrect|unable to login|cannot login|login failed|access denied/i",
                ".error",
                ".alert-error",
                ".alert-danger",
                "#error",
            ]
            for pattern in error_patterns:
                element = await page.query_selector(pattern)
                if element:
                    self.logger.debug(f"Error indicator found: {pattern}")
                    return False

            # 再检查自定义成功条件
            if success_indicator:
                if success_indicator.startswith("http"):
                    if success_indicator in current_url:
                        return True
                else:
                    element = await page.query_selector(success_indicator)
                    if element:
                        return True

            # URL 变化且不含“仍在登录/认证”的路径时才视为成功（含 #!/auth、/login、/signin 等不算成功）
            url_lower = current_url.lower()
            if current_url != original_url and not any(
                err in url_lower for err in ["error", "login", "signin", "auth"]
            ):
                self.logger.debug(f"URL changed: {original_url} → {current_url}")
                return True

            # 常见成功元素
            success_patterns = [
                "text=/欢迎|welcome|dashboard|home|profile/i",
                ".user-menu",
                ".profile",
                "#dashboard",
            ]
            for pattern in success_patterns:
                element = await page.query_selector(pattern)
                if element:
                    self.logger.debug(f"Success indicator found: {pattern}")
                    return True

            # 仍在登录页（有用户名框）视为失败
            username_field = await page.query_selector("input[type='text'], input[type='email']")
            if username_field:
                self.logger.debug("Still on login page with username field present")
                return False

            # 默认：无明确错误且 URL 变化才视为成功（auth 已在上面排除）
            return current_url != original_url

        except Exception as e:
            self.logger.error(f"Error verifying login success: {e}")
            return False

    async def _save_screenshot(self, page: Page, username: str, suffix: str = "") -> str:
        """Save screenshot of current page"""
        try:
            timestamp = int(time.time())
            safe_username = "".join(c for c in username if c.isalnum() or c in "-_")
            filename = f"{safe_username}_{timestamp}_{suffix}.png"
            filepath = self.screenshot_dir / filename

            await page.screenshot(path=str(filepath), full_page=True)
            self.logger.debug(f"Screenshot saved: {filepath}")

            return str(filepath)

        except Exception as e:
            self.logger.error(f"Failed to save screenshot: {e}")
            return ""

    async def batch_login(
        self,
        url: str,
        credentials: List[Credential],
        username_selector: Optional[str] = None,
        password_selector: Optional[str] = None,
        captcha_selector: Optional[str] = None,
        submit_selector: Optional[str] = None,
        success_indicator: Optional[str] = None,
        delay_between_attempts: int = 2000
    ) -> List[LoginResult]:
        """
        Attempt login with multiple credentials

        Args:
            url: Login page URL
            credentials: List of Credential objects
            username_selector: CSS selector for username field
            password_selector: CSS selector for password field
            captcha_selector: CSS selector for captcha field
            submit_selector: CSS selector for submit button
            success_indicator: Success verification selector/pattern
            delay_between_attempts: Delay between attempts (milliseconds)

        Returns:
            List of LoginResult objects
        """
        results = []
        total = len(credentials)

        self.logger.section(f"Starting Batch Login Test - {total} credentials")

        for idx, credential in enumerate(credentials, 1):
            self.logger.progress_info(idx, total, f"Testing: {credential.username}")

            result = await self.attempt_login(
                url=url,
                credential=credential,
                username_selector=username_selector,
                password_selector=password_selector,
                captcha_selector=captcha_selector,
                submit_selector=submit_selector,
                success_indicator=success_indicator
            )

            results.append(result)
            self.logger.credential_attempt(url, credential.username, result.status.value)

            # Delay between attempts
            if idx < total:
                await asyncio.sleep(delay_between_attempts / 1000)

        # Summary
        success_count = sum(1 for r in results if r.status == LoginStatus.SUCCESS)
        failed_count = sum(1 for r in results if r.status == LoginStatus.FAILED)
        error_count = sum(1 for r in results if r.status in [LoginStatus.ERROR, LoginStatus.TIMEOUT, LoginStatus.ELEMENT_NOT_FOUND])

        self.logger.summary(total, success_count, failed_count, error_count)

        return results
