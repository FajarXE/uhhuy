import logging
from pyrogram import Client, filters
from config import Config

# --- [DEBUG 1] Cek apakah file ini dibaca oleh Python ---
print("!!! DEBUG: MODUL RENDER SEDANG DIMUAT !!!")
logging.info("!!! DEBUG: MODUL RENDER SEDANG DIMUAT !!!")

# Kita matikan dulu filter admin dan fungsi API yang rumit
# Kita pakai handler paling sederhana

@Client.on_message(filters.command("render"))
async def debug_render_handler(client, message):
    # --- [DEBUG 2] Cek apakah pesan masuk ke handler ---
    user_id = message.from_user.id
    print(f"!!! DEBUG: Command /render diterima dari User ID: {user_id} !!!")
    logging.info(f"!!! DEBUG: Command /render diterima dari User ID: {user_id} !!!")

    # Cek apakah User ID ada di daftar Admin
    is_admin = user_id in Config.ADMINS
    admin_list = Config.ADMINS

    debug_text = (
        f"🤖 **DEBUG MODE** 🤖\n\n"
        f"✅ **Pesan Diterima!**\n"
        f"👤 **User ID Anda:** `{user_id}`\n"
        f"👑 **Status Admin:** `{is_admin}`\n"
        f"📋 **Daftar Admin di Config:** `{admin_list}`\n\n"
        f"Jika pesan ini muncul, berarti bot berjalan lancar. Masalah sebelumnya kemungkinan ada di `render_api.py` atau Logic Filter."
    )
    
    try:
        await message.reply(debug_text)
        print("!!! DEBUG: Balasan terkirim ke Telegram !!!")
    except Exception as e:
        print(f"!!! DEBUG: Gagal mengirim balasan: {e} !!!")
        logging.error(f"!!! DEBUG: Gagal mengirim balasan: {e} !!!")

