# [FILE: bot/modules/status.py]

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message
from bot.helpers.utils import get_status_text

@Client.on_message(filters.command(["task", "tasks"]))
async def task_command(client: Client, message: Message):
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
