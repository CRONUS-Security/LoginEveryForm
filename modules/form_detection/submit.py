"""
提交按钮 CSS 选择器（登录/登 录/Sign in 等）。
可在此文件中增删、调整顺序以适配不同站点。
"""
SUBMIT_PATTERNS = [
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
