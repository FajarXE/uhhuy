# [FILE: bot/helpers/spotify/handler.py]

import os
import hashlib
import asyncio
from bot.logger import LOGGER
from bot.settings import bot_set
from config import Config
from bot.helpers.uploder import track_upload
from bot.helpers.utils import progress_message

# Asumsi Anda menggunakan interface.py dari OrpheusDL sebagai jembatan utamanya
# Pastikan dependencies OrpheusDL (folder utils) juga tersedia agar import ini tidak gagal.
from .interface import ModuleInterface

async def start_spotify(link: str, user: dict):
    user_id = user['user_id']
    bot_msg = user.get('bot_msg')
    
    # 1. Kunci Radar UI agar permanen selama transisi ke uploader
    user['radar_msg'] = bot_msg 

    # 2. Setup Preferensi Kualitas (FLAC atau Ogg)
    # Jika tidak ada pengaturan, gunakan VERY_HIGH (Ogg 320k) sebagai fallback aman
    quality_pref = bot_set.user_data.get(user_id, {}).get("spotify_qual", "VERY_HIGH")

    await bot_msg.edit_text("🔍 **Spotify: Menghubungi Desktop API...**")

    # Inisialisasi modul (Anda mungkin perlu menyesuaikan argumen sesuai struktur interface.py Anda)
    try:
        spotify_module = ModuleInterface(flags=None, module_settings={})
    except Exception as e:
        LOGGER.error(f"Gagal memuat Spotify Module: {e}")
        raise Exception("Mesin Spotify tidak dapat dimuat. Cek logs.")

    if "track" in link:
        await process_spotify_track(link, user, spotify_module, quality_pref)
    else:
        raise Exception("Saat ini handler baru mendukung tautan Track tunggal.")

async def process_spotify_track(link: str, user: dict, module, quality: str):
    bot_msg = user['bot_msg']
    
    # Ekstrak ID Track dari URL
    track_id = link.split('/')[-1].split('?')[0]
    
    # Ambil Metadata (Fungsi ini harus sinkron/asinkron tergantung interface.py)
    # Kita bungkus dengan to_thread jika fungsi bawaan OrpheusDL memblokir (synchronous)
    try:
        meta = await asyncio.to_thread(module.get_track_info, track_id)
    except Exception as e:
        raise Exception(f"Gagal mengambil metadata Spotify: {e}")

    # Siapkan folder unduhan di penyimpanan lokal (akan diarahkan ke mount point Render)
    dl_dir = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']), "Spotify")
    os.makedirs(dl_dir, exist_ok=True)
    
    # Tentukan ekstensi berdasarkan preferensi
    ext = "flac" if quality == "FLAC" else "ogg"
    file_name = f"{meta.name} - {meta.artists[0]}.{ext}"
    output_path = os.path.join(dl_dir, file_name)

    # Setup Radar UI Permanen
    task_id = hashlib.md5(str(bot_msg.id).encode()).hexdigest()[:16]
    details = {
        'msg': bot_msg,
        'title': file_name,
        'task_id': task_id,
        'action': 'Decrypting',
        'type': 'Track',
        'machine': 'Spotify Protobuf'
    }

    # Callback untuk Radar UI
    async def ui_callback(current, total):
        await progress_message(current, total, details)

    # Proses Unduh & Dekripsi
    try:
        # Panggil fungsi unduh dari modul. Anda perlu memodifikasi sedikit fungsi di dalam 
        # desktop_api.py atau interface.py milik OrpheusDL agar menerima argumen `progress_callback`
        # untuk memicu ui_callback di atas setiap kali chunk file ditulis.
        await asyncio.to_thread(module.get_track_download, track_id, quality, output_path)
    except Exception as e:
        raise Exception(f"Gagal mendekripsi trek: {e}")

    if not os.path.exists(output_path):
        raise FileNotFoundError("Berkas hasil dekripsi tidak ditemukan di penyimpanan.")

    # Rakit Metadata untuk Uploader Bot Anda
    upload_meta = {
        'filepath': output_path,
        'title': meta.name,
        'artist': meta.artists[0] if meta.artists else "Unknown",
        'album': meta.album if hasattr(meta, 'album') else "Single",
        'provider': 'Spotify',
        'type': 'track',
        'quality': "Lossless (FLAC)" if quality == "FLAC" else "High (Ogg 320k)",
        'cover': meta.cover_url if hasattr(meta, 'cover_url') else None,
    }

    # Lempar ke modul upload (transisi akan mulus karena user['radar_msg'] sudah dikunci)
    await track_upload(upload_meta, user)
