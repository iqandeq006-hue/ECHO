import logging
import logging.handlers
import os

# Use AppData directory for logs (user-writable location)
LOG_DIR = os.path.join(os.getenv('APPDATA'), 'ECHO', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "ECHO.log")

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    if logger.handlers:
        return  # already configured

    logger.setLevel(level)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Rotating file handler
    fh = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.debug(f"Logging initialized. Log file: {LOG_PATH}")