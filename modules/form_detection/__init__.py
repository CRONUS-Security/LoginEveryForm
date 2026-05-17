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
import time
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


async def wait_for_login_form(page: Page, timeout_ms: int = 5000, logger=None) -> None:
    """
    等待页面 DOM 加载完成（domcontentloaded）。
    容器 scope 检测由后续的 detect_login_form 负责，此处不再轮询选择器。
    """
    def _dbg(msg: str):
        if logger:
            logger.debug(msg)

    import time as _time
    t0 = _time.perf_counter()
    _dbg("[wait_for_login_form] 等待 domcontentloaded...")
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        _dbg(f"[wait_for_login_form] ✅ domcontentloaded（{(_time.perf_counter()-t0)*1000:.0f}ms）")
    except Exception as e:
        _dbg(f"[wait_for_login_form] ⚠ domcontentloaded 超时，继续检测: {e!s:.80}")


async def _get_login_container_scope(page: Page, scopes: List[str], logger=None) -> str:
    """在页面中查找第一个匹配的登录容器 scope，未找到返回空字符串。"""
    for scope in scopes:
        try:
            t0 = time.perf_counter()
            el = await page.query_selector(scope)
            elapsed = (time.perf_counter() - t0) * 1000
            if el:
                if logger:
                    logger.debug(f"[container_scope] ✅ 命中: {scope!r}（{elapsed:.0f}ms）")
                return scope
            if logger:
                logger.debug(f"[container_scope] ✗ 无元素: {scope!r}（{elapsed:.0f}ms）")
        except Exception as e:
            if logger:
                logger.debug(f"[container_scope] ✗ 异常: {scope!r}: {e!s:.80}")
            continue
    return ""


async def _query_in_scope(page: Page, scope: str, selector: str):
    """在 scope 内查找**可见**元素；scope 为空则在整页查找。
    只返回 is_visible() 为 True 的元素，避免匹配到隐藏字段后
    wait_for_selector（默认 state='visible'）超时。
    """
    try:
        if scope:
            full = f"{scope} >> {selector}"
            el = await page.query_selector(full)
        else:
            el = await page.query_selector(selector)
        if el and await el.is_visible():
            return el
        return None
    except Exception:
        return None


async def detect_login_form(page: Page, logger) -> Dict[str, Optional[str]]:
    """
    根据 form_detection 下各规则文件中的选择器，自动检测登录表单控件。
    返回 {"username": str|None, "password": str|None, "captcha": str|None, "captcha_image": str|None, "submit": str|None}。
    """
    selectors = {
        "username": None,
        "password": None,
        "captcha": None,
        "captcha_image": None,
        "submit": None,
    }

    def _dbg(msg: str):
        logger.debug(msg)

    try:
        t_total = time.perf_counter()
        scopes = get_container_scopes()
        _dbg(f"[detect_login_form] 开始，共 {len(scopes)} 个容器 scope，"
             f"password:{len(get_password_patterns())} username:{len(get_username_patterns())} "
             f"captcha:{len(get_captcha_patterns())} submit:{len(get_submit_patterns())} "
             f"captcha_img:{len(get_captcha_image_patterns())} 个规则")

        t0 = time.perf_counter()
        scope = await _get_login_container_scope(page, scopes, logger)
        _dbg(f"[detect_login_form] 容器 scope 确定: {scope!r}（{(time.perf_counter()-t0)*1000:.0f}ms）")

        # ----- 密码 -----
        t0 = time.perf_counter()
        for pattern in get_password_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                selectors["password"] = f"{scope} >> {pattern}" if scope else pattern
                _dbg(f"[detect_login_form] password ✅ {selectors['password']}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                break
        if not selectors["password"]:
            for pattern in get_password_patterns():
                el = await page.query_selector(pattern)
                if el and await el.is_visible():
                    selectors["password"] = pattern
                    _dbg(f"[detect_login_form] password ✅ (fallback) {pattern}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                    break
        if not selectors["password"]:
            _dbg(f"[detect_login_form] password ✗ 未找到（{(time.perf_counter()-t0)*1000:.0f}ms）")

        # ----- 用户名 -----
        t0 = time.perf_counter()
        for pattern in get_username_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                selectors["username"] = f"{scope} >> {pattern}" if scope else pattern
                _dbg(f"[detect_login_form] username ✅ {selectors['username']}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                break
        if not selectors["username"]:
            for pattern in get_username_patterns():
                el = await page.query_selector(pattern)
                if el and await el.is_visible():
                    selectors["username"] = pattern
                    _dbg(f"[detect_login_form] username ✅ (fallback) {pattern}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                    break
        if not selectors["username"]:
            _dbg(f"[detect_login_form] username ✗ 未找到（{(time.perf_counter()-t0)*1000:.0f}ms）")

        # ----- 验证码输入框 -----
        t0 = time.perf_counter()
        for pattern in get_captcha_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                if selectors["username"] and (
                    pattern == selectors["username"]
                    or (scope and selectors["username"] == f"{scope} >> {pattern}")
                ):
                    continue
                selectors["captcha"] = f"{scope} >> {pattern}" if scope else pattern
                _dbg(f"[detect_login_form] captcha ✅ {selectors['captcha']}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                break
        if not selectors["captcha"]:
            for pattern in get_captcha_patterns():
                el = await page.query_selector(pattern)
                if el and await el.is_visible():
                    if selectors["username"] and pattern == selectors["username"]:
                        continue
                    selectors["captcha"] = pattern
                    _dbg(f"[detect_login_form] captcha ✅ (fallback) {pattern}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                    break
        if not selectors["captcha"]:
            _dbg(f"[detect_login_form] captcha ✗ 未找到（{(time.perf_counter()-t0)*1000:.0f}ms）")

        # ----- 提交按钮 -----
        t0 = time.perf_counter()
        for pattern in get_submit_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                selectors["submit"] = f"{scope} >> {pattern}" if scope else pattern
                _dbg(f"[detect_login_form] submit ✅ {selectors['submit']}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                break
        if not selectors["submit"]:
            for pattern in get_submit_patterns():
                el = await page.query_selector(pattern)
                if el and await el.is_visible():
                    selectors["submit"] = pattern
                    _dbg(f"[detect_login_form] submit ✅ (fallback) {pattern}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                    break
        if not selectors["submit"]:
            _dbg(f"[detect_login_form] submit ✗ 未找到（{(time.perf_counter()-t0)*1000:.0f}ms）")

        # ----- 验证码图片 -----
        t0 = time.perf_counter()
        for pattern in get_captcha_image_patterns():
            el = await _query_in_scope(page, scope, pattern)
            if el:
                selectors["captcha_image"] = f"{scope} >> {pattern}" if scope else pattern
                _dbg(f"[detect_login_form] captcha_image ✅ {selectors['captcha_image']}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                break
        if not selectors["captcha_image"]:
            for pattern in get_captcha_image_patterns():
                el = await page.query_selector(pattern)
                if el and await el.is_visible():
                    selectors["captcha_image"] = pattern
                    _dbg(f"[detect_login_form] captcha_image ✅ (fallback) {pattern}（{(time.perf_counter()-t0)*1000:.0f}ms）")
                    break
        if not selectors["captcha_image"]:
            _dbg(f"[detect_login_form] captcha_image ✗ 未找到（{(time.perf_counter()-t0)*1000:.0f}ms）")

        _dbg(f"[detect_login_form] 完成，总耗时 {(time.perf_counter()-t_total)*1000:.0f}ms，结果: {selectors}")
        return selectors

    except Exception as e:
        logger.error(f"Error detecting login form: {e}")
        return selectors
