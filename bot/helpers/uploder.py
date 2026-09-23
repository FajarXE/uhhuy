# [GANTI SELURUH ISI FILE: bot/helpers/uploder.py]

import os
import asyncio
import shutil
import hashlib 
import aiohttp # <-- Tambahan import untuk exception handling
from config import Config 
from pyrogram.errors import MessageNotModified

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *

from bot.helpers.ui_manager import progress_message, GLOBAL_CANCEL_DICT
from bot.logger import LOGGER 
import bot.helpers.translations as lang

from bot.tgclient import aio 
from ..modules.direct_uploader import DirectUpload

class FakeListener:
    def __init__(self, user_dict):
        self.user_dict = user_dict
        self.extra_details = {} 
        self.is_cancelled = False 
    async def onUploadError(self, error):
        LOGGER.error(f"Cloud Upload Error: {error}")
        return str(error)

async def tg_progress_callback(current, total, details):
    if details:
        task_id = details.get('task_id')
        if task_id:
            if task_id in GLOBAL_CANCEL_DICT:
                import asyncio
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
        await progress_message(current, total, details)

def create_cloud_caption(metadata):
    title = metadata.get('title', 'Unknown')
    quality = metadata.get('quality', 'Unknown')
    provider = metadata.get('provider', 'Unknown')
    if 'tracks' in metadata: total_tracks = len(metadata['tracks'])
    else: total_tracks = metadata.get('totaltracks', 1)

    if metadata.get('type') == 'playlist':
        return f"<b>ᴛɪᴛʟᴇ</b> : {title}\n<b>ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs</b> : {total_tracks}\n<b>ǫᴜᴀʟɪᴛʏ</b> : {quality}\n<b>ᴘʀᴏᴠɪᴅᴇʀ</b> : {provider}"

    artist = metadata.get('artist', 'Unknown')
    date = metadata.get('release_date') or metadata.get('date') or 'Unknown'
    total_volumes = metadata.get('total_volumes') or 1
    explicit = str(metadata.get('explicit', False))
    return f"<b>ᴛɪᴛʟᴇ</b> : {title}\n<b>ᴀʀᴛɪsᴛ</b> : {artist}\n<b>ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ</b> : {date}\n<b>ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs</b> : {total_tracks}\n<b>ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs</b> : {total_volumes}\n<b>ǫᴜᴀʟɪᴛʏ</b> : {quality}\n<b>ᴘʀᴏᴠɪᴅᴇʀ</b> : {provider}\n<b>ᴇxᴘʟɪᴄɪᴛ</b> : {explicit}"

# ==========================================
# CLOUD UPLOAD STRATEGIES (ADAPTOR)
# ==========================================
class CloudStrategy:
    async def prepare_folder(self, uploader, token, folder_name): pass
    def get_upload_kwargs(self): return {}
    def format_result(self, uploaded_links): return None

class GofileStrategy(CloudStrategy):
    def __init__(self):
        self.folder_id = None
        self.folder_code = None

    async def prepare_folder(self, uploader, token, folder_name):
        try:
            root_id = await uploader.gofile_get_root(token)
            new_folder = await uploader.gofile_create_folder_async(token, root_id, folder_name)
            if new_folder:
                self.folder_id = new_folder['id']
                self.folder_code = new_folder['code']
        except Exception as e:
            LOGGER.warning(f"Gofile Folder API Error/Lambat: {e}")

    def get_upload_kwargs(self):
        return {'upload_type': 'gofile', 'specific_folder_id': self.folder_id}

    def format_result(self, uploaded_links):
        if self.folder_code: return f"https://gofile.io/d/{self.folder_code}"
        return "\n".join(uploaded_links) if uploaded_links else None

class BuzzheavierStrategy(CloudStrategy):
    def __init__(self):
        self.folder_id = None

    async def prepare_folder(self, uploader, token, folder_name):
        try:
            root_id = await uploader.buzzheavier_get_root(token)
            self.folder_id = await uploader.buzzheavier_create_folder_async(token, root_id, folder_name)
        except Exception as e:
            LOGGER.warning(f"Buzzheavier Folder API Error/Lambat: {e}")

    def get_upload_kwargs(self):
        return {'upload_type': 'buzzheavier', 'specific_folder_id': self.folder_id}

    def format_result(self, uploaded_links):
        if self.folder_id: return f"https://buzzheavier.com/{self.folder_id}"
        return "\n".join(uploaded_links) if uploaded_links else None

class VikingfilesStrategy(CloudStrategy):
    def get_upload_kwargs(self):
        return {'upload_type': 'viking'}

    def format_result(self, uploaded_links):
        return "\n".join(uploaded_links) if uploaded_links else None
# ==========================================

async def upload_to_cloud_handler(filepath, user, metadata, mode):
    user_id = user['user_id']
    user_data = bot_set.user_data.get(user_id, {})
    mode = mode.title() if mode else 'Telegram'
    
    strategy = None
    token = None
    
    # 1. Pemilihan Strategi Berdasarkan Mode
    if mode == 'Gofile': 
        token = user_data.get('gofile_token')
        strategy = GofileStrategy()
    elif mode == 'Buzzheavier': 
        token = user_data.get('buzzheavier_token')
        strategy = BuzzheavierStrategy()
    elif mode == 'Vikingfiles': 
        token = user_data.get('viking_token')
        strategy = VikingfilesStrategy()
        
    if not token or not strategy:
        await send_message(user, f"⚠️ <b>{mode} Token Missing!</b>", 'text')
        return None

    server_dict = {
        "gofile": {"api": user_data.get('gofile_token')},
        "buzzheavier": {"api": user_data.get('buzzheavier_token')},
        "vikingfiles": {"api": user_data.get('viking_token')}
    }
    
    # 2. Normalisasi Input (Menyatukan Logika List, File Tunggal, dan Direktori)
    files_to_upload = []
    if isinstance(filepath, list):
        files_to_upload = filepath
        base_path = os.path.dirname(filepath[0])
    elif os.path.isfile(filepath):
        files_to_upload = [filepath]
        base_path = os.path.dirname(filepath)
    elif os.path.isdir(filepath):
        files_to_upload = [os.path.join(filepath, f) for f in os.listdir(filepath) if os.path.isfile(os.path.join(filepath, f))]
        base_path = filepath
    else:
        base_path = os.path.dirname(filepath.rstrip('/'))

    if not files_to_upload:
        return None
        
    listener = FakeListener(server_dict)
    uploader = DirectUpload(listener=listener, path=base_path)

    details = None
    if 'bot_msg' in user:
        task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        details = {
            'msg': user['bot_msg'], 'title': metadata.get('title', 'Unknown'),
            'type': metadata.get('type', 'Task').capitalize(), 'action': 'Upload', 
            'machine': 'AIOHTTP Streaming', 'task_id': task_id 
        }

    try:
        folder_name = metadata.get('title', 'Unknown Album')
        
        # 3. Persiapan Folder (Didelegasikan ke Strategy masing-masing)
        await strategy.prepare_folder(uploader, token, folder_name)
        
        uploaded_links = []
        upload_kwargs = strategy.get_upload_kwargs()
        total_files = len(files_to_upload)
        
        # 4. Iterasi Eksekusi Upload Seragam (Bebas Duplikasi)
        for index, file_part in enumerate(files_to_upload, 1):
            filename = os.path.basename(file_part)
            if details:
                details['title'] = f"[{index}/{total_files}] {filename}" if total_files > 1 else filename
                    
            res = await uploader.upload(filename, 0, details=details, **upload_kwargs)
            if res: 
                uploaded_links.append(list(res.values())[0])

        # 5. Ekstraksi Hasil (Didelegasikan ke Strategy)
        return strategy.format_result(uploaded_links)

    # --- PENANGANAN ERROR SPESIFIK & TRACEBACK ---
    except asyncio.TimeoutError:
        LOGGER.error(f"[UPLOAD TIMEOUT] Cloud API {mode} terlalu lambat merespons.")
        await send_message(user, f"⚠️ <b>{mode} Error:</b> Request Timeout.", 'text')
    except aiohttp.ClientError as e:
        LOGGER.error(f"[UPLOAD NETWORK ERROR] di Cloud Handler: {e}")
        await send_message(user, f"⚠️ <b>{mode} Error:</b> Gangguan jaringan.", 'text')
    except KeyError as e:
        LOGGER.error(f"[UPLOAD KEY ERROR] Struktur respon API berubah: {e}")
        await send_message(user, f"⚠️ <b>{mode} Error:</b> Respons API tidak terduga (Kehilangan key {e}).", 'text')
    except Exception as e:
        # Menggunakan .exception() agar traceback penuh tercetak di log
        LOGGER.exception(f"[UPLOAD FATAL ERROR] Exception tidak terduga di Cloud Handler: {e}")
        await send_message(user, f"⚠️ <b>{mode} Error:</b> {e}", 'text')
    
    return None

def handle_lyrics_files(folderpath, user_id):
    user_settings = bot_set.user_data.get(user_id, {})
    send_lyrics = user_settings.get('send_lyrics_file', False)
    
    if not send_lyrics and folderpath and os.path.exists(folderpath):
        for root, dirs, files in os.walk(folderpath):
            for file in files:
                if file.lower().endswith(('.lrc', '.txt')):
                    try: os.remove(os.path.join(root, file))
                    except Exception as e: LOGGER.error(f"Gagal menghapus lirik {file}: {e}")

async def album_upload(metadata, user):
    user_dict = user.copy()
    user_id = user['user_id']
    user_settings = bot_set.user_data.get(user_id, {})
    user_mode = user_settings.get('upload_mode', 'Telegram')
    
    _, is_zip, _, show_poster = fetch_zip_settings(user)
    LOGGER.info(f"[DEBUG ALBUM] User: {user_id} | Mode: {user_mode} | ZIP: {is_zip} | Poster: {show_poster}")

    handle_lyrics_files(metadata.get('folderpath'), user_id)

    if is_zip and not metadata.get('zip_path'):
        LOGGER.info("[DEBUG ALBUM] ZIP aktif tapi path kosong. Memulai Zipping...")
        if 'bot_msg' in user: 
            up_zip = {'action': 'Zipping', 'type': metadata.get('type', 'Task'), 'title': metadata.get('title', 'Unknown'), 'msg': user['bot_msg']}
            await progress_message(0, 1, up_zip)
            
        metadata['zip_path'] = await zip_handler(metadata['folderpath'])
        LOGGER.info(f"[DEBUG ALBUM] Hasil Zipping: {metadata.get('zip_path')}")

    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): target = metadata['zip_path'] 
        link = await upload_to_cloud_handler(target, user, metadata, user_mode.title())
        if link:
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            if show_poster and metadata.get('poster_msg'):
                await edit_message(metadata['poster_msg'], caption)
            else:
                if metadata.get('poster_msg'):
                    try: await aio.delete_messages(user['chat_id'], metadata['poster_msg'].id)
                    except: pass
                await send_message(user, caption, 'text')
        else:
             await send_message(user, f"❌ <b>Upload Failed!</b>", 'text')
        await cleanup(None, metadata, user_dict)
        return 

    if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        LOGGER.info("[DEBUG ALBUM] Masuk Logic Telegram Upload")
        if show_poster and metadata.get('poster_msg'):
            caption = await format_string(lang.s.ALBUM_TEMPLATE, metadata, user)
            try: await edit_message(metadata['poster_msg'], caption)
            except MessageNotModified: pass
        
        if is_zip and metadata.get('zip_path'):
            LOGGER.info("[DEBUG ALBUM] Uploading ZIP ke Telegram")
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str): zip_files = [zip_files] 
            for item in zip_files: 
                details = None
                if 'bot_msg' in user:
                    task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
                    details = {'msg': user['bot_msg'], 'title': os.path.basename(item), 'type': 'Zip Archive', 'action': 'Upload', 'machine': 'Telegram API', 'task_id': task_id}
                await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata, progress=tg_progress_callback, progress_args=(details,))
        else: 
            LOGGER.info("[DEBUG ALBUM] Uploading Batch Tracks (ZIP False/Gagal)")
            await batch_telegram_upload(metadata, user)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') if is_zip else metadata['folderpath'])
        if show_poster and metadata.get('poster_msg'):
            try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified: pass
        else:
            if metadata.get('poster_msg'):
                try: await aio.delete_messages(user['chat_id'], metadata['poster_msg'].id)
                except: pass
            await post_simple_message(user, metadata, rclone_link, index_link)
            
    await cleanup(None, metadata, user_dict)

async def artist_upload(metadata, user):
    user_dict = user.copy()
    user_id = user['user_id']
    user_settings = bot_set.user_data.get(user_id, {})
    user_mode = user_settings.get('upload_mode', 'Telegram')
    
    _, _, is_zip, show_poster = fetch_zip_settings(user)
    LOGGER.info(f"[DEBUG ARTIST] User: {user_id} | ZIP: {is_zip} | Poster: {show_poster}")
    handle_lyrics_files(metadata.get('folderpath'), user_id)

    if is_zip and not metadata.get('zip_path'):
        if 'bot_msg' in user: 
            up_zip = {'action': 'Zipping', 'type': metadata.get('type', 'Task'), 'title': metadata.get('title', 'Unknown'), 'msg': user['bot_msg']}
            await progress_message(0, 1, up_zip)
        metadata['zip_path'] = await zip_handler(metadata['folderpath'])

    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): target = metadata['zip_path']
        link = await upload_to_cloud_handler(target, user, metadata, user_mode.title())
        
        if link:
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            if show_poster and metadata.get('poster_msg'): 
                await edit_message(metadata['poster_msg'], caption)
            else:
                if metadata.get('poster_msg'):
                    try: await aio.delete_messages(user['chat_id'], metadata['poster_msg'].id)
                    except: pass
                await send_message(user, caption, 'text')
        else:
             await send_message(user, f"❌ <b>Upload Failed!</b>\nCould not upload to {user_mode}.", 'text')
        await cleanup(None, metadata, user_dict)
        return
    
    if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if show_poster and metadata.get('poster_msg'):
            caption = await format_string(lang.s.ARTIST_TEMPLATE, metadata, user)
            try: await edit_message(metadata['poster_msg'], caption)
            except: pass

        if is_zip and metadata.get('zip_path'): 
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str): zip_files = [zip_files]
            for item in zip_files: 
                details = None
                if 'bot_msg' in user:
                    task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
                    details = {'msg': user['bot_msg'], 'title': os.path.basename(item), 'type': 'Zip Archive', 'action': 'Upload', 'machine': 'Telegram API', 'task_id': task_id}
                await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata, progress=tg_progress_callback, progress_args=(details,))
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') if is_zip else metadata['folderpath'])
        if show_poster and metadata.get('poster_msg'):
            try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified: pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)
            
    await cleanup(None, metadata, user_dict)

async def playlist_upload(metadata, user):
    user_id = user['user_id']
    user_settings = bot_set.user_data.get(user_id, {})
    user_mode = user_settings.get('upload_mode', 'Telegram')
    
    is_zip, _, _, show_poster = fetch_zip_settings(user)
    LOGGER.info(f"[DEBUG PLAYLIST] User: {user_id} | ZIP: {is_zip} | Poster: {show_poster}")
    handle_lyrics_files(metadata.get('folderpath'), user_id)

    if is_zip and not metadata.get('zip_path'):
        if 'bot_msg' in user: 
            up_zip = {'action': 'Zipping', 'type': metadata.get('type', 'Task'), 'title': metadata.get('title', 'Unknown'), 'msg': user['bot_msg']}
            await progress_message(0, 1, up_zip)
        metadata['zip_path'] = await zip_handler(metadata['folderpath'])

    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): target = metadata['zip_path'] 
        link = await upload_to_cloud_handler(target, user, metadata, user_mode.title())
        if link:
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            if show_poster and metadata.get('poster_msg'): 
                await edit_message(metadata['poster_msg'], caption)
            else: 
                if metadata.get('poster_msg'):
                    try: await aio.delete_messages(user['chat_id'], metadata['poster_msg'].id)
                    except: pass
                await send_message(user, caption, 'text')
        else:
            await send_message(user, f"❌ <b>Upload Failed!</b>\nCould not upload to {user_mode}.", 'text')
        await cleanup(None, metadata, user)
        return

    if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if show_poster and metadata.get('poster_msg'):
            caption = await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user)
            try: await edit_message(metadata['poster_msg'], caption)
            except: pass

        if is_zip and metadata.get('zip_path'): 
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str): zip_files = [zip_files]
            for item in zip_files: 
                details = None
                if 'bot_msg' in user:
                    task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
                    details = {'msg': user['bot_msg'], 'title': os.path.basename(item), 'type': 'Zip Archive', 'action': 'Upload', 'machine': 'Telegram API', 'task_id': task_id}
                await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata, progress=tg_progress_callback, progress_args=(details,))
        else: 
            await batch_telegram_upload(metadata, user)
    else:
        if bot_set.playlist_sort and not is_zip:
            if bot_set.disable_sort_link: await rclone_upload(user, f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
            else:
                for track in metadata['tracks']:
                    try:
                        rclone_link, index_link = await rclone_upload(user, track['filepath'])
                        if not bot_set.disable_sort_link: await post_simple_message(user, track, rclone_link, index_link)
                    except ValueError: pass
        else:
            rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') if is_zip else metadata['folderpath'])
            if show_poster and metadata.get('poster_msg'):
                try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified: pass
            else:
                if metadata.get('poster_msg'):
                    try: await aio.delete_messages(user['chat_id'], metadata['poster_msg'].id)
                    except: pass
                await post_simple_message(user, metadata, rclone_link, index_link)
                
    await cleanup(None, metadata, user)

async def track_upload(metadata, user, disable_link=False):
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', bot_set.upload_mode)
    upload_success = False
    
    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        link = await upload_to_cloud_handler(metadata['filepath'], user, metadata, user_mode.title())
        if link:
            caption = await create_simple_text(metadata, user)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            await send_message(user, caption, 'text')
            upload_success = True
            
            # --- [FIX SILENT ERROR] Retry Hapus File ---
            await asyncio.sleep(0.5)
            for _ in range(3):
                try:
                    if os.path.exists(metadata['filepath']): os.remove(metadata['filepath'])
                    break
                except PermissionError: await asyncio.sleep(1.0)
                except FileNotFoundError: break
                except Exception as e: 
                    LOGGER.debug(f"Gagal menghapus file lokal: {e}")
                    break
            # -------------------------------------------
            return 

    if not upload_success:
        if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
        elif bot_set.upload_mode == 'Telegram' or user_mode == 'Telegram': await telegram_upload(metadata, user)
        else:
            rclone_link, index_link = await rclone_upload(user, metadata['filepath'])
            if not disable_link: await post_simple_message(user, metadata, rclone_link, index_link)
            
    # --- [FIX SILENT ERROR] Retry Hapus File Default ---
    await asyncio.sleep(0.5)
    for _ in range(3):
        try:
            if os.path.exists(metadata['filepath']): os.remove(metadata['filepath'])
            break
        except PermissionError: await asyncio.sleep(1.0)
        except FileNotFoundError: break
        except Exception as e: 
            LOGGER.debug(f"Gagal menghapus file lokal default: {e}")
            break
    # ---------------------------------------------------

async def rclone_upload(user, realpath):
    path_to_upload = realpath
    base_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    if isinstance(realpath, list): path_to_upload = base_path
    elif isinstance(realpath, str) and realpath.endswith('.zip'): path_to_upload = realpath
    else: path_to_upload = realpath 
    path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    
    process = await asyncio.create_subprocess_exec(
        "rclone", "copy", "--config", "./rclone.conf", path, Config.RCLONE_DEST,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    
    async def consume_stream(stream):
        while True:
            line = await stream.readline()
            if not line:
                break

    try:
        await asyncio.gather(
            consume_stream(process.stdout),
            consume_stream(process.stderr),
            process.wait()
        )
    except asyncio.CancelledError:
        # --- BUNUH ZOMBIE PROCESS RCLONE ---
        try:
            process.terminate()
        except Exception:
            pass
        raise # Lempar kembali error ke fungsi pemanggil agar antrean dibersihkan
    
    r_link, i_link = await create_link(realpath, base_path)
    return r_link, i_link

async def local_upload(metadata, user):
    to_move = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}"
    destination = os.path.join(Config.LOCAL_STORAGE, os.path.basename(to_move))
    if os.path.exists(destination):
        for item in os.listdir(to_move):
            src_item = os.path.join(to_move, item)
            dest_item = os.path.join(destination, item)
            if os.path.isdir(src_item):
                if not os.path.exists(dest_item): shutil.copytree(src_item, dest_item)
            else: shutil.copy2(src_item, dest_item)
    else: shutil.copytree(to_move, destination)
    shutil.rmtree(to_move)

async def telegram_upload(track, user, batch_mode=False): 
    meta = track.copy()
    meta['batch_mode'] = batch_mode
    if 'cover' in meta and (not meta['cover'] or not os.path.exists(meta['cover'])): meta['cover'] = None 
    
    filepath = track.get('filepath')
    if not filepath or not os.path.exists(filepath):
        LOGGER.error(f"[UPLOAD FAIL] Path does not exist: '{filepath}'")
        raise FileNotFoundError(f"File not found: {filepath}")
        
    details = None
    if 'bot_msg' in user:
        task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        task_type = meta.get('type')
        if not task_type: task_type = 'Track'
            
        details = {
            'msg': user['bot_msg'], 'title': meta.get('title', os.path.basename(filepath)),
            'type': task_type.capitalize(), 'action': 'Upload', 'machine': 'Telegram API', 'task_id': task_id
        }
        
    try: 
        media_type = meta.get('media_type', meta.get('type', 'audio')).lower()
        if media_type not in ['audio', 'video', 'doc']: media_type = 'audio' 
            
        await send_message(user, filepath, media_type, meta=meta, progress=tg_progress_callback, progress_args=(details,))

        user_settings = bot_set.user_data.get(user['user_id'], {})
        if user_settings.get('send_lyrics_file', False):
            base_path = os.path.splitext(filepath)[0]
            for ext in ['.lrc', '.txt']:
                lyrics_path = base_path + ext
                if os.path.exists(lyrics_path):
                    await send_message(user, lyrics_path, 'doc', caption=f"📝 Lyrics: {meta.get('title', 'Unknown')}", progress=tg_progress_callback, progress_args=(details,))

    except FileNotFoundError as e:
        LOGGER.error(f"[UPLOAD ERROR] File tidak ada: {e}")
        raise e
    except Exception as e:
        # [FIX] Jangan ditelan! Cetak hirarki lengkapnya
        LOGGER.exception(f"[UPLOAD ERROR] send_message failed for {filepath}:")
        raise e

async def batch_telegram_upload(metadata, user):
    tracks_to_upload = []
    
    if metadata['type'] in ['album', 'playlist']:
        for track in metadata['tracks']:
            if track.get('filepath'):
                tracks_to_upload.append(track)
    elif metadata['type'] == 'artist':
        for album in metadata.get('albums', []):
            for track in album['tracks']:
                if track.get('filepath'):
                    tracks_to_upload.append(track)
                    
    if not tracks_to_upload: return

    for track in tracks_to_upload:
        try:
            await telegram_upload(track, user, batch_mode=True)
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            LOGGER.info("Batch upload dibatalkan oleh pengguna.")
            raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
        except FileNotFoundError:
            pass
        except Exception as e:
            # [FIX]
            LOGGER.exception("Gagal mengunggah track dalam mode batch:")
