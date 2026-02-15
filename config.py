# [GANTI FILE: config.py]

import os
import logging
import sys
from os import getenv
from dotenv import load_dotenv

if not os.environ.get("ENV"):
    load_dotenv('.env', override=True)

class Config:
#--------------------

# MAIN BOT VARIABLES

#--------------------
    try:
        TG_BOT_TOKEN = getenv("TG_BOT_TOKEN")
        APP_ID = int(getenv("APP_ID"))
        API_HASH = getenv("API_HASH")
        DATABASE_URL = getenv("DATABASE_URL")
        BOT_USERNAME = getenv("BOT_USERNAME").lstrip("@")
        ADMINS = set(int(x) for x in getenv("ADMINS").split())
        PORT = getenv("PORT", "0")
        if PORT.isdigit():
            PORT = int(PORT)
    except Exception as e:
        logging.warning(f"BOT : Essential Configs are missing -> {e}")
        sys.exit(1)


#--------------------

# BOT WORKING DIRECTORY

#--------------------
    WORK_DIR = getenv("WORK_DIR", "./bot/")
    DOWNLOADS_FOLDER = getenv("DOWNLOADS_FOLDER", "DOWNLOADS")
    DOWNLOAD_BASE_DIR = WORK_DIR + DOWNLOADS_FOLDER
    LOCAL_STORAGE = getenv("DOWNLOAD_BASE_DIR", DOWNLOAD_BASE_DIR) 
#--------------------

# FILE/FOLDER NAMING

#--------------------
    PLAYLIST_NAME_FORMAT = getenv("PLAYLIST_NAME_FORMAT", "{title} - Playlist")
    TRACK_NAME_FORMAT = getenv("TRACK_NAME_FORMAT", "{title} - {artist}")
#--------------------

# RCLONE / INDEX

#--------------------
    RCLONE_CONFIG = getenv("RCLONE_CONFIG", None)
    RCLONE_DEST = getenv("RCLONE_DEST", 'remote:newfolder')
    INDEX_LINK = getenv('INDEX_LINK', None)
#--------------------

# QOBUZ
#--------------------
    
    QOBUZ_ACCOUNTS = []
    i = 1
    while True:
        user_id = getenv(f"QOBUZ_USER_{i}")
        user_token = getenv(f"QOBUZ_TOKEN_{i}")
        email = getenv(f"QOBUZ_EMAIL_{i}")
        password = getenv(f"QOBUZ_PASSWORD_{i}")
        account_data = {}
        if user_id and user_token:
            logging.info(f"Ditemukan Qobuz Akun #{i} (User/Token)")
            account_data = {"user_id": user_id, "user_token": user_token}
        elif email and password:
            logging.info(f"Ditemukan Qobuz Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password}
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Qobuz.")
            break
        
        account_data["id"] = i
        QOBUZ_ACCOUNTS.append(account_data)
        i += 1
    
    if not QOBUZ_ACCOUNTS:
        logging.warning("Tidak ada kredensial Qobuz (QOBUZ_USER_1, dll.) ditemukan di .env")

#--------------------

# DEEZER

#--------------------
    
    DEEZER_BF_SECRET = getenv("DEEZER_BF_SECRET", None)
    
    DEEZER_ACCOUNTS = []
    i = 1
    while True:
        arl = getenv(f"DEEZER_ARL_{i}")
        
        if arl:
            logging.info(f"Ditemukan Deezer Akun #{i} (ARL)")
            account_data = {"arl": arl, "id": i}
            DEEZER_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Deezer.")
            break

    if not DEEZER_ACCOUNTS:
        logging.warning("Tidak ada kredensial Deezer (DEEZER_ARL_1, dll.) ditemukan di .env")

#--------------------

# TIDAL
#--------------------
    ENABLE_TIDAL = getenv("ENABLE_TIDAL", None)
    TIDAL_MOBILE = getenv("TIDAL_MOBILE", None) 
    TIDAL_MOBILE_TOKEN = getenv("TIDAL_MOBILE_TOKEN", None)
    TIDAL_ATMOS_MOBILE_TOKEN = getenv("TIDAL_ATMOS_MOBILE_TOKEN", None)
    TIDAL_TV_TOKEN = getenv("TIDAL_TV_TOKEN", None)
    TIDAL_TV_SECRET = getenv("TIDAL_TV_SECRET", None)
    
    # --- PERBAIKAN: Baca boolean dari .env sebagai string "ON" / "OFF" ---
    _convert_m4a_raw = getenv("TIDAL_CONVERT_M4A", "FALSE").upper()
    TIDAL_CONVERT_M4A = "ON" if _convert_m4a_raw in ["TRUE", "1", "Y", "YES", "ON"] else "OFF"

    _fix_mqa_raw = getenv("TIDAL_FIX_MQA", "TRUE").upper()
    TIDAL_FIX_MQA = "ON" if _fix_mqa_raw in ["TRUE", "1", "Y", "YES", "ON"] else "OFF"
    # --- AKHIR PERBAIKAN ---
#--------------------    

# BEATPORT
#--------------------
    BEATPORT_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"BEATPORT_EMAIL_{i}")
        password = getenv(f"BEATPORT_PASSWORD_{i}")
        proxy = getenv(f"BEATPORT_PROXY_{i}") # Format: socks5h://user:pass@host:port
        
        if email and password:
            logging.info(f"Ditemukan Beatport Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password, "id": i}
            
            # --- LOGIKA PROXY ---
            if proxy:
                logging.info(f" -> Proxy ditemukan untuk Beatport #{i}")
                account_data["proxy"] = proxy
            # --------------------

            BEATPORT_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Beatport.")
            break

    if not BEATPORT_ACCOUNTS:
        logging.warning("Tidak ada kredensial Beatport (BEATPORT_EMAIL_1, dll.) ditemukan di .env")
#--------------------    

# BEATSOURCE
#--------------------
    BEATSOURCE_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"BEATSOURCE_EMAIL_{i}")
        password = getenv(f"BEATSOURCE_PASSWORD_{i}")
        proxy = getenv(f"BEATSOURCE_PROXY_{i}") # Format: socks5h://user:pass@host:port
        
        if email and password:
            logging.info(f"Ditemukan Beatsource Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password, "id": i}
            
            # --- LOGIKA PROXY ---
            if proxy:
                logging.info(f" -> Proxy ditemukan untuk Beatsource #{i}")
                account_data["proxy"] = proxy
            # --------------------

            BEATSOURCE_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Beatsource.")
            break

    if not BEATSOURCE_ACCOUNTS:
        logging.warning("Tidak ada kredensial Beatsource (BEATSOURCE_EMAIL_1, dll.) ditemukan di .env")
#--------------------

# --- TAMBAHAN BARU: Blok Soundcloud ---
#--------------------    
# SOUNDCLOUD
#--------------------
    # Ini adalah 'client_id' atau 'access_token' dari API v2
    SOUNDCLOUD_ACCESS_TOKEN = getenv("SOUNDCLOUD_ACCESS_TOKEN", None)
    if not SOUNDCLOUD_ACCESS_TOKEN:
        logging.warning("SOUNDCLOUD_ACCESS_TOKEN tidak diatur di .env! Modul Soundcloud akan gagal.")
#--------------------
# --- BATAS TAMBAHAN ---

#--------------------    
# KKBOX
#--------------------
    KKBOX_KC1_KEY = getenv("KKBOX_KC1_KEY", None)
    KKBOX_SECRET_KEY = getenv("KKBOX_SECRET_KEY", None)
    
    KKBOX_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"KKBOX_EMAIL_{i}")
        password = getenv(f"KKBOX_PASSWORD_{i}")
        proxy = getenv(f"KKBOX_PROXY_{i}", None) 
        
        if email and password:
            logging.info(f"Ditemukan KKBox Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password, "id": i}
            
            if proxy:
                logging.info(f" -> Ditemukan Proxy untuk Akun KKBox #{i}.")
                account_data["proxy"] = proxy
            
            KKBOX_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun KKBox.")
            break

    if not KKBOX_ACCOUNTS:
        logging.warning("Tidak ada kredensial KKBox (KKBOX_EMAIL_1, dll.) ditemukan di .env")
    if not KKBOX_KC1_KEY or not KKBOX_SECRET_KEY:
        logging.warning("KKBOX_KC1_KEY atau KKBOX_SECRET_KEY tidak diatur! Modul KKBox akan gagal.")
#-------------------- 

# --- TAMBAHAN BARU: Blok Napster ---
#--------------------    
# NAPSTER
#--------------------
    NAPSTER_API_KEY = getenv("NAPSTER_API_KEY", None)
    NAPSTER_CUSTOMER_SECRET = getenv("NAPSTER_CUSTOMER_SECRET", None)
    
    NAPSTER_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"NAPSTER_EMAIL_{i}")
        password = getenv(f"NAPSTER_PASSWORD_{i}")
        
        if email and password:
            logging.info(f"Ditemukan Napster Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password, "id": i}
            NAPSTER_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Napster.")
            break

    if not NAPSTER_ACCOUNTS:
        logging.warning("Tidak ada kredensial Napster (NAPSTER_EMAIL_1, dll.) ditemukan di .env")
    if not NAPSTER_API_KEY or not NAPSTER_CUSTOMER_SECRET:
        logging.warning("NAPSTER_API_KEY atau NAPSTER_CUSTOMER_SECRET tidak diatur! Modul Napster akan gagal.")
#-------------------- 
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Blok Idagio ---
#--------------------    
# IDAGIO
#--------------------
    IDAGIO_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"IDAGIO_EMAIL_{i}")
        password = getenv(f"IDAGIO_PASSWORD_{i}")
        
        if email and password:
            logging.info(f"Ditemukan Idagio Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password, "id": i}
            IDAGIO_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Idagio.")
            break

    if not IDAGIO_ACCOUNTS:
        logging.warning("Tidak ada kredensial Idagio (IDAGIO_EMAIL_1, dll.) ditemukan di .env")
#-------------------- 
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Blok Nugs.net ---
#--------------------    
# NUGS.NET
#--------------------
    NUGS_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"NUGS_EMAIL_{i}")
        password = getenv(f"NUGS_PASSWORD_{i}")
        
        if email and password:
            logging.info(f"Ditemukan Nugs.net Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password, "id": i}
            NUGS_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Nugs.net.")
            break

    if not NUGS_ACCOUNTS:
        logging.warning("Tidak ada kredensial Nugs.net (NUGS_EMAIL_1, dll.) ditemukan di .env")
#-------------------- 
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Blok Bugs ---
#--------------------    
# BUGS
#--------------------
    BUGS_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"BUGS_EMAIL_{i}")
        password = getenv(f"BUGS_PASSWORD_{i}")
        
        if email and password:
            logging.info(f"Ditemukan Bugs Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password, "id": i}
            BUGS_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Bugs.")
            break

    if not BUGS_ACCOUNTS:
        logging.warning("Tidak ada kredensial Bugs (BUGS_EMAIL_1, dll.) ditemukan di .env")
#-------------------- 
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Blok HIGHRESAUDIO ---
#--------------------    
# HIGHRESAUDIO
#--------------------
    HIGHRESAUDIO_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"HIGHRESAUDIO_EMAIL_{i}")
        password = getenv(f"HIGHRESAUDIO_PASSWORD_{i}")
        proxy = getenv(f"HIGHRESAUDIO_PROXY_{i}") # Format: http://user:pass@host:port atau socks5://...
        
        if email and password:
            logging.info(f"Ditemukan HIGHRESAUDIO Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password, "id": i}
            
            # --- LOGIKA PROXY ---
            if proxy:
                logging.info(f" -> Proxy ditemukan untuk HIGHRESAUDIO #{i}")
                account_data["proxy"] = proxy
            # --------------------

            HIGHRESAUDIO_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun HIGHRESAUDIO.")
            break

    if not HIGHRESAUDIO_ACCOUNTS:
        logging.warning("Tidak ada kredensial HIGHRESAUDIO (HIGHRESAUDIO_EMAIL_1, dll.) ditemukan di .env")
#-------------------- 
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Blok Moov ---
#--------------------    
# MOOV
#--------------------
    MOOV_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"MOOV_EMAIL_{i}")
        password = getenv(f"MOOV_PASSWORD_{i}")
        proxy = getenv(f"MOOV_PROXY_{i}") # Format: http://user:pass@host:port
        
        if email and password and proxy:
            logging.info(f"Ditemukan Moov Akun #{i} (Email/Pass/Proxy)")
            account_data = {"email": email, "password": password, "proxy": proxy, "id": i}
            MOOV_ACCOUNTS.append(account_data)
            i += 1
        else:
            if i > 1:
                 logging.info(f"Selesai memuat {i-1} akun Moov.")
            break

    if not MOOV_ACCOUNTS:
        logging.warning("Tidak ada kredensial Moov (MOOV_EMAIL_1, dll.) ditemukan di .env")
#--------------------
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Blok LivePhish ---
#--------------------    
# LIVEPHISH
#--------------------
    LIVEPHISH_ACCOUNTS = []
    i = 1
    while True:
        email = getenv(f"LIVEPHISH_EMAIL_{i}")
        password = getenv(f"LIVEPHISH_PASSWORD_{i}")
        
        if email and password:
            logging.info(f"Ditemukan LivePhish Akun #{i}")
            account_data = {"email": email, "password": password, "id": i}
            LIVEPHISH_ACCOUNTS.append(account_data)
            i += 1
        else:
            break
    
    if not LIVEPHISH_ACCOUNTS:
        logging.warning("Tidak ada kredensial LivePhish di .env")
#--------------------
# --- BATAS TAMBAHAN ---

#--------------------
# SPOTIFY
#--------------------
    # Default Client ID ini adalah ID umum, tapi disarankan pakai punya sendiri
    # Daftar di developer.spotify.com
    SPOTIFY_CLIENT_ID = getenv("SPOTIFY_CLIENT_ID", "65b708073fc0480ea92a077233ca87bd")
    SPOTIFY_CLIENT_SECRET = getenv("SPOTIFY_CLIENT_SECRET", "")
    
    # Variabel ini akan menyimpan JSON Token Login agar tidak hilang saat Restart di Render
    SPOTIFY_CREDENTIALS_JSON = getenv("SPOTIFY_CREDENTIALS_JSON", None)
#--------------------
# --- BATAS TAMBAHAN ---

#--------------------
# RENDER MANAGEMENT
#--------------------
    # API Key dari Dashboard Render -> Account Settings -> API Keys
    RENDER_API_KEY = getenv("RENDER_API_KEY", None)
#--------------------
# --- BATAS TAMBAHAN ---
    
# CONCURRENT
#--------------------
    MAX_WORKERS = int(getenv("MAX_WORKERS", "100"))
