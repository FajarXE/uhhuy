# --- PERBAIKAN DI SINI ---
# Mendefinisikan dictionary global agar bisa diimpor oleh file lain
BOT_QOBUZ_CLIENTS = {}
# --- BATAS PERBAIKAN ---

from config import Config
import subprocess, os

bot = Config.BOT_USERNAME

plugins = dict(
    root="bot/modules"
)

PORT = int(os.getenv("PORT", "0"))

subprocess.Popen([f"gunicorn server:app --bind 0.0.0.0:{PORT} --worker-class gevent"], shell=True)

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
