# [GANTI TOTAL ISI FILE: bot/modules/cancel.py]

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from bot.helpers.aria2_helper import aria2_cancel, ACTIVE_DOWNLOADS
from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT, GLOBAL_TASKS, GLOBAL_STATE_LOCK
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
    gid = query.data.split('_')[1]
    await process_cancel(client, query.message, gid, query.from_user.id, is_callback=True, query_obj=query)

async def process_cancel(client, message, gid, user_id, is_callback=False, query_obj=None):
    if not bot_set.bot_public and user_id not in bot_set.auth_users and user_id not in bot_set.admins:
        if is_callback:
            await query_obj.answer("❌ Access Denied.", show_alert=True)
        return
    
    is_admin = user_id in bot_set.admins
    
    # --- PENGECEKAN KEPEMILIKAN TASK ---
    if gid in GLOBAL_TASKS:
        task_owner = GLOBAL_TASKS[gid].get('user_id')
        if not is_admin and task_owner and str(task_owner) != str(user_id):
            if is_callback:
                await query_obj.answer("❌ Access Denied: You can only cancel your own tasks.", show_alert=True)
            else:
                await message.reply("❌ **Access Denied:** You can only cancel your own tasks.")
            return
            
    cancel_success_msg = ""
    found_task = False

    if gid in GLOBAL_TASKS:
        found_task = True
        GLOBAL_CANCEL_DICT.add(gid)
        await database.add_cancel_task(gid)
        cancel_success_msg = "🛑 Cancel Signal Sent!\nThe process will be stopped shortly."

    if gid in ACTIVE_DOWNLOADS:
        found_task = True
        filename = ACTIVE_DOWNLOADS.get(gid, "Unknown")
        GLOBAL_CANCEL_DICT.add(gid)
        success = await aria2_cancel(gid)
        if success and not cancel_success_msg:
            cancel_success_msg = f"🛑 Download Canceled:\n{filename}"
        elif not cancel_success_msg:
            cancel_success_msg = "🛑 Cancel Signal Sent to Aria2!"

    if not found_task:
        cancel_success_msg = "❌ Task not found or already completed."
        
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
        await message.reply("❌ **Access Denied:** Only Admin can reset the system.")
        return
        
    import bot.helpers.ui_manager as ui_manager
    async with GLOBAL_STATE_LOCK:
        ui_manager.GLOBAL_TASKS.clear()
        ui_manager.GLOBAL_CANCEL_DICT.clear()
        ui_manager.GLOBAL_UI_LAST_TEXT.clear()
        
    await database.clear_all_cancels()
    
    try:
        from bot.modules.download import USER_SEMAPHORES
        USER_SEMAPHORES.clear()
    except Exception:
        pass
    
    from bot.helpers.aria2_helper import aria2_purge_all
    await aria2_purge_all()
    
    await message.reply("✅ **Global Board System has been successfully reset!**\nAll ghost tasks, personal queues, and stalled downloads have been cleared.")
