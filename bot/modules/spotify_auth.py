from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config
from bot import CMD
from bot.helpers.spotify.credentials_manager import HeadlessSpotifyAuth
from bot.helpers.spotify.manager import spotify_manager

# [PERBAIKAN] Menggunakan koneksi DB internal yang aman
from bot.helpers.spotify.spotify_api import mongo_collection

auth_sessions = {}

@Client.on_message(filters.command("spotify_login") & filters.user(list(Config.ADMINS)))
async def spotify_login_cmd(client, message: Message):
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
    user_id = message.from_user.id
    if user_id not in auth_sessions:
        return await message.reply_text("⚠️ Jalankan /spotify_login terlebih dahulu.")
    
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Masukkan URL! Contoh:\n<code>/spotify_token http://...</code>")
    
    url = message.text.split(None, 1)[1].strip()
    auth_handler = auth_sessions[user_id]
    
    status_msg = await message.reply_text("⏳ Memproses token...")
    
    success, result = auth_handler.process_callback_url(url)
    
    if success:
        json_creds = result
        
        # Simpan ke file fisik (untuk backup lokal)
        import os
        creds_path = spotify_manager.credentials_path
        os.makedirs(os.path.dirname(creds_path), exist_ok=True)
        with open(creds_path, "w") as f:
            f.write(json_creds)
            
        # Catatan: Kita tidak perlu lagi menulis JSON ke DB di sini secara manual,
        # karena file spotify_api.py akan otomatis membacanya dan menyimpannya 
        # ke Database internalnya saat proses initialize di bawah ini!
        
        await spotify_manager.initialize_clients()
        
        final_msg = (
            "✅ <b>LOGIN BERHASIL!</b>\n\n"
            "Bot sekarang bisa mendownload dari Spotify.\n"
            "Kredensial telah disimpan secara permanen ke Database Internal."
        )
        await status_msg.edit_text(final_msg)
        auth_sessions.pop(user_id, None)
    else:
        await status_msg.edit_text(f"❌ <b>Login Gagal:</b>\n{result}")

@Client.on_message(filters.command("set_spotify_dc") & filters.user(list(Config.ADMINS)))
async def set_spotify_dc_cmd(client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ **Format Salah!**\n"
            "Gunakan: <code>/set_spotify_dc [cookie_sp_dc_anda]</code>"
        )
    
    cookie = message.text.split(None, 1)[1].strip()
    status_msg = await message.reply_text("⏳ Menyimpan Cookie sp_dc ke Database Internal...")
    
    try:
        # Simpan menggunakan koneksi PyMongo internal yang aman dari crash
        if mongo_collection is not None:
            mongo_collection.update_one(
                {"type": "spotify_sp_dc"}, 
                {"$set": {"data": cookie}}, 
                upsert=True
            )
            
        Config.SPOTIFY_SP_DC = cookie
        await spotify_manager.initialize_clients()
        
        await status_msg.edit_text(
            "✅ **Cookie sp_dc berhasil disimpan!**\n"
            "Bot sekarang bisa mengunduh kualitas FLAC (Lossless) menggunakan PlayPlay."
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ **Gagal menyimpan cookie:** {e}")
