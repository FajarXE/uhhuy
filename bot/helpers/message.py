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
    if restricted:
        if uid in bot_set.admins:
            return True
    else:
        if bot_set.bot_public:
            return True
        else:
            all_chats = list(bot_set.admins) + bot_set.auth_chats + bot_set.auth_users 
            if msg.from_user.id in all_chats:
                return True
            elif msg.chat.id in all_chats:
                return True
    return False


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


async def send_message(user, item, itype='text',
    caption=None, markup=None, chat_id=None,
    meta=None, thumb=None
  ):
    if not isinstance(user, dict):
        user = await fetch_user_details(user)
    
    # [LOGIKA DIRECT TO CHANNEL]
    # Tentukan target chat ID
    target_chat_id = chat_id if chat_id else user['chat_id']
    original_chat_id = target_chat_id
    
    # Jika mode Direct aktif dan Channel ID valid, kirim ke Channel
    is_direct_mode = Config.DIRECT_TO_CHANNEL and Config.COPY_CHANNEL_ID
    if is_direct_mode:
        target_chat_id = Config.COPY_CHANNEL_ID
    
    # Tentukan pesan mana yang di-reply
    reply_to_id = user['r_id']
    if is_direct_mode:
        reply_to_id = None # Tidak bisa reply pesan user di channel

    sent_msg = None

    try:
        if itype == 'text':
            sent_msg = await aio.send_message(
                chat_id=target_chat_id,
                text=item,
                reply_to_message_id=reply_to_id,
                reply_markup=markup,
                disable_web_page_preview=True
            )
            
        elif itype == 'doc':
            # Logika Thumb Lama Anda
            thumb_path = thumb 
            if not thumb_path and meta:
                thumb_path = meta.get('thumbnail') or meta.get('cover')
            
            if thumb_path and not os.path.exists(thumb_path):
                thumb_path = None
            
            # Progress Callback (Hanya jika kirim ke User, agar tidak spam edit di channel)
            progress_callback = None
            if not is_direct_mode:
                last_update_time = [0] 
                async def doc_progress(current, total):
                    current_time = time.time()
                    if current_time - last_update_time[0] < 5: return
                    last_update_time[0] = current_time
                    percentage = int((current / total) * 100)
                    progress_bar = "{0}{1}".format(
                        ''.join(["▰" for i in range(math.floor(percentage / 10))]),
                        ''.join(["▱" for i in range(10 - math.floor(percentage / 10))])
                    )
                    try:
                        text = (f"**Mengunggah file .zip...**\n`{os.path.basename(item)}`\n\n{progress_bar} {percentage}%")
                        asyncio.create_task(edit_message(user['bot_msg'], text, antiflood=False))
                    except: pass
                progress_callback = doc_progress
            
            sent_msg = await aio.send_document(
                chat_id=target_chat_id,
                document=item,
                caption=caption,
                reply_to_message_id=reply_to_id,
                thumb=thumb_path,
                progress=progress_callback
            )

        elif itype == 'audio':
            thumb_path = None
            cover_candidate = meta.get('cover') or meta.get('thumbnail')
            if cover_candidate and isinstance(cover_candidate, str):
                if os.path.exists(cover_candidate):
                    thumb_path = cover_candidate
            
            duration = 0
            raw_duration = meta.get('duration')
            if raw_duration:
                try: duration = int(float(str(raw_duration)))
                except: duration = 0

            # Progress Callback (Hanya jika kirim ke User)
            progress_callback = None 
            if not is_direct_mode and meta and not meta.get('batch_mode', False) and user.get('bot_msg'):
                last_update_time = [0]
                async def audio_progress(current, total):
                    current_time = time.time()
                    if current_time - last_update_time[0] < 5: return
                    last_update_time[0] = current_time
                    percentage = int((current / total) * 100)
                    progress_bar = "{0}{1}".format(
                        ''.join(["▰" for i in range(math.floor(percentage / 10))]),
                        ''.join(["▱" for i in range(10 - math.floor(percentage / 10))])
                    )
                    try:
                        track_num = meta.get('tracknumber', '?')
                        total_tracks = meta.get('totaltracks', '?')
                        title = meta.get('title', 'Unknown Track')
                        text = (f"**Mengunggah...**\nLagu {track_num} dari {total_tracks}\n`{title}`\n\n{progress_bar} {percentage}%")
                        asyncio.create_task(edit_message(user['bot_msg'], text, antiflood=False))
                    except Exception: pass
                progress_callback = audio_progress 
            
            sent_msg = await aio.send_audio(
                chat_id=target_chat_id,
                audio=item,
                caption=caption,
                duration=duration,
                performer=meta.get('artist'),
                title=meta.get('title'),
                thumb=thumb_path, 
                reply_to_message_id=reply_to_id,
                progress=progress_callback
            )

        elif itype == 'pic':
            sent_msg = await aio.send_photo(
                chat_id=target_chat_id,
                photo=item,
                caption=caption,
                reply_to_message_id=reply_to_id
            )

        # [LOGIKA COPY TO CHANNEL]
        # Jika Direct Mode MATI (User sudah terima file),
        # DAN Channel ID ada, maka COPY file tersebut ke Channel
        if sent_msg and not is_direct_mode and Config.COPY_CHANNEL_ID:
            # Hanya copy file media penting (Audio/Doc/Pic)
            if itype in ['audio', 'doc', 'pic']:
                 await copy_to_channel(aio, sent_msg)
        
        return sent_msg

    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await send_message(user, item, itype, caption, markup, chat_id, meta, thumb)
        
    except Exception as e:
        LOGGER.error(f"Send Message Error: {e}")
        # Fallback: Jika gagal kirim ke Channel (misal bot dikick), coba kirim ke User
        if is_direct_mode and target_chat_id != original_chat_id:
            LOGGER.info("Fallback: Mengirim ulang ke User karena gagal kirim ke Channel...")
            # Matikan direct mode sementara untuk pemanggilan rekursif ini
            Config.DIRECT_TO_CHANNEL = False 
            return await send_message(user, item, itype, caption, markup, original_chat_id, meta, thumb)
        return None


# --- FUNGSI EDIT MESSAGE (VERSI ANTI-CRASH) ---
async def edit_message(msg: Message, text: str, markup=None, antiflood=True):
    """
    Mengedit pesan dengan penanganan khusus untuk error SSL Shutdown.
    """
    if not msg:
        return None

    try:
        # Coba edit langsung dari objek pesan
        if msg._client and msg._client.is_connected:
            return await msg.edit_text(
                text=text,
                reply_markup=markup,
                disable_web_page_preview=True
            )
        
        # Fallback ke Klien Global (aio)
        elif aio.is_connected:
            return await aio.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.id,
                text=text,
                reply_markup=markup,
                disable_web_page_preview=True
            )

    except MessageNotModified:
        pass # Pesan sama, abaikan
    except FloodWait as e:
        if antiflood:
            await asyncio.sleep(e.value)
            return await edit_message(msg, text, markup, antiflood)
    except MessageIdInvalid:
        pass # Pesan sudah hilang
    except RPCError as e:
        # Error umum Telegram
        LOGGER.warning(f"RPCError Edit: {e}")
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
