"""
用户名/账号输入框 CSS 选择器。
优先 autocomplete、name、id、placeholder，并排除验证码类控件。
可在此文件中增删、调整顺序以适配不同站点（如 TrueNAS 等）。
"""
USERNAME_PATTERNS = [
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
    # 排除验证码类，避免把验证码当用户名
    "input[type='text']:not([name*='captcha']):not([name*='code']):not([name*='verify']):not([id*='captcha']):not([id*='code']):not([id*='verify'])",
]
