# [FILE: bot/helpers/message.py]

import os
import asyncio
import time
import math
import traceback 
import aiohttp 

from pyrogram.types import Message
from pyrogram.errors import MessageNotModified, FloodWait, MessageIdInvalid, RPCError

# Impor global client untuk fallback
from bot.tgclient import aio
from bot.settings import bot_set
from bot.logger import LOGGER
from config import Config # Butuh Config untuk COPY_CHANNEL_ID

current_user = []

user_details = {
    'user_id': None,
    'name': None, 
    'user_name': None, 
    'r_id': None, 
    'chat_id': None,
    'provider': None,
    'bot_msg': None,
    'link': None,
    'override' : None 
}

# --- FITUR BARU: COPY TO CHANNEL ---
async def copy_to_channel(client, message: Message):
    """
    Menyalin pesan yang dikirim bot ke Channel yang dikonfigurasi.
    """
    # Pastikan ID Channel ada dan Valid (Bukan 0)
    copy_target = Config.COPY_CHANNEL_ID
    if not copy_target or copy_target == 0:
        return

    try:
        # Gunakan client yang sama dengan pengirim pesan
        await message.copy(copy_target)
    except Exception as e:
        LOGGER.error(f"Gagal menyalin pesan ke channel {copy_target}: {e}")

# -----------------------------------

async def fetch_user_details(msg: Message, reply=False) -> dict:
    details = user_details.copy()
    details['user_id'] = msg.from_user.id
    details['name'] = msg.from_user.first_name
    if msg.from_user.username:
        details['user_name'] = msg.from_user.username
    else:
        details['user_name'] = msg.from_user.mention()
    details['r_id'] = msg.reply_to_message.id if reply else msg.id
    details['chat_id'] = msg.chat.id
    try:
        details['bot_msg'] = msg
    except:
        pass
    return details


async def check_user(uid=None, msg=None, restricted=False) -> bool:
    # 1. Menentukan ID user yang valid (dari parameter uid atau objek msg)
    actual_uid = uid if uid else (msg.from_user.id if msg and msg.from_user else None)

    # --- [FITUR BARU] LAZY LOADING USER DATA + LRU CACHE ---
    if actual_uid and actual_uid not in bot_set.user_data:
        from bot.helpers.database.mongo_async import database
        user_db_data = await database.get_user_settings(actual_uid)
        
        # Simpan ke cache RAM (Otomatis ditangani oleh LRUCache agar tidak luber)
        bot_set.user_data[actual_uid] = user_db_data or {}

        # Sinkronkan preferensi kualitas audio ke API Manager secara instan
        if user_db_data:
            import asyncio
            asyncio.create_task(sync_single_user_managers(actual_uid, user_db_data))
    # -------------------------------------------------------

    # 2. Logika otorisasi bawaan
    if restricted:
        if uid in bot_set.admins:
            return True
    else:
        if bot_set.bot_public:
            return True
        else:
            all_chats = list(bot_set.admins) + bot_set.auth_chats + bot_set.auth_users 
            if msg and msg.from_user and msg.from_user.id in all_chats:
                return True
            elif msg and msg.chat and msg.chat.id in all_chats:
                return True
    return False

# --- HELPER: SINKRONISASI MANAGER JIT ---
async def sync_single_user_managers(user_id, data):
    """Menyuntikkan pengaturan kualitas user ke manajer musik secara dinamis"""
    try:
        def safe_import_mgr(path, name):
            try:
                mod = __import__(path, fromlist=[name])
                return getattr(mod, name)
            except: 
                return None

        # Daftar lengkap semua manager (Future-Proof)
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
            'khinsider_qual': safe_import_mgr('bot.helpers.khinsider.manager', 'khinsider_manager'),
            'amazon_qual': safe_import_mgr('bot.helpers.amazon.manager', 'amazon_manager'),
            'genie_qual': safe_import_mgr('bot.helpers.genie.manager', 'genie_manager'),
        }
        
        for key, manager in settings_map.items():
            # Hanya jalankan jika user punya settingnya DAN manager mendukungnya
            if data.get(key) and manager and hasattr(manager, 'setup_quality'):
                try: await manager.setup_quality(user_id, data[key])
                except Exception: pass

        # Penanganan khusus Qobuz (karena menggunakan struktur dictionary)
        if data.get('qobuz_qual'):
            from bot import BOT_QOBUZ_CLIENTS
            if BOT_QOBUZ_CLIENTS:
                qobuz_interface = list(BOT_QOBUZ_CLIENTS.values())[0]
                if hasattr(qobuz_interface, 'setup_quality'):
                    try: await qobuz_interface.setup_quality(user_id, data['qobuz_qual'])
                    except Exception: pass
                    
    except Exception as e:
        from bot.logger import LOGGER
        LOGGER.debug(f"Gagal sinkronisasi manager JIT: {e}")
# ----------------------------------------


async def antiSpam(uid=None, cid=None, revoke=False) -> bool:
    if revoke:
        if bot_set.anti_spam == 'CHAT+':
            if cid in current_user:
                current_user.remove(cid)
        elif bot_set.anti_spam == 'USER':
            if uid in current_user:
                current_user.remove(uid)
    else:
        if bot_set.anti_spam == 'CHAT+':
            if cid in current_user:
                return True
            else:
                current_user.append(cid)
        elif bot_set.anti_spam == 'USER':
            if uid in current_user:
                return True
            else:
                current_user.append(uid)
        return False

# --- [PERBAIKAN] MENAMBAHKAN PARAMETER progress DAN progress_args ---
async def send_message(user, text: str, type: str = 'text', markup=None, antiflood=False, meta=None, caption=None, progress=None, progress_args=None):
    # [FIX] Import asyncio diletakkan di paling atas agar dikenali seluruh blok kode!
    import asyncio
    from pyrogram.types import Message
    from bot.tgclient import aio
    
    if isinstance(user, Message):
        client = getattr(user, '_client', aio)
        chat_id = user.chat.id
    elif isinstance(user, dict):
        client = user.get('client', aio)
        chat_id = user.get('chat_id')
    else:
        return None

    if not client or not chat_id:
        return None

    if type == 'text':
        try:
            msg = await client.send_message(chat_id, text, reply_markup=markup)
            from bot.helpers.message import copy_to_channel
            await copy_to_channel(client, msg)
            return msg
        except Exception as e:
            if "FloodWait" in str(type(e).__name__):
                if antiflood:
                    await asyncio.sleep(e.value)
                    return await send_message(user, text, type, markup, antiflood, meta, caption, progress, progress_args)
            else:
                from bot.logger import LOGGER
                LOGGER.error(f"Gagal mengirim teks: {e}")
            return None

    else:
        import time, hashlib, math, os
        from bot.helpers.utils import get_readable_time, get_readable_file_size, GLOBAL_CANCEL_DICT
        from bot.settings import bot_set
        
        start_time = time.time()
        
        # --- [TRANSISI MULUS] GUNAKAN ID PESAN ASLI ---
        if isinstance(user, dict) and user.get('bot_msg'):
            cancel_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        else:
            cancel_id = hashlib.md5(str(start_time).encode()).hexdigest()[:16]
        # ----------------------------------------------
        
        last_update_time = start_time
        
        is_local = False
        if isinstance(text, str):
            try:
                # Membaca path lokal untuk trigger radar UI
                if not text.startswith("http") and not text.startswith("tg://"):
                    is_local = True
            except: pass
            
        msg = None
        msg_created = False 

                # --- [PERBAIKAN] MENGUBAH NAMA PROGRESS INTERNAL AGAR TIDAK BENTROK ---
        async def internal_progress(current, total):
            nonlocal msg, last_update_time, msg_created, start_time 
            if cancel_id in GLOBAL_CANCEL_DICT:
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")

            # --- [FIX UI] TAKTIK RADAR PERMANEN (ANTI-LOMPAT) ---
            if is_local and not msg_created:
                msg_created = True
                start_time = time.time() # Reset stopwatch agar kecepatan akurat
                last_update_time = start_time 
                
                if isinstance(user, dict):
                    # 1. Jika radar permanen sudah dibuat di lagu sebelumnya, pakai itu terus!
                    if user.get('radar_msg'):
                        msg = user['radar_msg']
                    # 2. Jika belum ada, coba pakai bot_msg
                    elif user.get('bot_msg'):
                        msg = user['bot_msg']
                        user['radar_msg'] = msg # Simpan di memori
                    # 3. Jika bot_msg ternyata sudah dihapus oleh sistem uploader, BUAT BARU SEKALI SAJA!
                    else:
                        try:
                            from bot.tgclient import aio
                            msg = await aio.send_message(chat_id, f"🔄 Mengunggah file... `/cancel_{cancel_id}`")
                            user['radar_msg'] = msg # Kunci pesan ini di memori!
                        except: pass
            # ---------------------------------------------------
                
            if not msg:
                return 

            now = time.time()
            import random
            
            # Cukup hitung kalkulasi 1-2 detik sekali, UI diurus Mandor!
            delay = 1.5
            if msg and (now - last_update_time > delay or current == total):
                diff = now - start_time
                if diff < 1: diff = 1
                
                speed = current / diff
                percentage = (current / total) * 100 if total > 0 else 0
                
                filled_blocks = math.floor((percentage / 100) * 12)
                empty_blocks = 12 - filled_blocks
                progress_bar = "■" * filled_blocks + "□" * empty_blocks
                
                done_str = get_readable_file_size(current)
                total_str = get_readable_file_size(total)
                speed_str = f"{get_readable_file_size(speed)}/s"
                eta_seconds = int((total - current) / speed) if speed > 0 else 0
                eta_str = get_readable_time(eta_seconds) if eta_seconds > 0 else "-"
                since_str = get_readable_time(int(diff))
                
                try: dest_mode = bot_set.user_data.get(chat_id, {}).get('upload_mode', bot_set.upload_mode)
                except: dest_mode = bot_set.upload_mode

                file_title = os.path.basename(text) if isinstance(text, str) else "Unknown File"
                action = "Upload"
                task_type = "File" if type == 'doc' else type.capitalize()

                try:
                    from bot.helpers.aria2_helper import get_aria2_global_stat
                    stats = await get_aria2_global_stat()
                    speed_dl = int(stats.get('downloadSpeed', 0)) if stats else 0
                except:
                    speed_dl = 0
                    
                # Injeksi kecepatan Deezer jika ada (aman dari error)
                try:
                    from bot.helpers.deezer.dzapi import get_deezer_speed
                    dz_spd = get_deezer_speed()
                    if dz_spd > 0: speed_dl += dz_spd
                except: pass
                
                speed_ul = speed

                # --- TAMBAHKAN UPDATE KE GLOBAL_TASKS DI SINI ---
                try:
                    from bot.helpers.utils import GLOBAL_TASKS
                    GLOBAL_TASKS[cancel_id] = {
                        'action': action,
                        'type': task_type,
                        'title': file_title,
                        'since': since_str,
                        'progress_bar': progress_bar,
                        'percentage': f"{percentage:.2f}%",
                        'processed_label': "Processed_bytes",
                        'processed': f"{done_str} of {total_str}",
                        'speed': speed_str,
                        'machine': "Telegram API",
                        'mode': dest_mode,
                        'cancel_id': cancel_id,
                        'dl_speed': f"{get_readable_file_size(speed_dl)}/s",
                        'ul_speed': f"{get_readable_file_size(speed_ul)}/s",
                        'speed_dl_raw': speed_dl,
                        'speed_ul_raw': speed_ul,
                        'user_id': msg.chat.id if msg else 0,
                        'timestamp': now
                    }
                except Exception:
                    pass
                # ------------------------------------------------
                
                last_update_time = now

        try:
            res = None 
            final_caption = caption if caption is not None else (meta.get('caption', '') if meta else '')
            thumb = meta.get('cover') if meta and meta.get('cover') else None
            
            # --- [PERBAIKAN] MENENTUKAN KABEL SENSOR MANA YANG DIPAKAI ---
            if progress is not None:
                prog_func = progress
                p_args = progress_args or ()
            else:
                prog_func = internal_progress if is_local else None
                p_args = ()
            # -------------------------------------------------------------
            
            if type == 'audio':
                duration = meta.get('duration', 0) if meta else 0
                performer = meta.get('artist', '') if meta else ''
                audio_title = meta.get('title', '') if meta else ''
                res = await client.send_audio(chat_id, audio=text, caption=final_caption, duration=duration, performer=performer, title=audio_title, thumb=thumb, progress=prog_func, progress_args=p_args)
            
            elif type == 'doc':
                res = await client.send_document(chat_id, document=text, caption=final_caption, thumb=thumb, progress=prog_func, progress_args=p_args)
            
            elif type in ['photo', 'pic']:
                try:
                    # Langkah 1: Coba kirim sebagai Foto/Gambar standar
                    res = await client.send_photo(chat_id, photo=text, caption=final_caption, progress=prog_func, progress_args=p_args)
                except Exception as pic_err:
                    # Langkah 2: Jika server Telegram menolak karena ukurannya raksasa, kirim sebagai File Dokumen
                    if "IMAGE_PROCESS_FAILED" in str(pic_err) or "PHOTO_INVALID_DIMENSIONS" in str(pic_err):
                        from bot.logger import LOGGER
                        LOGGER.warning(f"Telegram menolak foto ({pic_err}), mengalihkan ke mode Dokumen.")
                        res = await client.send_document(chat_id, document=text, caption=final_caption, progress=prog_func, progress_args=p_args)
                    else:
                        raise pic_err # Lempar error jika masalahnya hal lain (seperti koneksi putus)
            
            elif type == 'video':
                res = await client.send_video(chat_id, video=text, caption=final_caption, thumb=thumb, progress=prog_func, progress_args=p_args)
            
            else:
                res = await client.send_document(chat_id, document=text, caption=final_caption, thumb=thumb, progress=prog_func, progress_args=p_args)
                
            if res:
                try:
                    from bot.helpers.message import copy_to_channel
                    await copy_to_channel(client, res)
                except: pass
                
            # --- [FIX UI] LINDUNGI RADAR AGAR TIDAK DIHAPUS ---
            if msg:
                is_protected = False
                if isinstance(user, dict):
                    if user.get('bot_msg') and msg.id == user['bot_msg'].id:
                        is_protected = True
                    if user.get('radar_msg') and msg.id == user['radar_msg'].id:
                        is_protected = True
                
                if not is_protected:
                    from bot.tgclient import aio
                    try: 
                        await aio.delete_messages(chat_id, msg.id)
                    except Exception as e: 
                        from bot.logger import LOGGER
                        LOGGER.debug(f"Gagal menghapus pesan pelindung radar {msg.id}: {e}")
            # --------------------------------------------------

            return res

        # [FIX] Tangkap CancelledError, update Radar UI, update pesan "UPLOADING...", lalu lempar sinyal!
        except asyncio.CancelledError:
            # --- CLEANUP GLOBAL TASKS ---
            try:
                from bot.helpers.utils import GLOBAL_TASKS
                GLOBAL_TASKS.pop(cancel_id, None)
            except Exception: pass
            # ----------------------------

            from bot.helpers.message import edit_message
            if msg: await edit_message(msg, "🛑 **Proses Upload Dibatalkan oleh Pengguna.**", None, False)
            
            # --- MENGHAPUS PESAN "UPLOADING..." YANG NYANGKUT ---
            if isinstance(user, dict) and 'bot_msg' in user:
                try: await edit_message(user['bot_msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                except: pass
            
            # Lempar sinyal ke sistem utama (agar sistem utama yg mengirim 1x pesan "Tugas Dibatalkan")
            raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
            
        except Exception as e:
            # --- CLEANUP GLOBAL TASKS ---
            try:
                from bot.helpers.utils import GLOBAL_TASKS
                GLOBAL_TASKS.pop(cancel_id, None)
            except Exception: pass
            # ----------------------------

            from bot.helpers.message import edit_message
            if cancel_id in GLOBAL_CANCEL_DICT or "DIBATALKAN_PENGGUNA" in str(e):
                if msg: await edit_message(msg, "🛑 **Proses Upload Dibatalkan oleh Pengguna.**", None, False)
                
                # --- MENGHAPUS PESAN "UPLOADING..." YANG NYANGKUT ---
                if isinstance(user, dict) and 'bot_msg' in user:
                    try: await edit_message(user['bot_msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                    except: pass
                
                # Lempar sinyal ke sistem utama
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
                
            # --- [FIX BUG LAGU HILANG & FLOODWAIT BATCH MEDIA] ---
            elif "FloodWait" in str(type(e).__name__):
                if hasattr(e, 'value'):
                    from bot.logger import LOGGER
                    import asyncio
                    
                    # --- [FIX] JANGAN TIDUR JIKA TILANG LEBIH DARI 5 MENIT ---
                    if e.value > 300:
                        LOGGER.warning(f"⚠️ FloodWait ekstrim ({e.value}s). Lagu dilewati agar playlist tidak mati!")
                        return None
                    # ---------------------------------------------------------
                    
                    LOGGER.warning(f"⏳ File tertunda limit Telegram ({e.value}s). Menunggu agar tidak ada lagu yang terlewat...")
                    await asyncio.sleep(e.value)
                    # Ulangi pengiriman file ini setelah tidur selesai
                    return await send_message(user, text, type, markup, antiflood, meta, caption, progress, progress_args)
            # -----------------------------------------------------
            
            else:
                from bot.logger import LOGGER
                LOGGER.error(f"Gagal mengirim {type}: {e}")
                if msg: await edit_message(msg, f"❌ **Gagal Mengunggah:** {e}", None, False)
            return None

# --- FUNGSI EDIT MESSAGE (VERSI ANTI-CRASH) ---
async def edit_message(msg: Message, text: str, markup=None, antiflood=True):
    """
    Mengedit pesan dengan penanganan khusus untuk error SSL Shutdown 
    dan pembersihan memori hantu (Anti I/O Bottleneck).
    """
    if not msg:
        return None

    try:
        # Coba edit langsung dari objek pesan
        if msg._client and msg._client.is_connected:
            return await msg.edit_text(
                text=text,
                reply_markup=markup
            )
        
        # Fallback ke Klien Global (aio)
        elif aio.is_connected:
            return await aio.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.id,
                text=text,
                reply_markup=markup
            )

    except MessageNotModified:
        pass # Pesan sama, abaikan
    except FloodWait as e:
        if antiflood:
            # --- FIX: JANGAN TIDUR JIKA TILANG TERLALU LAMA ---
            if e.value > 60:
                LOGGER.warning(f"⚠️ FloodWait ekstrim ({e.value}s) diabaikan agar antrean tidak hang.")
                return None
            
            import asyncio
            LOGGER.warning(f"⏳ Menunggu FloodWait {e.value} detik untuk edit pesan...")
            await asyncio.sleep(e.value)
            return await edit_message(msg, text, markup, antiflood)
            
    except MessageIdInvalid:
        # --- FIX: BERSIHKAN PESAN MATI DARI MEMORI RADAR ---
        from bot.helpers.utils import GLOBAL_UI_MSG, GLOBAL_UI_PAGES
        chat_id = msg.chat.id
        GLOBAL_UI_MSG.pop(chat_id, None)
        GLOBAL_UI_PAGES.pop(chat_id, None)
        pass # Pesan sudah hilang dan berhasil diamankan
    except RPCError as e:
        # Error umum Telegram
        LOGGER.warning(f"RPCError Edit: {e}")
        
        # --- FIX: Pembersihan "Memori Hantu" untuk mencegah I/O Bottleneck ---
        err_str = str(e)
        if any(err in err_str for err in ["INPUT_USER_DEACTIVATED", "USER_IS_BLOCKED", "PEER_ID_INVALID", "CHAT_WRITE_FORBIDDEN"]):
            try:
                from bot.helpers.utils import GLOBAL_UI_MSG, GLOBAL_UI_PAGES, GLOBAL_UI_LAST_UPDATE
                chat_id = msg.chat.id
                
                # Hapus dari semua radar Global Status
                if chat_id in GLOBAL_UI_MSG:
                    del GLOBAL_UI_MSG[chat_id]
                if chat_id in GLOBAL_UI_PAGES:
                    del GLOBAL_UI_PAGES[chat_id]
                if msg.id in GLOBAL_UI_LAST_UPDATE:
                    del GLOBAL_UI_LAST_UPDATE[msg.id]
                    
                LOGGER.info(f"🧹 Membersihkan User {chat_id} dari radar UI karena akun tidak aktif/diblokir.")
            except Exception as cleanup_err:
                LOGGER.debug(f"Gagal membersihkan radar: {cleanup_err}")
                
    except (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError, TimeoutError) as e:
        # [DEBUG] Tangkap Error SSL di sini agar tidak jadi 'Future exception'
        if "SSL shutdown" in str(e):
            # LOGGER.debug("SSL Shutdown ignored during edit_message")
            pass
        else:
            LOGGER.error(f"Connection Error Edit: {e}")
    except Exception as e:
        LOGGER.error(f"Error Edit Message: {e}")
        return None
