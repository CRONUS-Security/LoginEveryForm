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

    async def _get_login_container_scope(self, page: Page) -> str:
        """
        Find the best container scope for login fields: prefer <form> with password,
        then role=form, then common class names. Returns empty string if none.
        """
        # Order: form tag first, then semantic role/classes
        scopes = [
            "form:has(input[type='password'])",
            "[role='form']:has(input[type='password'])",
            ".login-form:has(input[type='password'])",
            ".login-box:has(input[type='password'])",
            ".auth-form:has(input[type='password'])",
            "#loginForm:has(input[type='password'])",
            "[class*='login']:has(input[type='password'])",
        ]
        for scope in scopes:
            try:
                el = await page.query_selector(scope)
                if el:
                    return scope
            except Exception:
                continue
        return ""

    async def _query_in_scope(self, page: Page, scope: str, selector: str):
        """Query element: if scope given, within scope (scope >> selector); else page.query_selector(selector)."""
        try:
            if scope:
                full = f"{scope} >> {selector}"
                return await page.query_selector(full)
            return await page.query_selector(selector)
        except Exception:
            return None

    async def detect_login_form(self, page: Page) -> Dict[str, Optional[str]]:
        """
        Automatically detect login form elements with form-scoped and attribute-based matching
        to improve stability. Prefers: 1) elements inside a form that has a password field,
        2) HTML5 autocomplete attributes, 3) specific name/id/placeholder in priority order.
        """
        self.logger.debug("Detecting login form elements (form-scoped + autocomplete priority)...")

        selectors = {
            "username": None,
            "password": None,
            "captcha": None,
            "submit": None
        }

        try:
            # Prefer form/container that contains password field to avoid matching search/nav bars
            scope = await self._get_login_container_scope(page)

            # ----- Password: high confidence (type=password is definitive) -----
            password_patterns = [
                "input[type='password']",
                "input[autocomplete='current-password']",
                "input[name*='password']",
                "input[name*='passwd']",
                "input[id*='password']",
                "input[id*='passwd']",
                "input[placeholder*='密码']",
                "input[placeholder*='password']",
            ]
            for pattern in password_patterns:
                el = await self._query_in_scope(page, scope, pattern)
                if el:
                    selectors["password"] = f"{scope} >> {pattern}" if scope else pattern
                    self.logger.debug(f"Password field found: {selectors['password']}")
                    break
            if not selectors["password"]:
                # Fallback: any password on page
                for pattern in password_patterns:
                    el = await page.query_selector(pattern)
                    if el:
                        selectors["password"] = pattern
                        self.logger.debug(f"Password field (page fallback): {pattern}")
                        break

            # ----- Username: prefer autocomplete, then name/placeholder (avoid captcha-like) -----
            username_patterns = [
                "input[autocomplete='username']",
                "input[autocomplete='email']",
                "input[type='email']",
                "input[name='username']",
                "input[name='user']",
                "input[name='account']",
                "input[name='login']",
                "input[name='email']",
                "input[type='text'][name*='user']",
                "input[type='text'][name*='login']",
                "input[type='text'][name*='account']",
                "input[id='username']",
                "input[id='user']",
                "input[id='account']",
                "input[id='login']",
                "input[type='text'][id*='user']",
                "input[type='text'][id*='login']",
                "input[type='text'][id*='account']",
                "input[placeholder*='用户']",
                "input[placeholder*='用户名']",
                "input[placeholder*='账号']",
                "input[placeholder*='邮箱']",
                "input[placeholder*='手机']",
                "input[placeholder*='username']",
                "input[placeholder*='email']",
                "input[placeholder*='account']",
                # Exclude likely captcha: not name/id containing code/captcha/verify
                "input[type='text']:not([name*='captcha']):not([name*='code']):not([name*='verify']):not([id*='captcha']):not([id*='code']):not([id*='verify'])",
            ]
            for pattern in username_patterns:
                el = await self._query_in_scope(page, scope, pattern)
                if el:
                    selectors["username"] = f"{scope} >> {pattern}" if scope else pattern
                    self.logger.debug(f"Username field found: {selectors['username']}")
                    break
            if not selectors["username"]:
                for pattern in username_patterns:
                    el = await page.query_selector(pattern)
                    if el:
                        selectors["username"] = pattern
                        self.logger.debug(f"Username field (page fallback): {pattern}")
                        break

            # ----- Captcha: prefer explicit captcha/verify/验证码 to avoid "discount code" -----
            captcha_patterns = [
                "input[name*='captcha']",
                "input[name*='verify']",
                "input[id*='captcha']",
                "input[id*='verify']",
                "input[placeholder*='验证码']",
                "input[placeholder*='captcha']",
                "input[placeholder*='图形码']",
                "input[placeholder*='安全码']",
                "input[name*='code']",
                "input[id*='code']",
                "input[placeholder*='code']",
            ]
            for pattern in captcha_patterns:
                el = await self._query_in_scope(page, scope, pattern)
                if el:
                    # Avoid treating main username as captcha: if same as username selector, skip
                    if selectors["username"] and (pattern == selectors["username"] or (scope and selectors["username"] == f"{scope} >> {pattern}")):
                        continue
                    selectors["captcha"] = f"{scope} >> {pattern}" if scope else pattern
                    self.logger.debug(f"Captcha field found: {selectors['captcha']}")
                    break
            if not selectors["captcha"]:
                for pattern in captcha_patterns:
                    el = await page.query_selector(pattern)
                    if el:
                        if selectors["username"] and pattern == selectors["username"]:
                            continue
                        selectors["captcha"] = pattern
                        self.logger.debug(f"Captcha field (page fallback): {pattern}")
                        break

            # ----- Submit button -----
            submit_patterns = [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('登录')",
                "button:has-text('登錄')",
                "button:has-text('登 录')",
                "button:has-text('Login')",
                "button:has-text('Sign in')",
                "button:has-text('Sign In')",
                "button[name*='login']",
                "button[id*='login']",
                "input[value*='登录']",
                "input[value*='登 录']",
                "input[value*='Login']",
                "input[value*='Sign in']",
                "a:has-text('登录')",
                "a:has-text('Login')",
            ]
            for pattern in submit_patterns:
                el = await self._query_in_scope(page, scope, pattern)
                if el:
                    selectors["submit"] = f"{scope} >> {pattern}" if scope else pattern
                    self.logger.debug(f"Submit button found: {selectors['submit']}")
                    break
            if not selectors["submit"]:
                for pattern in submit_patterns:
                    el = await page.query_selector(pattern)
                    if el:
                        selectors["submit"] = pattern
                        self.logger.debug(f"Submit button (page fallback): {pattern}")
                        break

            return selectors

        except Exception as e:
            self.logger.error(f"Error detecting login form: {e}")
            return selectors

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
            # Common captcha image selectors
            if not captcha_selector:
                captcha_image_patterns = [
                    "img[src*='captcha']",
                    "img[src*='code']",
                    "img[src*='verify']",
                    "img[alt*='验证码']",
                    "img[alt*='captcha']",
                    "#captcha-image",
                    ".captcha-image",
                ]

                for pattern in captcha_image_patterns:
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
            # Create new page
            page = await self.context.new_page()
            page.set_default_timeout(self.timeout)

            # Navigate to login page
            self.logger.info(f"Navigating to: {url}")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=self.timeout)

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

            # Check if URL changed (common success indicator)
            if current_url != original_url and not any(err in current_url.lower() for err in ['error', 'login', 'signin']):
                self.logger.debug(f"URL changed: {original_url} → {current_url}")
                return True

            # Check for custom success indicator
            if success_indicator:
                if success_indicator.startswith("http"):
                    # URL pattern matching
                    if success_indicator in current_url:
                        return True
                else:
                    # CSS selector
                    element = await page.query_selector(success_indicator)
                    if element:
                        return True

            # Check for common error indicators
            error_patterns = [
                "text=/错误|失败|error|failed|invalid|incorrect/i",
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

            # Check for common success indicators
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

            # If still on login page with username field present, likely failed
            username_field = await page.query_selector("input[type='text'], input[type='email']")
            if username_field:
                self.logger.debug("Still on login page with username field present")
                return False

            # Default: if no clear error and URL changed, consider success
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
