"""
Logging System Module
Using rich + logging for comprehensive logging
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table


class SecurityLogger:
    """Enhanced logging system for security operations"""

    def __init__(self, log_dir: str = "logs", log_level: int = logging.DEBUG):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # Initialize Rich console
        self.console = Console()

        # Create logger
        self.logger = logging.getLogger("LoginEveryForm")
        self.logger.setLevel(log_level)

        # Remove existing handlers
        self.logger.handlers.clear()

        # Create log filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"security_verification_{timestamp}.log"

        # File handler (detailed logs)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)

        # Rich console handler (formatted console output)
        console_handler = RichHandler(
            console=self.console,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            markup=True
        )
        console_handler.setLevel(logging.INFO)

        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        # Log initialization
        self.logger.info(f"Logging system initialized. Log file: {log_file}")

    def info(self, message: str, **kwargs):
        """Log info message"""
        self.logger.info(message, **kwargs)

    def debug(self, message: str, **kwargs):
        """Log debug message"""
        self.logger.debug(message, **kwargs)

    def warning(self, message: str, **kwargs):
        """Log warning message"""
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs):
        """Log error message"""
        self.logger.error(message, **kwargs)

    def critical(self, message: str, **kwargs):
        """Log critical message"""
        self.logger.critical(message, **kwargs)

    def success(self, message: str):
        """Log success message with rich formatting"""
        self.logger.info(message)
        self.console.print(f"[bold green]✓[/bold green] {message}")

    def failed(self, message: str):
        """Log failure message with rich formatting"""
        self.logger.error(message)
        self.console.print(f"[bold red]✗[/bold red] {message}")

    def section(self, title: str):
        """Print a section header"""
        self.console.print(f"\n[bold cyan]{'=' * 60}[/bold cyan]")
        self.console.print(f"[bold cyan]{title:^60}[/bold cyan]")
        self.console.print(f"[bold cyan]{'=' * 60}[/bold cyan]\n")
        self.logger.info(f"=== {title} ===")

    def panel(self, content: str, title: str = "", style: str = "cyan"):
        """Display content in a rich panel"""
        self.console.print(Panel(content, title=title, border_style=style))

    def table(self, title: str, columns: list, rows: list):
        """Display data in a rich table"""
        table = Table(title=title, show_header=True, header_style="bold magenta")

        for column in columns:
            table.add_column(column)

        for row in rows:
            table.add_row(*[str(cell) for cell in row])

        self.console.print(table)

    def progress_info(self, current: int, total: int, message: str):
        """Log progress information"""
        percentage = (current / total * 100) if total > 0 else 0
        self.logger.info(f"[{current}/{total}] ({percentage:.1f}%) {message}")
        self.console.print(f"[cyan][[/cyan][yellow]{current}[/yellow][cyan]/[/cyan][yellow]{total}[/yellow][cyan]][/cyan] {message}")

    def credential_attempt(self, url: str, username: str, status: str):
        """Log credential verification attempt"""
        log_msg = f"URL: {url} | Username: {username} | Status: {status}"
        self.logger.info(log_msg)

        status_color = {
            "SUCCESS": "green",
            "FAILED": "red",
            "ERROR": "yellow",
            "CAPTCHA_REQUIRED": "magenta"
        }.get(status, "white")

        self.console.print(f"[{status_color}]● {username}[/{status_color}] @ [dim]{url}[/dim] → [{status_color}]{status}[/{status_color}]")

    def summary(self, total: int, success: int, failed: int, errors: int):
        """Display summary statistics"""
        self.section("Verification Summary")

        summary_table = Table(show_header=True, header_style="bold cyan")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Count", justify="right", style="yellow")
        summary_table.add_column("Percentage", justify="right", style="magenta")

        summary_table.add_row("Total Attempts", str(total), "100%")
        summary_table.add_row("Successful Logins", str(success), f"{success/total*100:.1f}%" if total > 0 else "0%")
        summary_table.add_row("Failed Logins", str(failed), f"{failed/total*100:.1f}%" if total > 0 else "0%")
        summary_table.add_row("Errors", str(errors), f"{errors/total*100:.1f}%" if total > 0 else "0%")

        self.console.print(summary_table)

        self.logger.info(f"Summary: Total={total}, Success={success}, Failed={failed}, Errors={errors}")


# Global logger instance
_logger_instance: Optional[SecurityLogger] = None


def get_logger() -> SecurityLogger:
    """Get the global logger instance"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = SecurityLogger()
    return _logger_instance


def init_logger(log_dir: str = "logs", log_level: int = logging.DEBUG) -> SecurityLogger:
    """Initialize the global logger"""
    global _logger_instance
    _logger_instance = SecurityLogger(log_dir, log_level)
    return _logger_instance
