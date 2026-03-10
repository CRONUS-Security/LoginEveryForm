"""
密码框 CSS 选择器。
按顺序尝试，先在本页或 container scope 内匹配。
可在此文件中增删、调整顺序以适配不同站点。
"""
PASSWORD_PATTERNS = [
    "input[type='password']",
    "input[autocomplete='current-password']",
    "input[name*='password']",
    "input[name*='passwd']",
    "input[id*='password']",
    "input[id*='passwd']",
    "input[placeholder*='密码']",
    "input[placeholder*='password']",
]
