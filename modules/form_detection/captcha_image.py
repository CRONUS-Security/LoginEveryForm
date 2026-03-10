"""
验证码图片元素 CSS 选择器（用于截图识别验证码）。
在 get_captcha_image 中按顺序尝试。
可在此文件中增删、调整顺序以适配不同站点。
"""
CAPTCHA_IMAGE_PATTERNS = [
    "img[src*='captcha']",
    "img[src*='code']",
    "img[src*='verify']",
    "img[alt*='验证码']",
    "img[alt*='captcha']",
    "#captcha-image",
    ".captcha-image",
]
