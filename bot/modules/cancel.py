# [GANTI TOTAL ISI FILE: bot/modules/cancel.py]

import re
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.helpers.aria2_helper import aria2_cancel, ACTIVE_DOWNLOADS
from bot.helpers.utils import GLOBAL_CANCEL_DICT, GLOBAL_TASKS
from bot.settings import bot_set

@Client.on_message(filters.regex(r"^/cancel_([a-zA-Z0-9]+)"))
async def cancel_task_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if not bot_set.bot_public and user_id not in bot_set.auth_users and user_id not in bot_set.admins:
        return
    
    gid = message.matches[0].group(1)
    is_admin = user_id in bot_set.admins
    
    # --- PENGECEKAN KEPEMILIKAN TASK (SECURITY FIX) ---
    if gid in GLOBAL_TASKS:
        task_owner = GLOBAL_TASKS[gid].get('user_id')
        if not is_admin and task_owner and str(task_owner) != str(user_id):
            await message.reply("❌ **Akses Ditolak:** Anda hanya bisa membatalkan tugas Anda sendiri.")
            return
    # --------------------------------------------------
    
    if gid in ACTIVE_DOWNLOADS:
        filename = ACTIVE_DOWNLOADS[gid]
        success = await aria2_cancel(gid)
        if success:
            await message.reply(f"🛑 **Unduhan Dibatalkan:**\n`{filename}`")
        else:
            await message.reply("❌ **Gagal membatalkan unduhan Aria2.**")
            
    else:
        GLOBAL_CANCEL_DICT.add(gid)
        await message.reply(f"🛑 **Sinyal Batal Dikirim!**\nProses akan segera dihentikan.")

# --- TOMBOL PANIK / CLEAR BOARD (TANPA ANTREAN) ---
@Client.on_message(filters.command(["clear_queue", "force_unlock", "clear_board"]))
async def force_unlock_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in bot_set.admins:
        await message.reply("❌ **Akses Ditolak:** Hanya Admin yang bisa mereset sistem.")
        return
        
    import bot.helpers.utils as utils
    
    # 1. Bersihkan sisa task hantu di Papan Global
    utils.GLOBAL_TASKS.clear()
    
    # 2. Bersihkan sinyal batal yang nyangkut
    utils.GLOBAL_CANCEL_DICT.clear()
    
    # 3. Bunuh paksa semua unduhan Aria2 yang nyangkut di latar belakang
    from bot.helpers.aria2_helper import aria2_purge_all
    await aria2_purge_all()
    
    await message.reply("✅ **Sistem Papan Global Berhasil Direset!**\nSemua task hantu dan unduhan yang macet telah dibersihkan.")
# ------------------------------------------------
