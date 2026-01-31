"""
Configuration Management
"""

from pathlib import Path
from typing import Optional
import modules


class Config:
    """Application configuration"""

    # Application
    APP_NAME = "LoginEveryForm"
    APP_VERSION = modules.__version__
    APP_AUTHOR = modules.__author__

    # Directories
    BASE_DIR = Path(__file__).parent
    LOGS_DIR = BASE_DIR / "logs"
    SCREENSHOTS_DIR = BASE_DIR / "screenshots"
    DATA_DIR = BASE_DIR / "data"

    # Browser Settings
    DEFAULT_BROWSER = "chromium"  # chromium, firefox, webkit
    DEFAULT_HEADLESS = False
    DEFAULT_TIMEOUT = 30000  # milliseconds

    # Login Settings
    DEFAULT_WAIT_AFTER_SUBMIT = 3000  # milliseconds
    DEFAULT_DELAY_BETWEEN_ATTEMPTS = 2000  # milliseconds

    # Excel Settings
    DEFAULT_USERNAME_COLUMN = 0
    DEFAULT_PASSWORD_COLUMN = 1
    DEFAULT_NOTE_COLUMN = 2
    DEFAULT_SKIP_HEADER = True

    # Logging
    LOG_LEVEL = "DEBUG"
    LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"

    # UI Settings
    WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION} - Password Leak Verification Tool"
    WINDOW_WIDTH = 1200
    WINDOW_HEIGHT = 800

    @classmethod
    def ensure_directories(cls):
        """Create necessary directories"""
        cls.LOGS_DIR.mkdir(exist_ok=True)
        cls.SCREENSHOTS_DIR.mkdir(exist_ok=True)
        cls.DATA_DIR.mkdir(exist_ok=True)
