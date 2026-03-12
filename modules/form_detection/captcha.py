"""
验证码输入框 CSS 选择器。
用于识别需要填写验证码的输入框，避免与用户名混淆。
可在此文件中增删、调整顺序以适配不同站点。
"""
CAPTCHA_PATTERNS = [
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
    "input[id*='TextBoxCode']"
]
