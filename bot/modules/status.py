# [FILE: bot/modules/status.py]

import time
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
from bot.helpers.utils import GLOBAL_TASKS

def get_status_text(page=1, limit=5):
    # Bersihkan task yang nyangkut (tidak ada update lebih dari 2 menit)
    current_time = time.time()
    stale = [k for k, v in GLOBAL_TASKS.items() if current_time - v.get('timestamp', current_time) > 120]
    for k in stale:
        GLOBAL_TASKS.pop(k, None)

    tasks = list(GLOBAL_TASKS.values())
    if not tasks:
        return "💤 **Tidak ada task yang sedang berjalan saat ini.**", None
    
    total_tasks = len(tasks)
    max_pages = (total_tasks + limit - 1) // limit
    if page > max_pages: page = max_pages
    if page < 1: page = 1
    
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    tasks_page = tasks[start_idx:end_idx]
    
    text = f"**📊 GLOBAL STATUS (Page {page}/{max_pages})**\n\n"
    for i, t in enumerate(tasks_page, start=start_idx + 1):
        text += f"**{i:02d}. {t['action']} {t['type']}**: `{t['title']}`\n"
        text += f"**Since**: {t['since']}\n\n"
        text += f"**Progress**: `[{t['progress_bar']}]` {t['percentage']}\n"
        text += f"**{t['processed_label']}**: {t['processed']}\n"
        text += f"**Current_Speed**: {t['speed']}\n"
        text += f"**Machine_type**: {t['machine']}\n"
        text += f"**Destination_mode**: {t['mode']}\n"
        text += f"**Cancel**: /cancel_{t['cancel_id']}\n\n"
        text += f"🔻 {t['dl_speed']} | 🔺 {t['ul_speed']}\n"
        if i < end_idx and i < total_tasks:
            text += "➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
    
    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"status_page_{page-1}"))
    if page < max_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"status_page_{page+1}"))
    
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([
        InlineKeyboardButton("🔄 Refresh", callback_data=f"status_refresh_{page}"),
        InlineKeyboardButton("❌ Close", callback_data="status_close")
    ])
    
    return text, InlineKeyboardMarkup(buttons)

@Client.on_message(filters.command(["status"]))
async def status_command(client: Client, message: Message):
    text, markup = get_status_text(page=1)
    await message.reply(text, reply_markup=markup, disable_web_page_preview=True)

@Client.on_callback_query(filters.regex(r"^status_"))
async def status_callback(client: Client, query: CallbackQuery):
    data = query.data
    
    if data == "status_close":
        await query.message.delete()
        return
        
    if data.startswith("status_page_"):
        page = int(data.split("_")[-1])
        text, markup = get_status_text(page=page)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            pass
        await query.answer()
        
    elif data.startswith("status_refresh_"):
        page = int(data.split("_")[-1])
        text, markup = get_status_text(page=page)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            await query.answer("Status diperbarui!", show_alert=False)
        except Exception:
            await query.answer("Status sudah yang terbaru!", show_alert=False)
