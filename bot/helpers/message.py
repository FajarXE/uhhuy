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


async def send_message(user: dict, text: str, type: str = 'text', markup=None, antiflood=False, meta=None, caption=None):
    client = user.get('client', aio)
    chat_id = user['chat_id']
    if not client or not chat_id:
        return None

    if type == 'text':
        try:
            msg = await client.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)
            await copy_to_channel(client, msg)
            return msg
        except FloodWait as e:
            if antiflood:
                await asyncio.sleep(e.value)
                return await send_message(user, text, type, markup, antiflood, meta, caption)
        except Exception as e:
            LOGGER.error(f"Gagal mengirim teks: {e}")
            return None

    else:
        import time, hashlib, math
        from bot.helpers.utils import get_readable_time, get_readable_file_size, GLOBAL_CANCEL_DICT
        
        start_time = time.time()
        cancel_id = hashlib.md5(str(start_time).encode()).hexdigest()[:16]
        last_update_time = start_time
        
        msg = await client.send_message(chat_id, f"🔄 Menyiapkan Upload... `/cancel_{cancel_id}`")

        async def progress(current, total):
            nonlocal last_update_time
            if cancel_id in GLOBAL_CANCEL_DICT:
                raise Exception("DIBATALKAN_PENGGUNA")

            now = time.time()
            if now - last_update_time > 2.5 or current == total:
                diff = now - start_time
                if diff < 1: diff = 1
                
                speed = current / diff
                percentage = (current / total) * 100 if total > 0 else 0
                
                filled_blocks = math.floor((percentage / 100) * 12)
                empty_blocks = 12 - filled_blocks
                progress_bar = "◙" * filled_blocks + "◘" * empty_blocks
                
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

                text_to_send = f"**{action} {task_type}**: `{file_title}`\n"
                text_to_send += f"**Since**: {since_str}\n\n"
                text_to_send += f"**Progress**: `[{progress_bar}]` {percentage:.2f}%\n"
                text_to_send += f"**Processed_bytes**: {done_str} of {total_str}\n"
                text_to_send += f"**Current_Speed**: {speed_str} | **ETA**: {eta_str}\n"
                text_to_send += f"**Machine_type**: Telegram API\n"
                text_to_send += f"**Destination_mode**: {dest_mode}\n"
                text_to_send += f"**Cancel**: /cancel_{cancel_id}\n"

                try:
                    await edit_message(msg, text_to_send, None, False)
                except MessageNotModified: pass
                except FloodWait: pass
                last_update_time = now

        try:
            # --- PERBAIKAN DI SINI ---
            # Mengutamakan parameter 'caption', baru kemudian membaca dari 'meta'
            final_caption = caption if caption is not None else (meta.get('caption', '') if meta else '')
            thumb = meta.get('cover') if meta and meta.get('cover') else None
            
            if type == 'audio':
                duration = meta.get('duration', 0) if meta else 0
                performer = meta.get('artist', '') if meta else ''
                audio_title = meta.get('title', '') if meta else ''
                
                res = await client.send_audio(
                    chat_id, audio=text, caption=final_caption, duration=duration,
                    performer=performer, title=audio_title, thumb=thumb, progress=progress
                )
            elif type == 'doc':
                res = await client.send_document(
                    chat_id, document=text, caption=final_caption, thumb=thumb, progress=progress
                )
            elif type == 'photo':
                res = await client.send_photo(
                    chat_id, photo=text, caption=final_caption, progress=progress
                )
            elif type == 'video':
                res = await client.send_video(
                    chat_id, video=text, caption=final_caption, thumb=thumb, progress=progress
                )
                
            await copy_to_channel(client, res)
            await aio.delete_messages(chat_id, msg.id)
            return res

        except Exception as e:
            if str(e) == "DIBATALKAN_PENGGUNA":
                await edit_message(msg, "🛑 **Proses Upload Dibatalkan oleh Pengguna.**")
            else:
                LOGGER.error(f"Gagal mengirim {type}: {e}")
                await edit_message(msg, f"❌ **Gagal Mengunggah:** {e}")
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
