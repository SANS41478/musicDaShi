"""musicDaShi — Automatic Music Performance Engine.

Entry point for the desktop application.
"""

import logging
import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import MainWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    """Launch the musicDaShi desktop application."""
    logger.info("Starting musicDaShi...")

    app = QApplication(sys.argv)
    app.setApplicationName("musicDaShi")
    app.setOrganizationName("musicDaShi")

    window = MainWindow()
    window.show()

    logger.info("Application ready")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
