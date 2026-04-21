# [FILE: bot/helpers/spotify/handler.py]

import os
import hashlib
import asyncio
from bot.logger import LOGGER
from bot.settings import bot_set
from config import Config
from bot.helpers.uploder import track_upload
from bot.helpers.utils import progress_message

# Import Enums dari folder utils OrpheusDL
from utils.models import QualityEnum, CodecOptions, CodecEnum
from .manager import spotify_manager

async def start_spotify(link: str, user: dict):
    user_id = user['user_id']
    bot_msg = user.get('bot_msg')
    
    module = spotify_manager.session
    if not module:
        raise Exception("Mesin Spotify belum siap. Pastikan login berhasil di /login_spotify.")

    user['radar_msg'] = bot_msg 
    quality_pref = bot_set.user_data.get(user_id, {}).get("spotify_qual", "VERY_HIGH")

    await bot_msg.edit_text("🔍 **Spotify: Mengambil Metadata...**")

    if "track" in link:
        await process_spotify_track(link, user, module, quality_pref)
    else:
        raise Exception("Saat ini baru mendukung tautan Track tunggal.")

async def process_spotify_track(link: str, user: dict, module, quality: str):
    bot_msg = user['bot_msg']
    track_id = link.split('/')[-1].split('?')[0]
    
    # 1. Map string kualitas user ke QualityEnum OrpheusDL
    # 'FLAC' di bot Anda dipetakan ke LOSSLESS di Orpheus
    if quality == "FLAC":
        target_quality = QualityEnum.LOSSLESS
        target_codec = CodecEnum.FLAC
    else:
        target_quality = QualityEnum.HIGH # VERY_HIGH (320kbps)
        target_codec = CodecEnum.VORBIS

    # 2. Buat objek CodecOptions (Dibutuhkan oleh get_track_info)
    codec_opts = CodecOptions(
        codec=target_codec,
        allow_multichannel=False
    )

    # 3. Ambil Metadata dengan argumen lengkap
    try:
        meta = await asyncio.to_thread(
            module.get_track_info, 
            track_id, 
            target_quality, # Argumen ke-2: quality_tier
            codec_opts      # Argumen ke-3: codec_options
        )
    except Exception as e:
        LOGGER.error(f"Metadata Error: {e}")
        raise Exception(f"Gagal mengambil metadata: {e}")

    dl_dir = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']), "Spotify")
    os.makedirs(dl_dir, exist_ok=True)
    
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

    # 4. Proses Unduh (Pastikan argumen sinkron dengan get_track_download)
    try:
        await asyncio.to_thread(module.get_track_download, track_id, target_quality, output_path)
    except Exception as e:
        raise Exception(f"Gagal mengunduh/dekripsi: {e}")

    if not os.path.exists(output_path):
        raise FileNotFoundError("Berkas tidak ditemukan.")

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

    await track_upload(upload_meta, user)
