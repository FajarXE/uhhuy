# [FILE: bot/helpers/spotify/handler.py]

import os
import hashlib
import asyncio
from bot.logger import LOGGER
from bot.settings import bot_set
from config import Config
from bot.helpers.uploder import track_upload
from bot.helpers.utils import progress_message

# Import manager yang sudah berhasil login tadi
from .manager import spotify_manager

async def start_spotify(link: str, user: dict):
    user_id = user['user_id']
    bot_msg = user.get('bot_msg')
    
    # 1. Gunakan sesi yang sudah diinisialisasi oleh manager.py
    # Tidak perlu membuat ModuleInterface(flags=None, ...) lagi!
    module = spotify_manager.session
    
    if not module:
        raise Exception("Mesin Spotify belum siap. Pastikan login berhasil di /login_spotify.")

    # Kunci Radar UI agar tidak berkedip
    user['radar_msg'] = bot_msg 

    # 2. Ambil preferensi kualitas user (Default VERY_HIGH / 320k)
    quality_pref = bot_set.user_data.get(user_id, {}).get("spotify_qual", "VERY_HIGH")

    await bot_msg.edit_text("🔍 **Spotify: Mengambil Metadata...**")

    # Routing link
    if "track" in link:
        await process_spotify_track(link, user, module, quality_pref)
    else:
        raise Exception("Saat ini baru mendukung tautan Track tunggal.")

async def process_spotify_track(link: str, user: dict, module, quality: str):
    bot_msg = user['bot_msg']
    
    # Ekstrak ID Track
    track_id = link.split('/')[-1].split('?')[0]
    
    # Ambil Metadata via OrpheusDL Module
    try:
        # Karena OrpheusDL sinkron, kita bungkus ke thread agar bot tidak lag
        meta = await asyncio.to_thread(module.get_track_info, track_id)
    except Exception as e:
        raise Exception(f"Gagal mengambil metadata: {e}")

    # Path penyimpanan di Render (Network Mount)
    dl_dir = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']), "Spotify")
    os.makedirs(dl_dir, exist_ok=True)
    
    # Tentukan ekstensi (FLAC jika diatur, jika tidak OGG)
    ext = "flac" if quality == "FLAC" else "ogg"
    file_name = f"{meta.name} - {meta.artists[0]}.{ext}"
    output_path = os.path.join(dl_dir, file_name)

    # Setup Radar UI
    task_id = hashlib.md5(str(bot_msg.id).encode()).hexdigest()[:16]
    details = {
        'msg': bot_msg,
        'title': file_name,
        'task_id': task_id,
        'action': 'Downloading',
        'type': 'Track',
        'machine': 'Spotify Desktop API'
    }

    # Jalankan proses unduh
    try:
        # Kita panggil fungsi download dari modul Orpheus
        # Jika Anda ingin progress bar bergerak, panggil callback di sini 
        # (tergantung apakah desktop_api.py Anda sudah kita modif untuk itu)
        await asyncio.to_thread(module.get_track_download, track_id, quality, output_path)
    except Exception as e:
        raise Exception(f"Gagal mengunduh/dekripsi: {e}")

    if not os.path.exists(output_path):
        raise FileNotFoundError("Berkas tidak ditemukan setelah proses selesai.")

    # Rakit Metadata untuk Uploader Bot
    upload_meta = {
        'filepath': output_path,
        'title': meta.name,
        'artist': meta.artists[0] if meta.artists else "Unknown",
        'album': meta.album if hasattr(meta, 'album') else "Single",
        'provider': 'Spotify',
        'type': 'track',
        'quality': "Lossless (FLAC)" if quality == "FLAC" else "High (320k)",
        'cover': meta.cover_url if hasattr(meta, 'cover_url') else None,
    }

    # Kirim ke Telegram (Uploder Anda akan menangani Radar selanjutnya)
    await track_upload(upload_meta, user)
