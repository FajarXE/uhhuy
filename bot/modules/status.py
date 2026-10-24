# [GANTI TOTAL ISI FILE: bot/modules/status.py]

import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message
from pyrogram.errors import FloodWait, MessageNotModified

from bot.helpers.ui_manager import (
    get_status_text,
    GLOBAL_UI_MSG,
    GLOBAL_UI_PAGES,
    GLOBAL_UI_LAST_TEXT,
    GLOBAL_TASKS
)
from bot.logger import LOGGER
from bot.helpers.database.mongo_async import database

@Client.on_message(filters.command(["task", "tasks"]))
async def task_command(client: Client, message: Message):
    chat_id = message.chat.id
    
    # --- HAPUS PESAN RADAR LAMA JIKA ADA ---
    old_msg = GLOBAL_UI_MSG.pop(chat_id, None)
    GLOBAL_UI_LAST_TEXT.pop(chat_id, None)
    if old_msg:
        try:
            await client.delete_messages(chat_id, old_msg.id)
        except Exception:
            pass
    # ---------------------------------------

    GLOBAL_UI_PAGES[chat_id] = 1
    text, markup = await get_status_text(page=1)
    
    try:
        sent_msg = await message.reply_text(text, reply_markup=markup)
        
        # Hanya daftarkan ke Radar & MongoDB jika memang ada task yang sedang berjalan
        if GLOBAL_TASKS:
            GLOBAL_UI_MSG[chat_id] = sent_msg
            GLOBAL_UI_LAST_TEXT[chat_id] = text
            await database.save_ui_state(chat_id, sent_msg.id, 1)
        else:
            GLOBAL_UI_PAGES.pop(chat_id, None)
            await database.remove_ui_state(chat_id)
        
    except FloodWait as e:
        LOGGER.warning(f"Terkena FloodWait {e.value} detik saat mengirim /task.")
        await asyncio.sleep(e.value)
        try:
            sent_msg = await message.reply_text(text, reply_markup=markup)
            if GLOBAL_TASKS:
                GLOBAL_UI_MSG[chat_id] = sent_msg
                GLOBAL_UI_LAST_TEXT[chat_id] = text
                await database.save_ui_state(chat_id, sent_msg.id, 1)
        except Exception:
            pass
    except Exception as e:
        LOGGER.error(f"Gagal mengirim /task: {e}")

@Client.on_callback_query(filters.regex(r"^status_"))
async def status_callback(client: Client, query: CallbackQuery):
    data = query.data
    chat_id = query.message.chat.id
    
    if data == "status_close":
        try:
            await query.message.delete()
        except Exception:
            pass
            
        GLOBAL_UI_MSG.pop(chat_id, None)
        GLOBAL_UI_PAGES.pop(chat_id, None)
        GLOBAL_UI_LAST_TEXT.pop(chat_id, None)
        await database.remove_ui_state(chat_id)
        return
        
    if data.startswith("status_page_"):
        page = int(data.split("_")[-1])
        old_page = GLOBAL_UI_PAGES.get(chat_id, 1)
        GLOBAL_UI_PAGES[chat_id] = page
        
        if GLOBAL_TASKS:
            await database.save_ui_state(chat_id, query.message.id, page)
        
        text, markup = await get_status_text(page=page)
        try:
            await query.message.edit_text(text, reply_markup=markup)
            GLOBAL_UI_LAST_TEXT[chat_id] = text
            try:
                await query.answer()
            except Exception:
                pass
        except FloodWait as e:
            try:
                await query.answer(f"⏳ Terlalu cepat! Tunggu {e.value} detik.", show_alert=True)
            except Exception:
                pass
            
            # Kembalikan ke halaman sebelumnya karena edit gagal
            GLOBAL_UI_PAGES[chat_id] = old_page
            if GLOBAL_TASKS:
                try:
                    await database.save_ui_state(chat_id, query.message.id, old_page)
                except Exception:
                    pass
        except MessageNotModified:
            GLOBAL_UI_LAST_TEXT[chat_id] = text
            try:
                await query.answer()
            except Exception:
                pass
        except Exception:
            pass
            
    elif data.startswith("status_refresh_"):
        page = int(data.split("_")[-1])
        GLOBAL_UI_PAGES[chat_id] = page
        
        text, markup = await get_status_text(page=page)
        try:
            await query.message.edit_text(text, reply_markup=markup)
            GLOBAL_UI_LAST_TEXT[chat_id] = text
            await query.answer("Status diperbarui!", show_alert=False)
        except FloodWait as e:
            try:
                await query.answer(f"⏳ Terlalu cepat! Tunggu {e.value} detik.", show_alert=True)
            except Exception:
                pass
        except MessageNotModified:
            GLOBAL_UI_LAST_TEXT[chat_id] = text
            try:
                await query.answer("Status sudah yang terbaru!", show_alert=False)
            except Exception:
                pass
        except Exception:
            pass
