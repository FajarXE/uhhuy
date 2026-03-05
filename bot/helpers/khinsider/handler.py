# [GANTI SELURUH FILE: bot/helpers/khinsider/handler.py]

import os
import aiohttp
import aiofiles
import time
import asyncio
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import ID3, APIC, TYER, TDRC, TPOS, COMM
from mutagen.flac import FLAC, Picture

from ...modules.user_settings import bot_set
from ...helpers.utils import download_file, run_concurrent_tasks, fetch_zip_settings, zip_folder, post_art_poster
from ...helpers.uploder import album_upload
from ...helpers.message import edit_message
from config import Config
from .manager import khinsider_manager
from bot.logger import LOGGER

# --- FUNGSI TAGGING LENGKAP ---
def set_file_tags(filepath, meta, cover_path, fmt):
    """Menanamkan Cover + Metadata (Year, Disc, dll) ke file."""
    if not os.path.exists(filepath):
        return

    try:
        year = meta.get('date', 'N/A')
        if year == 'N/A': year = None
        
        disc_num = meta.get('disc_number', '1')
        total_discs = meta.get('totalvolumes', '1')
        disc_set = f"{disc_num}/{total_discs}"

        if fmt == 'mp3':
            try:
                audio = MP3(filepath, ID3=ID3)
            except:
                audio = MP3(filepath)
                audio.add_tags()
            
            if cover_path and os.path.exists(cover_path):
                audio.tags.delall("APIC")
                with open(cover_path, 'rb') as albumart:
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3, desc=u'Cover',
                        data=albumart.read()
                    ))
            
            if year:
                audio.tags.add(TDRC(encoding=3, text=[str(year)])) 
                audio.tags.add(TYER(encoding=3, text=[str(year)])) 
            
            audio.tags.add(TPOS(encoding=3, text=[disc_set]))
            audio.save()
            
        elif fmt == 'flac':
            audio = FLAC(filepath)
            if cover_path and os.path.exists(cover_path):
                image = Picture()
                image.type = 3
                image.mime = 'image/jpeg'
                image.desc = 'Cover'
                with open(cover_path, 'rb') as f:
                    image.data = f.read()
                audio.clear_pictures()
                audio.add_picture(image)
            
            if year:
                audio['DATE'] = str(year)
                audio['YEAR'] = str(year)
            
            audio['DISCNUMBER'] = str(disc_num)
            audio['TOTALDISCS'] = str(total_discs)
            audio.save()
            
    except Exception as e:
        LOGGER.error(f"Gagal set tags untuk {filepath}: {e}")

# --- HANDLER UTAMA ---
async def start_khinsider(url, user):
    msg = user['bot_msg']
    await edit_message(msg, "⚙️ Memproses Album Khinsider...")
    
    try:
        album_meta = await khinsider_manager.get_album(url)
    except Exception as e:
        await edit_message(msg, f"❌ Gagal mengambil info album: {e}")
        return

    album_folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['title']}"
    os.makedirs(album_folder_path, exist_ok=True)

    cover_path = None
    if album_meta.get('images'):
        await edit_message(msg, f"🖼️ Mengunduh {len(album_meta['images'])} gambar...")
        for i, img_url in enumerate(album_meta['images']):
            try:
                ext = img_url.split('.')[-1].split('?')[0]
                if i == 0:
                    filename = f"cover.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                    cover_path = filepath 
                else:
                    filename = f"artwork_{i}.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                # Download gambar dengan menyamar (Spoofing)
                await download_file(img_url, filepath, details={'msg': None, 'headers': {'User-Agent': khinsider_manager.headers['User-Agent']}})
            except Exception: pass

    track_total = len(album_meta['tracks'])
    
    # --- BUNGKUS DATA ALBUM DI AWAL ---
    album_data = {
        'title': album_meta['title'],
        'artist': 'Game Soundtrack',
        'albumartist': 'Game Soundtrack',
        'type': 'album',
        'provider': 'Khinsider',
        'tracks': [],
        'cover': cover_path,
        'folderpath': album_folder_path,
        'totaltracks': str(track_total),
        'date': album_meta['date'],
        'totalvolumes': album_meta['totalvolumes'],
        'explicit': str(album_meta['explicit']),
        'quality': bot_set.user_data.get(user['user_id'], {}).get('khinsider_qual', 'FLAC').upper()
    }
    
    # --- [FIX UI] KIRIM POSTER DI AWAL SEBELUM DOWNLOAD ---
    try:
        album_data['poster_msg'] = await post_art_poster(user, album_data)
    except Exception as e:
        LOGGER.error(f"Gagal mengirim poster Khinsider: {e}")
    # ------------------------------------------------------

    async def _process_track(track):
        try:
            # 1. Scrape Direct Link
            dl_url, fmt = await khinsider_manager.get_track_download_url(
                track['url'], 
                preferred_formats=[bot_set.user_data.get(user['user_id'], {}).get('khinsider_qual', 'flac'), 'mp3']
            )
            
            if int(album_meta['totalvolumes']) > 1:
                filename = f"{track['disc_number']}-{track['track_number'].zfill(2)}. {track['title']}.{fmt}"
            else:
                filename = f"{track['track_number'].zfill(2)}. {track['title']}.{fmt}"
                
            filename = filename.replace("/", "_").replace("\\", "_")
            filepath = f"{album_folder_path}/{filename}"
            
            # --- 2. FULL ARIA2 + AIOHTTP FALLBACK ---
            headers_dict = {"User-Agent": khinsider_manager.headers["User-Agent"]}
            
            # [KUNCI RAHASIA] Gunakan 'msg': None.
            # Aria2 tetap mendapat Headers penyamaran, tidak akan crash, dan UI tetap rapi!
            details_aria = {'msg': None, 'headers': headers_dict}
            
            # Coba unduh dengan Aria2 
            err = await download_file(dl_url, filepath, retries=1, details=details_aria)
            
            if err:
                LOGGER.warning(f"Khinsider: Aria2 gagal/ditolak. Mengaktifkan AIOHTTP Turbo Fallback untuk {filename}")
                async with aiohttp.ClientSession(headers=headers_dict) as session:
                    async with session.get(dl_url) as r:
                        r.raise_for_status()
                        async with aiofiles.open(filepath, 'wb') as f:
                            async for chunk in r.content.iter_chunked(256 * 1024):
                                if chunk: await f.write(chunk)
            # ----------------------------------------
            
            # 3. Tanam Tags
            track_meta_for_tag = {
                'date': album_meta['date'],
                'disc_number': track['disc_number'],
                'totalvolumes': album_meta['totalvolumes']
            }
            if cover_path:
                await asyncio.to_thread(set_file_tags, filepath, track_meta_for_tag, cover_path, fmt)
            
            # 4. Ambil Durasi Asli
            duration = 0
            try:
                if fmt == 'flac':
                    audio = FLAC(filepath)
                    duration = int(audio.info.length)
                elif fmt == 'mp3':
                    audio = MP3(filepath)
                    duration = int(audio.info.length)
            except Exception as e:
                LOGGER.error(f"Gagal baca durasi {filename}: {e}")

            meta = {
                'title': track['title'],
                'album': album_meta['title'],
                'artist': 'Game Soundtrack',
                'tracknumber': track['track_number'],
                'totaltracks': str(track_total),
                'filepath': filepath,
                'cover': cover_path, 
                'provider': 'Khinsider',
                'type': 'album',
                'quality': fmt.upper(),
                'duration': duration,
                'extension': fmt
            }
            return meta
        except Exception as e:
            LOGGER.error(f"Khinsider track error: {e}")
            return None

    tasks = [_process_track(t) for t in album_meta['tracks']]
    update_details = {
        'msg': msg, 
        'title': album_meta['title'], 
        'type': 'Album',
        'action': 'Download'
    }
    
    # Eksekusi dengan limit 4 agar aman dari limitasi server
    results = await run_concurrent_tasks(tasks, update_details, limit=4) 
    successful_tracks = [r for r in results if r]

    if not successful_tracks:
        await edit_message(msg, "❌ Gagal mengunduh semua lagu Khinsider.")
        return

    album_data['tracks'] = successful_tracks

    # 5. Upload
    await edit_message(msg, "⚙️ Memproses upload...")
    
    _, album_zip, _, _ = await asyncio.to_thread(fetch_zip_settings, user)
    if album_zip:
        await edit_message(msg, "📦 Mengompresi album ke ZIP...")
        album_data['zip_path'] = await asyncio.to_thread(zip_folder, album_folder_path)
    
    await edit_message(msg, "🚀 Mengunggah...")
    await album_upload(album_data, user)
