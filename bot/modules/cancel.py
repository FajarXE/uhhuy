# [GANTI TOTAL ISI FILE: bot/modules/cancel.py]

import re
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatType
from bot.helpers.aria2_helper import aria2_cancel, ACTIVE_DOWNLOADS
from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT, GLOBAL_TASKS
from bot.settings import bot_set
from bot.helpers.database.mongo_async import database

@Client.on_message(filters.regex(r"^/cancel_([a-zA-Z0-9]+)"))
async def cancel_task_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if not bot_set.bot_public and user_id not in bot_set.auth_users and user_id not in bot_set.admins:
        return
    
    gid = message.matches[0].group(1)
    is_admin = user_id in bot_set.admins
    
    # --- [FIX] PENCARIAN TASK & VALIDASI KEPEMILIKAN YANG AMAN DI GRUP ---
    task_key = None
    if gid in GLOBAL_TASKS:
        task_key = gid
    else:
        for k, v in GLOBAL_TASKS.items():
            if k == gid or v.get('gid') == gid or v.get('cancel_id') == gid:
                task_key = k
                break

    if task_key and task_key in GLOBAL_TASKS:
        # Gunakan 'owner_id' (ID personal from_user.id) untuk validasi di grup
        task_owner = GLOBAL_TASKS[task_key].get('owner_id') or GLOBAL_TASKS[task_key].get('user_id')
        if not is_admin and task_owner and str(task_owner) != str(user_id):
            await message.reply("❌ **Akses Ditolak:** Anda hanya bisa membatalkan tugas Anda sendiri.")
            return
    # ------------------------------------------------------------------
    
    # Ambil GID Aria2 jika tugas tersebut merupakan unduhan Aria2
    aria2_gid = None
    if task_key and task_key in GLOBAL_TASKS:
        aria2_gid = GLOBAL_TASKS[task_key].get('gid')
    if not aria2_gid and gid in ACTIVE_DOWNLOADS:
        aria2_gid = gid

    if aria2_gid in ACTIVE_DOWNLOADS:
        filename = ACTIVE_DOWNLOADS[aria2_gid]
        success = await aria2_cancel(aria2_gid)
        if success:
            await message.reply(f"🛑 **Unduhan Dibatalkan:**\n`{filename}`")
        else:
            await message.reply("❌ **Gagal membatalkan unduhan Aria2.**")
            
    elif task_key or gid in GLOBAL_TASKS:
        target_id = task_key if task_key else gid
        GLOBAL_CANCEL_DICT.add(target_id)
        await database.add_cancel_task(target_id)
        await message.reply(f"🛑 **Sinyal Batal Dikirim!**\nProses akan segera dihentikan.")
        
    else:
        if message.from_user and message.chat.id == message.from_user.id:
            await message.reply("❌ **Task tidak ditemukan atau sudah selesai.**")

# --- TOMBOL PANIK / CLEAR BOARD (TANPA ANTREAN) ---
@Client.on_message(filters.command(["clear_queue", "force_unlock", "clear_board"]))
async def force_unlock_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in bot_set.admins:
        await message.reply("❌ **Akses Ditolak:** Hanya Admin yang bisa mereset sistem.")
        return
        
    import bot.helpers.ui_manager as ui_manager
    
    ui_manager.GLOBAL_TASKS.clear()
    ui_manager.GLOBAL_CANCEL_DICT.clear()
    await database.clear_all_cancels()
    
    from bot.helpers.aria2_helper import aria2_purge_all
    await aria2_purge_all()
    
    await message.reply("✅ **Sistem Papan Global Berhasil Direset!**\nSemua task hantu dan unduhan yang macet telah dibersihkan.")
