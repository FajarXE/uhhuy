# [GANTI DI DALAM FILE: bot/modules/cancel.py]

import re
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.helpers.aria2_helper import aria2_cancel, ACTIVE_DOWNLOADS
from bot.settings import bot_set

# Menggunakan Regex untuk menangkap perintah yang menyatu dengan ID
@Client.on_message(filters.regex(r"^/cancel_([a-zA-Z0-9]+)"))
async def cancel_task_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if not bot_set.bot_public and user_id not in bot_set.auth_users and user_id not in bot_set.admins:
        return
    
    # Mengambil ID dari grup Regex (teks setelah garis bawah '_')
    gid = message.matches[0].group(1)
    
    if gid in ACTIVE_DOWNLOADS:
        filename = ACTIVE_DOWNLOADS[gid]
        success = await aria2_cancel(gid)
        
        if success:
            await message.reply(f"🛑 **Unduhan Dibatalkan:**\n`{filename}`")
        else:
            await message.reply("❌ **Gagal membatalkan unduhan. Sistem tidak merespons.**")
    else:
        await message.reply("❌ **Task ID tidak ditemukan, sudah selesai, atau sudah dibatalkan sebelumnya.**")
