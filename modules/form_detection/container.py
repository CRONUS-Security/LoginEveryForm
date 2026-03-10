"""
登录表单容器选择器（用于限定用户名/密码/验证码/提交按钮的查找范围）。
按顺序尝试，返回第一个匹配的 scope；空列表表示不限定 scope，在整页查找。
可在此文件中增删、调整顺序以适配不同站点（如 TrueNAS 等）。
"""
# 优先：带密码框的 form 或常见登录容器，避免匹配到导航栏搜索框等
CONTAINER_SCOPES = [
    "form:has(input[type='password'])",
    "[role='form']:has(input[type='password'])",
    ".login-form:has(input[type='password'])",
    ".login-box:has(input[type='password'])",
    ".auth-form:has(input[type='password'])",
    "#loginForm:has(input[type='password'])",
    "[class*='login']:has(input[type='password'])",
]
