# [GANTI FILE: bot/__init__.py]

import os
import subprocess
from config import Config

BOT_QOBUZ_CLIENTS = {}

bot = Config.BOT_USERNAME

plugins = dict(
    root="bot/modules"
)

PORT = int(os.getenv("PORT", "0"))
gunicorn_process = None

def start_gunicorn():
    """Menjalankan web server Gunicorn hanya saat layanan utama dimulai dan PORT valid."""
    global gunicorn_process
    if PORT > 0 and gunicorn_process is None:
        gunicorn_process = subprocess.Popen(
            f"exec gunicorn server:app --bind 0.0.0.0:{PORT} --threads 4",
            shell=True
        )
    return gunicorn_process

class CMD(object):
    START = ["start"]
    HELP = ["help"]
    SETTINGS = ["settings"]
    DOWNLOAD = ["dl"]
    BAN = ["ban", "unadd", "unauth"]
    AUTH = ["auth"]
    LOG = ["log"]
    USETTING = ["usetting", "uset"]

cmd = CMD()
