# [FILE: bot/helpers/uploder.py] - VERSI DEBUG KHUSUS

import os
import asyncio
import shutil
from config import Config 
from pyrogram.errors import MessageNotModified

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *
from bot.logger import LOGGER 

from ..modules.direct_uploader import DirectUpload

class FakeListener:
    def __init__(self, user_dict):
        self.user_dict = user_dict
        self.extra_details = {} 
        self.is_cancelled = False 
    async def onUploadError(self, error):
        LOGGER.error(f"Cloud Upload Error: {error}")
        return str(error)

def create_cloud_caption(metadata):
    title = metadata.get('title', 'Unknown')
    quality = metadata.get('quality', 'Unknown')
    provider = metadata.get('provider', 'Unknown')
    
    if 'tracks' in metadata:
        total_tracks = len(metadata['tracks'])
    else:
        total_tracks = metadata.get('totaltracks', 1)

    if metadata.get('type') == 'playlist':
        return f"<b>ᴛɪᴛʟᴇ</b> : {title}\n<b>ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs</b> : {total_tracks}\n<b>ǫᴜᴀʟɪᴛʏ</b> : {quality}\n<b>ᴘʀᴏᴠɪᴅᴇʀ</b> : {provider}"

    artist = metadata.get('artist', 'Unknown')
    date = metadata.get('date') or metadata.get('release_date') or 'Unknown'
    total_volumes = metadata.get('total_volumes') or 1
    explicit = str(metadata.get('explicit', False))

    return f"<b>ᴛɪᴛʟᴇ</b> : {title}\n<b>ᴀʀᴛɪsᴛ</b> : {artist}\n<b>ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ</b> : {date}\n<b>ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs</b> : {total_tracks}\n<b>ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs</b> : {total_volumes}\n<b>ǫᴜᴀʟɪᴛʏ</b> : {quality}\n<b>ᴘʀᴏᴠɪᴅᴇʀ</b> : {provider}\n<b>ᴇxᴘʟɪᴄɪᴛ</b> : {explicit}"

async def upload_to_cloud_handler(filepath, user, metadata, mode):
    LOGGER.info(f"[DEBUG UPLOADER] Memulai Handler Cloud. Mode: {mode}, Path: {filepath}")
    user_id = user['user_id']
    user_data = bot_set.user_data.get(user_id, {})
    
    mode = mode.title() if mode else 'Telegram'

    if mode == 'Gofile': token = user_data.get('gofile_token')
    elif mode == 'Buzzheavier': token = user_data.get('buzzheavier_token')
    elif mode == 'Vikingfiles': token = user_data.get('viking_token')
    else: token = None
    
    if not token:
        LOGGER.warning(f"[DEBUG UPLOADER] Token Kosong untuk {mode}!")
        await send_message(user, f"⚠️ <b>{mode} Token Missing!</b>", 'text')
        return None

    server_dict = {
        "gofile": {"api": user_data.get('gofile_token')},
        "buzzheavier": {"api": user_data.get('buzzheavier_token')},
        "vikingfiles": {"api": user_data.get('viking_token')}
    }
    
    if isinstance(filepath, list): 
        base_path = os.path.dirname(filepath[0])
        LOGGER.info(f"[DEBUG UPLOADER] Base Path (List): {base_path}")
    elif os.path.isfile(filepath):
        base_path = os.path.dirname(filepath)
        LOGGER.info(f"[DEBUG UPLOADER] Base Path (File): {base_path}")
    else:
        base_path = os.path.dirname(filepath.rstrip('/'))
        LOGGER.info(f"[DEBUG UPLOADER] Base Path (Dir): {base_path}")
        
    listener = FakeListener(server_dict)
    uploader = DirectUpload(listener=listener, path=base_path)

    try:
        folder_name = metadata.get('title', 'Unknown Album')

        # KASUS A: LIST FILES
        if isinstance(filepath, list):
            LOGGER.info("[DEBUG UPLOADER] Terdeteksi LIST FILES (Split Zip)")
            if 'bot_msg' in user:
                await edit_message(user['bot_msg'], f"📂 Detected {len(filepath)} Split Files. Uploading to {mode}...")

            if mode == 'Gofile':
                root_id = await uploader.gofile_get_root(token)
                new_folder = await uploader.gofile_create_folder_async(token, root_id, folder_name)
                if new_folder:
                    folder_id = new_folder['id']
                    final_link = new_folder['code']
                    for index, file_part in enumerate(filepath, 1):
                        await edit_message(user['bot_msg'], f"🚀 Uploading Part {index}/{len(filepath)}: `{os.path.basename(file_part)}`")
                        await uploader.upload(os.path.basename(file_part), 0, 'gofile', specific_folder_id=folder_id)
                    return f"https://gofile.io/d/{final_link}"

            elif mode == 'Buzzheavier':
                root_id = await uploader.buzzheavier_get_root(token)
                parent_id = await uploader.buzzheavier_create_folder_async(token, root_id, folder_name)
                target_folder = parent_id if parent_id else None
                
                uploaded_links = []
                for index, file_part in enumerate(filepath, 1):
                    await edit_message(user['bot_msg'], f"🚀 Uploading Part {index}/{len(filepath)} to Buzzheavier...")
                    res = await uploader.upload(os.path.basename(file_part), 0, 'buzzheavier', specific_folder_id=target_folder)
                    if res: uploaded_links.append(list(res.values())[0])
                
                if target_folder: return f"https://buzzheavier.com/{target_folder}"
                else: return "\n".join(uploaded_links)

            elif mode == 'Vikingfiles':
                links = []
                for index, file_part in enumerate(filepath, 1):
                    await edit_message(user['bot_msg'], f"🚀 Uploading Part {index}/{len(filepath)} to Vikingfiles...")
                    res = await uploader.upload(os.path.basename(file_part), 0, 'viking')
                    if res: links.append(list(res.values())[0])
                return "\n".join(links)

        # KASUS B: SINGLE FILE
        elif os.path.isfile(filepath):
            LOGGER.info("[DEBUG UPLOADER] Terdeteksi SINGLE FILE")
            if 'bot_msg' in user: await edit_message(user['bot_msg'], f"🚀 Uploading to {mode}...")
            
            if mode == 'Buzzheavier':
                root_id = await uploader.buzzheavier_get_root(token)
                parent_id = await uploader.buzzheavier_create_folder_async(token, root_id, folder_name)
                res = await uploader.upload(os.path.basename(filepath), 0, 'buzzheavier', specific_folder_id=parent_id)
                if res and parent_id: return f"https://buzzheavier.com/{parent_id}"
                elif res: return list(res.values())[0]
            
            else:
                res = await uploader.upload(os.path.basename(filepath), 0, mode.lower())
                if res: return list(res.values())[0]

        # KASUS C: FOLDER ASLI
        elif os.path.isdir(filepath):
            LOGGER.info("[DEBUG UPLOADER] Terdeteksi FOLDER (Non-Zip)")
            files = [f for f in os.listdir(filepath) if os.path.isfile(os.path.join(filepath, f))]
            
            if mode == 'Buzzheavier':
                if 'bot_msg' in user: await edit_message(user['bot_msg'], f"📂 Uploading Folder to Buzzheavier...")
                uploader.path = filepath 
                root_id = await uploader.buzzheavier_get_root(token)
                parent_id = await uploader.buzzheavier_create_folder_async(token, root_id, folder_name)
                target_folder = parent_id if parent_id else None

                links = []
                for index, filename in enumerate(files, 1):
                    await edit_message(user['bot_msg'], f"🚀 Uploading {index}/{len(files)}: `{filename}`")
                    res = await uploader.upload(filename, 0, 'buzzheavier', specific_folder_id=target_folder)
                    if res: links.append(list(res.values())[0])
                
                if target_folder: return f"https://buzzheavier.com/{target_folder}"
                return "\n".join(links)

            elif mode == 'Gofile':
                if 'bot_msg' in user: await edit_message(user['bot_msg'], f"📂 Creating Gofile Folder...")
                uploader.path = filepath 

                root_id = await uploader.gofile_get_root(token)
                new_folder = await uploader.gofile_create_folder_async(token, root_id, folder_name)
                
                if new_folder:
                    folder_id = new_folder['id']
                    final_link = new_folder['code']
                    for index, filename in enumerate(files, 1):
                        await edit_message(user['bot_msg'], f"🚀 Uploading {index}/{len(files)}: `{filename}`")
                        await uploader.upload(filename, 0, 'gofile', specific_folder_id=folder_id)
                    return f"https://gofile.io/d/{final_link}"
                else:
                    return None

            elif mode == 'Vikingfiles':
                uploader.path = filepath 
                links = []
                for index, filename in enumerate(files, 1):
                    await edit_message(user['bot_msg'], f"🚀 Uploading {index}/{len(files)} to Vikingfiles...")
                    res = await uploader.upload(filename, 0, 'viking')
                    if res: links.append(list(res.values())[0])
                return "\n".join(links)

    except Exception as e:
        LOGGER.error(f"[DEBUG UPLOADER] Exception di Handler: {e}")
        await send_message(user, f"⚠️ {mode} Error: {e}", 'text')
    
    return None

# --- TASK HANDLERS (DEBUGGED) ---

async def album_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): target = metadata['zip_path'] 
        link = await upload_to_cloud_handler(target, user, metadata, user_mode.title())
        if link:
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            if metadata.get('poster_msg'): await edit_message(metadata['poster_msg'], caption)
            else: await send_message(user, caption, 'text')
        else:
             await send_message(user, f"❌ <b>Upload Failed!</b>\nCould not upload to {user_mode}.", 'text')
        await cleanup(None, metadata, user_dict)
        return 

    if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'):
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str): zip_files = [zip_files] 
            for item in zip_files: 
                await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata)
        else: await batch_telegram_upload(metadata, user)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata.get('poster_msg'):
            try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified: pass
        else: await post_simple_message(user, metadata, rclone_link, index_link)
    await cleanup(None, metadata, user_dict)

async def artist_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): target = metadata['zip_path']
        link = await upload_to_cloud_handler(target, user, metadata, user_mode.title())
        if link:
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            if metadata.get('poster_msg'): await edit_message(metadata['poster_msg'], caption)
            else: await send_message(user, caption, 'text')
        else:
             await send_message(user, f"❌ <b>Upload Failed!</b>\nCould not upload to {user_mode}.", 'text')
        await cleanup(None, metadata, user_dict)
        return
    
    if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'): 
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str): zip_files = [zip_files]
            for item in zip_files: await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata)
        else: pass 
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata.get('poster_msg'):
            try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified: pass
        else: await post_simple_message(user, metadata, rclone_link, index_link)
    await cleanup(None, metadata, user_dict)

# --- [BAGIAN INI YANG KITA DEBUG HABIS-HABISAN] ---
async def playlist_upload(metadata, user):
    user_id = user['user_id']
    user_data = bot_set.user_data.get(user_id, {})
    user_mode = user_data.get('upload_mode', 'Telegram')
    
    LOGGER.info(f"------------------------------------------------")
    LOGGER.info(f"[DEBUG UPLOADER] PLAYLIST UPLOAD DIPANGGIL")
    LOGGER.info(f"[DEBUG UPLOADER] User ID: {user_id}")
    LOGGER.info(f"[DEBUG UPLOADER] Raw Mode dari DB: '{user_mode}'")
    LOGGER.info(f"[DEBUG UPLOADER] Title Mode: '{user_mode.title()}'")
    LOGGER.info(f"------------------------------------------------")

    # [LOGIC CHECK]
    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        LOGGER.info(f"[DEBUG UPLOADER] >>> MASUK BLOK CLOUD ({user_mode})")
        
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): 
            target = metadata['zip_path'] 
            LOGGER.info(f"[DEBUG UPLOADER] Target = Zip: {target}")
        else:
            LOGGER.info(f"[DEBUG UPLOADER] Target = Folder: {target}")
        
        link = await upload_to_cloud_handler(target, user, metadata, user_mode.title())
        
        if link:
            LOGGER.info(f"[DEBUG UPLOADER] Upload SUKSES. Link: {link}")
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            if metadata.get('poster_msg'): await edit_message(metadata['poster_msg'], caption)
            else: await send_message(user, caption, 'text')
        else:
            LOGGER.error(f"[DEBUG UPLOADER] Upload GAGAL (Link None).")
            await send_message(user, f"❌ <b>Upload Failed!</b>\nCould not upload to {user_mode}.", 'text')

        await cleanup(None, metadata, user)
        LOGGER.info(f"[DEBUG UPLOADER] STOPPING PROCESS (RETURN)")
        return # HARUS STOP DI SINI

    LOGGER.info(f"[DEBUG UPLOADER] >>> MASUK BLOK FALLBACK (Default/Telegram)")

    # --- FALLBACK ---
    if bot_set.upload_mode == 'Local': 
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'): 
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str): zip_files = [zip_files]
            for item in zip_files: await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata)
        else: await batch_telegram_upload(metadata, user)
    else:
        # BAGIAN BANJIR POSTER
        LOGGER.info(f"[DEBUG UPLOADER] Masuk logika Rclone/Sort...")
        playlist_zip, _, __, ___ = fetch_zip_settings(user)
        if bot_set.playlist_sort and not playlist_zip:
            if bot_set.disable_sort_link: await rclone_upload(user, f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
            else:
                for track in metadata['tracks']:
                    try:
                        rclone_link, index_link = await rclone_upload(user, track['filepath'])
                        if not bot_set.disable_sort_link: await post_simple_message(user, track, rclone_link, index_link)
                    except ValueError: pass
        else:
            rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
            if metadata.get('poster_msg'):
                try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified: pass
            else: await post_simple_message(user, metadata, rclone_link, index_link)
    await cleanup(None, metadata, user)

async def track_upload(metadata, user, disable_link=False):
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    upload_success = False
    
    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        link = await upload_to_cloud_handler(metadata['filepath'], user, metadata, user_mode.title())
        if link:
            caption = await create_simple_text(metadata, user)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            await send_message(user, caption, 'text')
            upload_success = True
            try:
                if os.path.exists(metadata['filepath']): os.remove(metadata['filepath'])
            except: pass
            return 

    if not upload_success:
        if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
        elif bot_set.upload_mode == 'Telegram' or user_mode == 'Telegram': await telegram_upload(metadata, user)
        else:
            rclone_link, index_link = await rclone_upload(user, metadata['filepath'])
            if not disable_link: await post_simple_message(user, metadata, rclone_link, index_link)
    try: 
        if os.path.exists(metadata['filepath']): os.remove(metadata['filepath'])
    except: pass

async def rclone_upload(user, realpath):
    path_to_upload = realpath
    base_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    if isinstance(realpath, list): path_to_upload = base_path
    elif isinstance(realpath, str) and realpath.endswith('.zip'): path_to_upload = realpath
    else: path_to_upload = realpath 
    path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    cmd = f'rclone copy --config ./rclone.conf "{path}" "{Config.RCLONE_DEST}"'
    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
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
    user_copy = user
    if batch_mode and 'bot_msg' in user:
        user_copy = user.copy()
        del user_copy['bot_msg']
    filepath = track.get('filepath')
    if not filepath or not os.path.exists(filepath):
        LOGGER.error(f"[UPLOAD FAIL] Path does not exist: '{filepath}'")
        raise FileNotFoundError(f"File not found: {filepath}")
    try: await send_message(user_copy, filepath, 'audio', meta=meta)
    except Exception as e:
        LOGGER.error(f"[UPLOAD ERROR] send_message failed for {filepath}: {e}")
        raise e

async def batch_telegram_upload(metadata, user):
    tasks = []
    if metadata['type'] in ['album', 'playlist']:
        for track in metadata['tracks']:
            if not track.get('filepath'): continue
            tasks.append(telegram_upload(track, user, batch_mode=True)) 
    elif metadata['type'] == 'artist':
        for album in metadata['albums']:
            for track in album['tracks']:
                if not track.get('filepath'): continue
                tasks.append(telegram_upload(track, user, batch_mode=True))
    if not tasks: return
    try: await edit_message(user['bot_msg'], f"Mengunggah {len(tasks)} lagu secara paralel...")
    except: pass
    semaphore = asyncio.Semaphore(Config.MAX_WORKERS)
    async def sem_task(task):
        async with semaphore:
            try: await task 
            except FileNotFoundError: pass
            except Exception as e: LOGGER.error(f"Failed to upload one track during batch: {e}")
    await asyncio.gather(*(sem_task(task) for task in tasks))
