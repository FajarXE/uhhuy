# [GANTI TOTAL ISI FILE: bot/modules/cancel.py]

import re
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ChatType
from bot.helpers.aria2_helper import aria2_cancel, ACTIVE_DOWNLOADS
from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT, GLOBAL_TASKS
from bot.settings import bot_set
from bot.helpers.database.mongo_async import database

# Handler untuk Teks Perintah (Jika user masih mengetik manual /cancel_...)
@Client.on_message(filters.regex(r"^/cancel_([a-zA-Z0-9]+)"))
async def cancel_task_handler(client: Client, message: Message):
    gid = message.text.split('_')[1]
    await process_cancel(client, message, gid, message.from_user.id)

# Handler untuk Tombol Merah Kurigram (InlineKeyboardButton)
@Client.on_callback_query(filters.regex(r"^cancel_([a-zA-Z0-9]+)"))
async def cancel_task_callback(client: Client, query: CallbackQuery):
    # Ekstrak task_id dari tombol yang diklik
    gid = query.data.split('_')[1]
    await process_cancel(client, query.message, gid, query.from_user.id, is_callback=True, query_obj=query)

async def process_cancel(client, message, gid, user_id, is_callback=False, query_obj=None):
    if not bot_set.bot_public and user_id not in bot_set.auth_users and user_id not in bot_set.admins:
        if is_callback:
            await query_obj.answer("❌ Akses Ditolak.", show_alert=True)
        return
    
    is_admin = user_id in bot_set.admins
    
    # --- PENGECEKAN KEPEMILIKAN TASK ---
    if gid in GLOBAL_TASKS:
        task_owner = GLOBAL_TASKS[gid].get('user_id')
        if not is_admin and task_owner and str(task_owner) != str(user_id):
            if is_callback:
                await query_obj.answer("❌ Akses Ditolak: Anda hanya bisa membatalkan tugas Anda sendiri.", show_alert=True)
            else:
                await message.reply("❌ **Akses Ditolak:** Anda hanya bisa membatalkan tugas Anda sendiri.")
            return
            
    cancel_success_msg = ""
    
    if gid in ACTIVE_DOWNLOADS:
        filename = ACTIVE_DOWNLOADS[gid]
        success = await aria2_cancel(gid)
        if success:
            cancel_success_msg = f"🛑 Unduhan Dibatalkan:\n{filename}"
        else:
            cancel_success_msg = "❌ Gagal membatalkan unduhan Aria2."
            
    elif gid in GLOBAL_TASKS:
        GLOBAL_CANCEL_DICT.add(gid)
        await database.add_cancel_task(gid)
        cancel_success_msg = "🛑 Sinyal Batal Dikirim!\nProses akan segera dihentikan."
        
    else:
        cancel_success_msg = "❌ Task tidak ditemukan atau sudah selesai."
        
    # Kirim pop-up Toast Notification jika klik dari tombol, kirim pesan text jika manual
    if is_callback:
        await query_obj.answer(cancel_success_msg, show_alert=True)
    else:
        if message.from_user and message.chat.id == message.from_user.id:
            await message.reply(cancel_success_msg)

# --- TOMBOL PANIK / CLEAR BOARD ---
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
