# [FILE: bot/modules/status.py]

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

# Mengimpor GLOBAL_UI_MSG untuk menyambungkan kabel radar Papan Global
from bot.helpers.utils import get_status_text, GLOBAL_UI_MSG

@Client.on_message(filters.command(["task", "tasks"]))
async def task_command(client: Client, message: Message):
    # --- [FIX SPAM PAPAN GLOBAL] HAPUS PESAN LAMA JIKA ADA ---
    if message.chat.id in GLOBAL_UI_MSG:
        try:
            await GLOBAL_UI_MSG[message.chat.id].delete()
        except Exception:
            pass
    # ---------------------------------------------------------

    text, markup = get_status_text(page=1)
    
    # Menyimpan pesan yang dikirim bot ke dalam variabel
    sent_msg = await message.reply(text, reply_markup=markup, disable_web_page_preview=True)
    
    # Mendaftarkan pesan ini ke dalam memori Radar agar diperbarui secara real-time
    GLOBAL_UI_MSG[message.chat.id] = sent_msg

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
