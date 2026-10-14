import os
import logging
import inspect
from logging.handlers import RotatingFileHandler

log_file_path = "./bot/bot_logs.log"

# Config file has logging so removing that handler 
try:
    logging.getLogger().removeHandler(logging.getLogger().handlers[0])
except Exception:
    pass

logging.basicConfig(
    format="[%(levelname)s] - [%(asctime)s] [%(filename)s:%(lineno)d] %(message)s",
    handlers=[
        # [FIX] Batasi ukuran log maksimal 10 MB (dengan 2 file backup) agar disk tidak penuh
        RotatingFileHandler(log_file_path, maxBytes=10 * 1024 * 1024, backupCount=2, encoding="utf-8"),
        logging.StreamHandler()
    ],
    level=logging.INFO,
)

LOGGER = logging.getLogger(__name__)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.ERROR)
