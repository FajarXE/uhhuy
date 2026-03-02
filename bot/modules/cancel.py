# [GANTI TOTAL ISI FILE: bot/modules/cancel.py]

import re
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.helpers.aria2_helper import aria2_cancel, ACTIVE_DOWNLOADS
from bot.helpers.utils import GLOBAL_CANCEL_DICT
from bot.settings import bot_set

@Client.on_message(filters.regex(r"^/cancel_([a-zA-Z0-9]+)"))
async def cancel_task_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if not bot_set.bot_public and user_id not in bot_set.auth_users and user_id not in bot_set.admins:
        return
    
    gid = message.matches[0].group(1)
    
    # 1. Cek apakah ini ID dari Aria2 (Sedang proses Download)
    if gid in ACTIVE_DOWNLOADS:
        filename = ACTIVE_DOWNLOADS[gid]
        success = await aria2_cancel(gid)
        if success:
            await message.reply(f"🛑 **Unduhan Dibatalkan:**\n`{filename}`")
        else:
            await message.reply("❌ **Gagal membatalkan unduhan Aria2.**")
            
    # 2. Jika bukan Aria2, berarti itu ID dari Upload/Zipping!
    else:
        GLOBAL_CANCEL_DICT.add(gid)
        await message.reply(f"🛑 **Sinyal Batal Dikirim!**\nProses Upload/Zipping akan segera dihentikan.")
