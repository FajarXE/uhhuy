# [FILE: bot/settings.py]

import os
import json
import base64
import requests
import asyncio
import logging

import bot.helpers.translations as lang

from config import Config
from bot.logger import LOGGER

from .helpers.database.mongo_async import database
from .helpers.translations import lang_available
from .helpers.tidal.manager import tidal_manager

def __encrypt_string__(string):
    s = bytes(string, 'utf-8')
    s = base64.b64encode(s)
    return s

def __decrypt_string__(string):
    try:
        s = base64.b64decode(string)
        s = s.decode()
        return s
    except:
        return string

# --- [FIX] PENGHAPUSAN EVENT LOOP GLOBAL ---
# Baris loop = asyncio.new_event_loop() dihapus dari sini.
# Kueri database dipindahkan ke dalam set_language() agar berjalan di loop yang benar.
# -------------------------------------------

class BotSettings:
    def __init__(self):
        self.deezer = False
        self.admins = Config.ADMINS
        
        # Inisialisasi atribut dengan nilai kosong/default
        self.set_db = {}
        self.bot_lang = None
        self.auth_users = []
        self.auth_chats = []
        self.rclone = False
        self.anti_spam = "OFF"
        self.bot_public = None
        self.art_poster = None
        self.playlist_sort = None
        self.disable_sort_link = None
        self.artist_batch = None
        self.playlist_conc = None
        self.link_options = 'False'
        self.album_zip = None
        self.playlist_zip = None
        self.artist_zip = None
        self.upload_mode = 'Telegram'
        self.user_data = {}
        self.can_enable_tidal = Config.ENABLE_TIDAL

    def check_upload_mode(self):
        if os.path.exists('rclone.conf'):
            self.rclone = True
        elif Config.RCLONE_CONFIG:
            if Config.RCLONE_CONFIG.startswith('http'):
                rclone = requests.get(Config.RCLONE_CONFIG, allow_redirects=True)
                if rclone.status_code != 200:
                    LOGGER.info("RCLONE : Error retreiving file from Config URL")
                    self.rclone = False
                else:
                    with open('rclone.conf', 'wb') as f:
                        f.write(rclone.content)
                    self.rclone = True
            
        db_upload = self.set_db.get('UPLOAD_MODE')
        if self.rclone and db_upload == 'RCLONE':
            self.upload_mode = 'RCLONE'
        elif db_upload == 'Telegram' or db_upload == 'Local':
            self.upload_mode = db_upload
        else:
            self.upload_mode = 'Telegram'
            
        link_option = self.set_db.get('RCLONE_LINK_OPTIONS')
        self.link_options = link_option if self.rclone and link_option else 'False'
    
    async def set_language(self):
        # --- [FIX] AMBIL DATA DATABASE DI SINI ---
        # Karena ini dieksekusi di start_services(), uvloop sudah pasti aktif!
        self.set_db = await database.get_variable()
        
        # Isi semua pengaturan yang sebelumnya ada di __init__
        self.auth_users = self.set_db.get('AUTH_USERS', [])
        self.auth_chats = self.set_db.get('AUTH_CHATS', [])
        self.anti_spam = self.set_db.get('ANTI_SPAM', "OFF")
        self.bot_public = self.set_db.get('BOT_PUBLIC')
        self.art_poster = self.set_db.get('ART_POSTER')
        self.playlist_sort = self.set_db.get('PLAYLIST_SORT')
        self.disable_sort_link = self.set_db.get('PLAYLIST_LINK_DISABLE')
        self.artist_batch = self.set_db.get('ARTIST_BATCH_UPLOAD')
        self.playlist_conc = self.set_db.get('PLAYLIST_CONCURRENT')
        self.album_zip = self.set_db.get('ALBUM_ZIP')
        self.playlist_zip = self.set_db.get('PLAYLIST_ZIP')
        self.artist_zip = self.set_db.get('ARTIST_ZIP')
        
        # Eksekusi pengecekan mode upload setelah set_db terisi
        self.check_upload_mode()
        # -----------------------------------------

        self.bot_lang = self.set_db.get("BOT_LANGUAGE", "en")
        for item in lang_available:
            logging.info(item.__language__ == self.bot_lang)
            if item.__language__ == self.bot_lang:
                lang.s = item
                break

    async def initialize_users(self) -> dict:
        user_data = await database.initialize_users()
        
        if tidal_manager and tidal_manager.clients:
            tidal_manager.user_data = user_data
            
        self.user_data = user_data

bot_set = BotSettings()
