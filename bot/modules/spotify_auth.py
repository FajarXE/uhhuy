from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config
from bot import CMD
from bot.helpers.spotify.credentials_manager import HeadlessSpotifyAuth
from bot.helpers.spotify.manager import spotify_manager

# [PENTING] Import koneksi MongoDB dari spotify_api
from bot.helpers.spotify.spotify_api import mongo_collection

# Simpan sesi auth sementara di memori
auth_sessions = {}

@Client.on_message(filters.command("spotify_login") & filters.user(list(Config.ADMINS)))
async def spotify_login_cmd(client, message: Message):
    """
    Command untuk memulai proses login Spotify.
    """
    user_id = message.from_user.id
    auth_handler = HeadlessSpotifyAuth()
    auth_sessions[user_id] = auth_handler
    
    login_url = auth_handler.get_login_url()
    
    msg_text = (
        "<b>🟢 LOGIN SPOTIFY (TANPA PC)</b>\n\n"
        "1. Klik Link ini: <a href='{}'>KLIK DISINI UNTUK LOGIN</a>\n"
        "2. Login akun Spotify Anda dan klik 'Agree/Setuju'.\n"
        "3. Anda akan diarahkan ke halaman yang <b>ERROR</b>.\n"
        "4. Salin <b>SELURUH URL</b> dari address bar browser.\n"
        "5. Kirim ke sini dengan perintah:\n\n"
        "<code>/spotify_token [URL_YANG_DISALIN]</code>"
    ).format(login_url)
    
    await message.reply_text(msg_text, disable_web_page_preview=True)

@Client.on_message(filters.command("spotify_token") & filters.user(list(Config.ADMINS)))
async def spotify_token_cmd(client, message: Message):
    """
    Command untuk memproses URL callback dan menyimpannya permanen.
    """
    user_id = message.from_user.id
    
    if user_id not in auth_sessions:
        return await message.reply_text("⚠️ Jalankan /spotify_login terlebih dahulu.")
    
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Masukkan URL! Contoh:\n<code>/spotify_token http://...</code>")
    
    url = message.text.split(None, 1)[1].strip()
    auth_handler = auth_sessions[user_id]
    
    status_msg = await message.reply_text("⏳ Memproses dan mengamankan token...")
    
    success, result = auth_handler.process_callback_url(url)
    
    if success:
        json_creds = result
        import os
        import json
        
        # 1. Simpan ke file lokal sementara
        creds_path = spotify_manager.credentials_path
        os.makedirs(os.path.dirname(creds_path), exist_ok=True)
        with open(creds_path, "w") as f:
            f.write(json_creds)
            
        # 2. [ANTI-RESET RENDER] Simpan LANGSUNG ke MongoDB!
        if mongo_collection is not None:
            try:
                parsed_creds = json.loads(json_creds)
                mongo_collection.update_one(
                    {"type": "spotify_auth"}, 
                    {"$set": {"data": parsed_creds}}, 
                    upsert=True
                )
            except Exception as e:
                print(f"Gagal simpan ke DB: {e}")
                
        # Init ulang manager agar langsung bisa dipakai
        await spotify_manager.initialize_clients()
        
        final_msg = (
            "✅ <b>LOGIN BERHASIL DAN PERMANEN!</b>\n\n"
            "Bot sekarang bisa mendownload dari Spotify.\n"
            "Kredensial telah <b>disimpan dengan aman ke Database MongoDB</b>. Anda tidak perlu login ulang saat bot restart!"
        )
        await status_msg.edit_text(final_msg)
        auth_sessions.pop(user_id, None)
    else:
        await status_msg.edit_text(f"❌ <b>GAGAL:</b>\n{result}")
