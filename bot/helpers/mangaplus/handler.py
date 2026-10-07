import os
import re
import time
import asyncio
import aiohttp
import aiofiles
import hashlib

from config import Config
from bot.logger import LOGGER
from bot.settings import bot_set
from bot.helpers.message import edit_message
from bot.helpers.ui_manager import progress_message, GLOBAL_CANCEL_DICT
from bot.helpers.mangaplus.api import MangaPlusAPI

api = MangaPlusAPI()

async def start_mangaplus(link: str, user: dict):
    match = re.search(r'/viewer/(\d+)', link)
    if not match:
        if '/titles/' in link:
             raise Exception("❌ Anda mengirimkan link daftar isi manga. Silakan buka salah satu chapter dan kirimkan link dari halaman membacanya (harus mengandung `/viewer/`).")
        raise Exception("❌ URL MangaPlus tidak valid. Pastikan format URL mengandung /viewer/[ID_CHAPTER]")
    
    chapter_id = match.group(1)
    msg = user.get('bot_msg')
    
    if msg:
        await edit_message(msg, f"🔍 Mengambil data API MangaPlus untuk Chapter `{chapter_id}`...")
        
    try:
        data = await api.get_chapter_data(chapter_id)
    except Exception as e:
        raise Exception(f"Gagal mengambil metadata MangaPlus: {e}")
        
    pages = data['pages']
    total_pages = len(pages)
    
    if total_pages == 0:
        raise Exception("Tidak ada halaman manga yang ditemukan. Konten mungkin dikunci berdasarkan region server Anda, atau chapter tersebut dibatasi untuk akun Premium.")
        
    chapter_title = f"MangaPlus_Chapter_{chapter_id}"
    base_path = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']), "MangaPlus", chapter_title)
    os.makedirs(base_path, exist_ok=True)
    
    task_id = hashlib.md5(str(msg.id).encode()).hexdigest()[:16] if msg else "unknown"
    update_details = {
        'msg': msg, 'title': chapter_title,
        'type': 'Manga Chapter', 'action': 'Downloading',
        'machine': 'Native Decryptor', 'task_id': task_id
    }

    sem = asyncio.Semaphore(Config.MAX_WORKERS or 10)
    completed = 0
    
    async def download_page(page_data):
        nonlocal completed
        if task_id in GLOBAL_CANCEL_DICT: return False
            
        img_url = page_data['url']
        hex_key = page_data['key']
        filename = f"{str(page_data['page_num']).zfill(3)}.jpg"
        filepath = os.path.join(base_path, filename)
        
        async with sem:
            if task_id in GLOBAL_CANCEL_DICT: return False
            try:
                async with aiohttp.ClientSession(headers=api.headers) as session:
                    async with session.get(img_url, timeout=30) as resp:
                        raw_bytes = await resp.read()
                        
                decrypted_bytes = api.decrypt_image(raw_bytes, hex_key)
                
                async with aiofiles.open(filepath, 'wb') as f:
                    await f.write(decrypted_bytes)
                    
                completed += 1
                await progress_message(completed, total_pages, update_details)
                return True
            except Exception as e:
                LOGGER.error(f"Gagal mengunduh halaman {page_data['page_num']}: {e}")
                return False

    tasks = [download_page(p) for p in pages]
    await asyncio.gather(*tasks)
    
    if task_id in GLOBAL_CANCEL_DICT:
        raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")

    metadata = {
        'itemid': chapter_id,
        'title': chapter_title,
        'type': 'album',
        'provider': 'MangaPlus',
        'quality': 'Super High (Descrambled)',
        'folderpath': base_path,
        'poster_msg': msg,
        'totaltracks': total_pages,
        'artist': 'Shueisha',
        'release_date': time.strftime("%Y-%m-%d"),
        'tracks': []
    }
    
    user_id = user['user_id']
    original_zip = bot_set.user_data.get(user_id, {}).get('ALBUM_ZIP')
    bot_set.user_data.setdefault(user_id, {})['ALBUM_ZIP'] = True
    
    try:
        from bot.helpers.uploder import album_upload
        await album_upload(metadata, user)
    finally:
        if original_zip is not None:
            bot_set.user_data[user_id]['ALBUM_ZIP'] = original_zip
        else:
            bot_set.user_data[user_id].pop('ALBUM_ZIP', None)
