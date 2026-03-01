# [FILE BARU: bot/modules/cancel.py]

from pyrogram import Client, filters
from pyrogram.types import Message
from bot.helpers.aria2_helper import aria2_cancel, ACTIVE_DOWNLOADS
from bot.settings import bot_set

@Client.on_message(filters.command(["cancel", "cancel1"]))
async def cancel_task_handler(client: Client, message: Message):
    # Pastikan yang bisa cancel adalah admin/auth user
    user_id = message.from_user.id
    if not bot_set.bot_public and user_id not in bot_set.auth_users and user_id not in bot_set.admins:
        return

    # Cek apakah Task ID disertakan (contoh: /cancel1 a1b2c3d4e5f6)
    if len(message.command) < 2:
        await message.reply("❌ **Format salah!** Gunakan `/cancel1 <Task_ID>`")
        return
    
    gid = message.command[1]
    
    # Cek apakah GID tersebut ada di daftar antrean aktif Aria2
    if gid in ACTIVE_DOWNLOADS:
        filename = ACTIVE_DOWNLOADS[gid]
        
        # Kirim sinyal pembunuhan proses ke Aria2
        success = await aria2_cancel(gid)
        
        if success:
            await message.reply(f"🛑 **Unduhan Dibatalkan:**\n`{filename}`")
        else:
            await message.reply("❌ **Gagal membatalkan unduhan. Sistem tidak merespons.**")
    else:
        await message.reply("❌ **Task ID tidak ditemukan, sudah selesai, atau sudah dibatalkan sebelumnya.**")
