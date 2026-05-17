"""
PyInstaller hook for playwright.

Playwright uses dynamic imports and runtime module loading heavily.
This hook ensures all necessary submodules are collected so the
frozen application can launch browsers correctly.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Collect everything from playwright package
datas, binaries, hiddenimports = collect_all("playwright")

# Explicitly collect all submodules to catch dynamic imports
hiddenimports += collect_submodules("playwright")
hiddenimports += collect_submodules("playwright.async_api")
hiddenimports += collect_submodules("playwright.sync_api")
hiddenimports += [
    "playwright._impl._api_types",
    "playwright._impl._browser",
    "playwright._impl._browser_context",
    "playwright._impl._browser_type",
    "playwright._impl._connection",
    "playwright._impl._element_handle",
    "playwright._impl._errors",
    "playwright._impl._event_context_manager",
    "playwright._impl._frame",
    "playwright._impl._helper",
    "playwright._impl._input",
    "playwright._impl._js_handle",
    "playwright._impl._local_utils",
    "playwright._impl._network",
    "playwright._impl._page",
    "playwright._impl._playwright",
    "playwright._impl._transport",
    "playwright._impl._tracing",
    "playwright._impl._video",
    "playwright._impl._wait_helper",
]
