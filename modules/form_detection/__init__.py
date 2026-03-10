"""
登录表单控件识别规则包。
各规则按文件拆分，便于单独调整：
- container.py  登录容器 scope
- password.py   密码框
- username.py   用户名框
- captcha.py    验证码输入框
- submit.py     提交按钮
- captcha_image.py  验证码图片
"""
from typing import Dict, Optional, List

from playwright.async_api import Page

from .container import CONTAINER_SCOPES
from .password import PASSWORD_PATTERNS
from .username import USERNAME_PATTERNS
from .captcha import CAPTCHA_PATTERNS
from .submit import SUBMIT_PATTERNS
from .captcha_image import CAPTCHA_IMAGE_PATTERNS

__all__ = [
    "detect_login_form",
    "wait_for_login_form",
    "get_container_scopes",
    "get_password_patterns",
    "get_username_patterns",
    "get_captcha_patterns",
    "get_submit_patterns",
    "get_captcha_image_patterns",
]


def get_container_scopes() -> List[str]:
    """返回登录容器选择器列表（用于限定查找范围）。"""
    return list(CONTAINER_SCOPES)


def get_password_patterns() -> List[str]:
    """返回密码框 CSS 选择器列表。"""
    return list(PASSWORD_PATTERNS)


def get_username_patterns() -> List[str]:
    """返回用户名框 CSS 选择器列表。"""
    return list(USERNAME_PATTERNS)


def get_captcha_patterns() -> List[str]:
    """返回验证码输入框 CSS 选择器列表。"""
    return list(CAPTCHA_PATTERNS)


def get_submit_patterns() -> List[str]:
    """返回提交按钮 CSS 选择器列表。"""
    return list(SUBMIT_PATTERNS)


def get_captcha_image_patterns() -> List[str]:
    """返回验证码图片元素 CSS 选择器列表。"""
    return list(CAPTCHA_IMAGE_PATTERNS)


async def wait_for_login_form(page: Page, timeout_ms: int = 5000) -> None:
    """
    等待登录表单出现在 DOM 中（避免 load 后 SPA 尚未渲染导致检测为空）。
    先尝试等待容器 scope，否则等待 input[type='password']。
    """
    for scope in get_container_scopes():
        try:
            await page.wait_for_selector(scope, state="attached", timeout=timeout_ms)
            return
        except Exception:
            continue
    try:
        await page.wait_for_selector("input[type='password']", state="attached", timeout=timeout_ms)
    except Exception:
        pass


async def _get_login_container_scope(page: Page, scopes: List[str]) -> str:
    """在页面中查找第一个匹配的登录容器 scope，未找到返回空字符串。"""
    for scope in scopes:
        try:
            el = await page.query_selector(scope)
            if el:
                return scope
        except Exception:
            continue
    return ""


async def _query_in_scope(page: Page, scope: str, selector: str):
    """在 scope 内查找元素；scope 为空则在整页查找。"""
    try:
        if scope:
            full = f"{scope} >> {selector}"
            return await page.query_selector(full)
        return await page.query_selector(selector)
    except Exception:
        return None


async def detect_login_form(page: Page, logger) -> Dict[str, Optional[str]]:
    """
    根据 form_detection 下各规则文件中的选择器，自动检测登录表单控件。
    返回 {"username": str|None, "password": str|None, "captcha": str|None, "submit": str|None}。
    """
    selectors = {
        "username": None,
        "password": None,
        "captcha": None,
        "submit": None,
    }

    try:
        scopes = get_container_scopes()
        scope = await _get_login_container_scope(page, scopes)

        # ----- 密码 -----
        for pattern in get_password_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                selectors["password"] = f"{scope} >> {pattern}" if scope else pattern
                logger.debug(f"Password field found: {selectors['password']}")
                break
        if not selectors["password"]:
            for pattern in get_password_patterns():
                el = await page.query_selector(pattern)
                if el:
                    selectors["password"] = pattern
                    logger.debug(f"Password field (page fallback): {pattern}")
                    break

        # ----- 用户名 -----
        for pattern in get_username_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                selectors["username"] = f"{scope} >> {pattern}" if scope else pattern
                logger.debug(f"Username field found: {selectors['username']}")
                break
        if not selectors["username"]:
            for pattern in get_username_patterns():
                el = await page.query_selector(pattern)
                if el:
                    selectors["username"] = pattern
                    logger.debug(f"Username field (page fallback): {pattern}")
                    break

        # ----- 验证码输入框 -----
        for pattern in get_captcha_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                if selectors["username"] and (
                    pattern == selectors["username"]
                    or (scope and selectors["username"] == f"{scope} >> {pattern}")
                ):
                    continue
                selectors["captcha"] = f"{scope} >> {pattern}" if scope else pattern
                logger.debug(f"Captcha field found: {selectors['captcha']}")
                break
        if not selectors["captcha"]:
            for pattern in get_captcha_patterns():
                el = await page.query_selector(pattern)
                if el:
                    if selectors["username"] and pattern == selectors["username"]:
                        continue
                    selectors["captcha"] = pattern
                    logger.debug(f"Captcha field (page fallback): {pattern}")
                    break

        # ----- 提交按钮 -----
        for pattern in get_submit_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                selectors["submit"] = f"{scope} >> {pattern}" if scope else pattern
                logger.debug(f"Submit button found: {selectors['submit']}")
                break
        if not selectors["submit"]:
            for pattern in get_submit_patterns():
                el = await page.query_selector(pattern)
                if el:
                    selectors["submit"] = pattern
                    logger.debug(f"Submit button (page fallback): {pattern}")
                    break

        return selectors

    except Exception as e:
        logger.error(f"Error detecting login form: {e}")
        return selectors
