# [FILE: bot/helpers/message.py]

import os
import asyncio
import time
import math
import traceback 
import aiohttp 
import hashlib

from pyrogram.types import Message
from pyrogram.errors import MessageNotModified, FloodWait, MessageIdInvalid, RPCError

# Impor global client untuk fallback
from bot.tgclient import aio
from bot.settings import bot_set
from bot.logger import LOGGER
from config import Config

current_user = set()

user_details = {
    'user_id': None, 'name': None, 'user_name': None, 'r_id': None, 
    'chat_id': None, 'provider': None, 'bot_msg': None, 'link': None, 'override' : None 
}

async def copy_to_channel(client, message: Message):
    """Menyalin pesan yang dikirim bot ke Channel yang dikonfigurasi."""
    copy_target = Config.COPY_CHANNEL_ID
    if not copy_target or copy_target == 0: return
    try: await message.copy(copy_target)
    except Exception as e: LOGGER.error(f"Gagal menyalin pesan ke channel {copy_target}: {e}")

async def fetch_user_details(msg: Message, reply=False) -> dict:
    details = user_details.copy()
    details['user_id'] = msg.from_user.id
    details['name'] = msg.from_user.first_name
    details['user_name'] = msg.from_user.username if msg.from_user.username else msg.from_user.mention()
    details['r_id'] = msg.reply_to_message.id if reply else msg.id
    details['chat_id'] = msg.chat.id
    try: details['bot_msg'] = msg
    except: pass
    return details

async def check_user(uid=None, msg=None, restricted=False) -> bool:
    actual_uid = uid if uid else (msg.from_user.id if msg and msg.from_user else None)

    if actual_uid and actual_uid not in bot_set.user_data:
        from bot.helpers.database.mongo_async import database
        user_db_data = await database.get_user_settings(actual_uid)
        bot_set.user_data[actual_uid] = user_db_data or {}
        
        if user_db_data:
            # --- [FIX ERROR] ---
            # Hapus baris 'from .utils import sync_single_user_managers'
            # Karena fungsinya sudah ada di file ini sendiri, kita bisa langsung memanggilnya
            import asyncio
            asyncio.create_task(sync_single_user_managers(actual_uid, user_db_data))
            # -------------------

    if restricted:
        if actual_uid in bot_set.admins: return True
    else:
        if bot_set.bot_public: return True
        else:
            all_chats = list(bot_set.admins) + bot_set.auth_chats + bot_set.auth_users 
            if msg and msg.from_user and msg.from_user.id in all_chats: return True
            elif msg and msg.chat and msg.chat.id in all_chats: return True
    return False

async def sync_single_user_managers(user_id, data):
    """Menyuntikkan pengaturan kualitas user ke manajer musik secara dinamis"""
    try:
        def safe_import_mgr(path, name):
            try:
                mod = __import__(path, fromlist=[name])
                return getattr(mod, name)
            except: 
                return None

        settings_map = {
            'deezer_qual': safe_import_mgr('bot.helpers.deezer.manager', 'deezer_manager'),
            'beatport_qual': safe_import_mgr('bot.helpers.beatport.manager', 'beatport_manager'),
            'tidal_qual': safe_import_mgr('bot.helpers.tidal.manager', 'tidal_manager'),
            'kkbox_qual': safe_import_mgr('bot.helpers.kkbox.manager', 'kkbox_manager'),
            'soundcloud_qual': safe_import_mgr('bot.helpers.soundcloud.manager', 'soundcloud_manager'),
            'idagio_qual': safe_import_mgr('bot.helpers.idagio.manager', 'idagio_manager'),
            'nugs_qual': safe_import_mgr('bot.helpers.nugs.manager', 'nugs_manager'),
            'bugs_qual': safe_import_mgr('bot.helpers.bugs.manager', 'bugs_manager'),
            'highresaudio_qual': safe_import_mgr('bot.helpers.highresaudio.manager', 'highresaudio_manager'),
            'moov_qual': safe_import_mgr('bot.helpers.moov.manager', 'moov_manager'),
            'jiosaavn_qual': safe_import_mgr('bot.helpers.jiosaavn.manager', 'jiosaavn_manager'),
            'gaana_qual': safe_import_mgr('bot.helpers.gaana.manager', 'gaana_manager'),
            'bandcamp_qual': safe_import_mgr('bot.helpers.bandcamp.manager', 'bandcamp_manager'),
            'livephish_qual': safe_import_mgr('bot.helpers.livephish.manager', 'livephish_manager'),
            'beatstars_qual': safe_import_mgr('bot.helpers.beatstars.manager', 'beatstars_manager'),
            'amazon_qual': safe_import_mgr('bot.helpers.amazon.manager', 'amazon_manager'),
            'genie_qual': safe_import_mgr('bot.helpers.genie.manager', 'genie_manager'),
        }
        
        for key, manager in settings_map.items():
            if data.get(key) and manager and hasattr(manager, 'setup_quality'):
                try: await manager.setup_quality(user_id, data[key])
                except Exception: pass

        if data.get('qobuz_qual'):
            from bot import BOT_QOBUZ_CLIENTS
            if BOT_QOBUZ_CLIENTS:
                qobuz_interface = list(BOT_QOBUZ_CLIENTS.values())[0]
                if hasattr(qobuz_interface, 'setup_quality'):
                    try: await qobuz_interface.setup_quality(user_id, data['qobuz_qual'])
                    except Exception: pass
                    
    except Exception as e:
        LOGGER.debug(f"Gagal sinkronisasi manager JIT: {e}")

async def antiSpam(uid=None, cid=None, revoke=False) -> bool:
    if revoke:
        # Menggunakan .discard() lebih aman daripada .remove() 
        # untuk mencegah KeyError jika ada race-condition dari event loop.
        if bot_set.anti_spam == 'CHAT+': 
            current_user.discard(cid)
        elif bot_set.anti_spam == 'USER': 
            current_user.discard(uid)
    else:
        if bot_set.anti_spam == 'CHAT+':
            if cid in current_user: return True
            current_user.add(cid)
        elif bot_set.anti_spam == 'USER':
            if uid in current_user: return True
            current_user.add(uid)
        return False

# ==========================================================
# FUNGSI PROGRESS TERPISAH (STANDALONE)
# ==========================================================
async def standalone_local_progress(current, total, p_state: dict, user, text, task_type):
    from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT, GLOBAL_TASKS, GLOBAL_STATE_LOCK
    from bot.helpers.utils import get_readable_file_size, get_readable_time
    from bot.helpers.aria2_helper import get_aria2_global_stat
    
    if p_state['cancel_id'] in GLOBAL_CANCEL_DICT:
        raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")

    if p_state['is_local'] and not p_state['msg_created']:
        p_state['msg_created'] = True
        p_state['start_time'] = time.time()
        p_state['last_update_time'] = p_state['start_time']
        
        if isinstance(user, dict):
            if user.get('radar_msg'):
                p_state['msg'] = user['radar_msg']
            elif user.get('bot_msg'):
                p_state['msg'] = user['bot_msg']
                user['radar_msg'] = p_state['msg']
            else:
                try:
                    p_state['msg'] = await aio.send_message(p_state['chat_id'], f"🔄 Mengunggah file... `/cancel_{p_state['cancel_id']}`")
                    user['radar_msg'] = p_state['msg']
                except: pass

    if not p_state['msg']: return

    now = time.time()
    if now - p_state['last_update_time'] > 1.5 or current == total:
        diff = max(now - p_state['start_time'], 1)
        speed = current / diff
        percentage = (current / total) * 100 if total > 0 else 0
        
        filled = math.floor((percentage / 100) * 12)
        progress_bar = "■" * filled + "□" * (12 - filled)
        
        dest_mode = bot_set.user_data.get(p_state['chat_id'], {}).get('upload_mode', bot_set.upload_mode)
        
        try:
            stats = await get_aria2_global_stat()
            speed_dl = int(stats.get('downloadSpeed', 0)) if stats else 0
        except: speed_dl = 0
            
        try:
            from bot.helpers.deezer.dzapi import get_deezer_speed
            dz_spd = get_deezer_speed()
            if dz_spd > 0: speed_dl += dz_spd
        except: pass
        
        file_title = os.path.basename(text) if isinstance(text, str) else "Unknown File"
        
        # --- [FIX] UPDATE DICTIONARY DALAM LOCK MEMORI ---
        async with GLOBAL_STATE_LOCK:
            if p_state['cancel_id'] not in GLOBAL_TASKS:
                GLOBAL_TASKS[p_state['cancel_id']] = {}
                
            GLOBAL_TASKS[p_state['cancel_id']].update({
                'action': 'Upload', 'type': task_type, 'title': file_title,
                'since': get_readable_time(int(diff)), 'progress_bar': progress_bar,
                'percentage': f"{percentage:.2f}%", 'processed_label': "Processed_bytes",
                'processed': f"{get_readable_file_size(current)} of {get_readable_file_size(total)}",
                'speed': f"{get_readable_file_size(speed)}/s", 'machine': "Telegram API",
                'mode': dest_mode, 'cancel_id': p_state['cancel_id'],
                'dl_speed': f"{get_readable_file_size(speed_dl)}/s", 'ul_speed': f"{get_readable_file_size(speed)}/s",
                'speed_dl_raw': speed_dl, 'speed_ul_raw': speed,
                'user_id': p_state['msg'].chat.id if p_state['msg'] else 0,
                'timestamp': now
            })
        # -------------------------------------------------
        p_state['last_update_time'] = now

# ==========================================================
# SEND MESSAGE (RAPID & BERSIH)
# ==========================================================
async def send_message(user, text: str, type: str = 'text', markup=None, antiflood=False, meta=None, caption=None, progress=None, progress_args=None):
    if isinstance(user, Message):
        client = getattr(user, '_client', aio)
        chat_id = user.chat.id
    elif isinstance(user, dict):
        client = user.get('client', aio)
        chat_id = user.get('chat_id')
    else: return None

    if not client or not chat_id: return None

    if type == 'text':
        # Menerapkan iterasi untuk mencegah rekursi FloodWait
        for attempt in range(3):
            try:
                msg = await client.send_message(chat_id, text, reply_markup=markup)
                await copy_to_channel(client, msg)
                return msg
            except Exception as e:
                if "FloodWait" in str(e.__class__.__name__):
                    if antiflood:
                        wait_time = getattr(e, 'value', 0)
                        if wait_time > 300: return None
                        await asyncio.sleep(wait_time)
                        continue # Mengulang iterasi tanpa menambah tumpukan thread
                return None
        return None
    else:
        from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT, GLOBAL_TASKS
        start_time = time.time()
        
        if isinstance(user, dict) and user.get('bot_msg'):
            cancel_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        else:
            cancel_id = hashlib.md5(str(start_time).encode()).hexdigest()[:16]
            
        is_local = False
        if isinstance(text, str) and not text.startswith("http") and not text.startswith("tg://"):
            is_local = True
            
        p_state = {
            'msg': None, 'msg_created': False, 'start_time': start_time,
            'last_update_time': start_time, 'cancel_id': cancel_id,
            'is_local': is_local, 'chat_id': chat_id
        }
        
        # Iterasi aman untuk Upload Media
        for attempt in range(3):
            try:
                final_caption = caption if caption is not None else (meta.get('caption', '') if meta else '')
                thumb = meta.get('cover') if meta and meta.get('cover') else None
                task_type = "File" if type == 'doc' else type.capitalize()
                
                if progress is not None:
                    prog_func = progress
                    p_args = progress_args or ()
                else:
                    prog_func = standalone_local_progress if is_local else None
                    p_args = (p_state, user, text, task_type)

                res = None
                if type == 'audio':
                    res = await client.send_audio(chat_id, audio=text, caption=final_caption, duration=meta.get('duration', 0) if meta else 0, performer=meta.get('artist', '') if meta else '', title=meta.get('title', '') if meta else '', thumb=thumb, progress=prog_func, progress_args=p_args)
                elif type == 'doc':
                    res = await client.send_document(chat_id, document=text, caption=final_caption, thumb=thumb, progress=prog_func, progress_args=p_args)
                elif type in ['photo', 'pic']:
                    try: res = await client.send_photo(chat_id, photo=text, caption=final_caption, progress=prog_func, progress_args=p_args)
                    except Exception as pic_err:
                        if "IMAGE_PROCESS_FAILED" in str(pic_err) or "PHOTO_INVALID_DIMENSIONS" in str(pic_err):
                            res = await client.send_document(chat_id, document=text, caption=final_caption, progress=prog_func, progress_args=p_args)
                        else: raise pic_err
                elif type == 'video':
                    res = await client.send_video(chat_id, video=text, caption=final_caption, thumb=thumb, progress=prog_func, progress_args=p_args)
                else:
                    res = await client.send_document(chat_id, document=text, caption=final_caption, thumb=thumb, progress=prog_func, progress_args=p_args)
                    
                if res:
                    try: await copy_to_channel(client, res)
                    except: pass
                    
                # Pelindungan radar
                if p_state['msg']:
                    is_protected = False
                    if isinstance(user, dict):
                        if user.get('bot_msg') and p_state['msg'].id == user['bot_msg'].id: is_protected = True
                        if user.get('radar_msg') and p_state['msg'].id == user['radar_msg'].id: is_protected = True
                    if not is_protected:
                        try: await aio.delete_messages(chat_id, p_state['msg'].id)
                        except: pass

                return res

            except asyncio.CancelledError:
                GLOBAL_TASKS.pop(cancel_id, None)
                if p_state['msg']: 
                    try: await edit_message(p_state['msg'], "🛑 **Proses Upload Dibatalkan oleh Pengguna.**", None, False)
                    except: pass
                if isinstance(user, dict) and 'bot_msg' in user:
                    try: await edit_message(user['bot_msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                    except: pass
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
                
            except Exception as e:
                if cancel_id in GLOBAL_CANCEL_DICT or "DIBATALKAN_PENGGUNA" in str(e):
                    GLOBAL_TASKS.pop(cancel_id, None)
                    if p_state['msg']: 
                        try: await edit_message(p_state['msg'], "🛑 **Proses Upload Dibatalkan oleh Pengguna.**", None, False)
                        except: pass
                    if isinstance(user, dict) and 'bot_msg' in user:
                        try: await edit_message(user['bot_msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                        except: pass
                    raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
                    
                elif "FloodWait" in str(e.__class__.__name__):
                    wait_time = getattr(e, 'value', 0)
                    if wait_time > 300: 
                        GLOBAL_TASKS.pop(cancel_id, None)
                        return None
                    await asyncio.sleep(wait_time)
                    continue # Mengulang upload jika terkena tilang singkat
                else:
                    GLOBAL_TASKS.pop(cancel_id, None)
                    LOGGER.error(f"Gagal mengirim {type}: {e}")
                    if p_state['msg']: await edit_message(p_state['msg'], f"❌ **Gagal Mengunggah:** {e}", None, False)
                    return None
                    
        GLOBAL_TASKS.pop(cancel_id, None)
        return None

# ==========================================================
# EDIT MESSAGE
# ==========================================================
async def edit_message(msg: Message, text: str, markup=None, antiflood=True):
    if not msg: return None
    
    # Membungkus edit_message dalam iterasi aman
    for attempt in range(3):
        try:
            if msg._client and msg._client.is_connected:
                return await msg.edit_text(text=text, reply_markup=markup)
            elif aio.is_connected:
                return await aio.edit_message_text(chat_id=msg.chat.id, message_id=msg.id, text=text, reply_markup=markup)
            break
        except MessageNotModified: 
            break 
        except FloodWait as e:
            if antiflood:
                if e.value > 60: return None
                await asyncio.sleep(e.value)
                continue # Coba edit ulang setelah delay
            break
        except MessageIdInvalid:
            from bot.helpers.ui_manager import GLOBAL_UI_MSG, GLOBAL_UI_PAGES
            chat_id = msg.chat.id
            
            # --- [PERBAIKAN GHOST PANEL] ---
            # Pastikan pesan yang gagal diedit ADALAH pesan yang sedang aktif di memori.
            # Jika berbeda, biarkan memori Radar terbaru tetap hidup.
            current_radar = GLOBAL_UI_MSG.get(chat_id)
            if current_radar and current_radar.id == msg.id:
                GLOBAL_UI_MSG.pop(chat_id, None)
                GLOBAL_UI_PAGES.pop(chat_id, None)
            # -------------------------------
            break
        except RPCError as e:
            err_str = str(e)
            if any(err in err_str for err in ["INPUT_USER_DEACTIVATED", "USER_IS_BLOCKED", "PEER_ID_INVALID", "CHAT_WRITE_FORBIDDEN"]):
                try:
                    from bot.helpers.ui_manager import GLOBAL_UI_MSG, GLOBAL_UI_PAGES, GLOBAL_UI_LAST_UPDATE
                    chat_id = msg.chat.id
                    if chat_id in GLOBAL_UI_MSG: del GLOBAL_UI_MSG[chat_id]
                    if chat_id in GLOBAL_UI_PAGES: del GLOBAL_UI_PAGES[chat_id]
                    if msg.id in GLOBAL_UI_LAST_UPDATE: del GLOBAL_UI_LAST_UPDATE[msg.id]
                except: pass
            break
        except (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError, TimeoutError) as e:
            if "SSL shutdown" not in str(e): LOGGER.error(f"Connection Error Edit: {e}")
            break
        except Exception: 
            break
            
    return None
