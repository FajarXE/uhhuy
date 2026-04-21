# [FILE: bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager
from bot.helpers.database.mongo_async import database
import urllib.parse
import json

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS:
        return

    # Daftar Scope Lengkap untuk mendukung Metadata dan Streaming (Librespot)
    scopes = [
        "user-read-private", 
        "user-read-email", 
        "user-library-read", 
        "user-library-modify", 
        "streaming", 
        "user-read-playback-state", 
        "user-modify-playback-state", 
        "user-read-currently-playing", 
        "user-read-recently-played", 
        "user-top-read", 
        "user-read-playback-position", 
        "playlist-read-private", 
        "playlist-read-collaborative",
        "playlist-read",
        "playlist-modify"
    ]
    
    params = {
        "client_id": Config.SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": "http://127.0.0.1:4381/login",
        "scope": " ".join(scopes),
        "show_dialog": "true"
    }
    
    auth_url = f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(params)}"

    text = (
        "🔐 **SPOTIFY LOGIN (FINAL SCOPES)**\n\n"
        "Gunakan link di bawah untuk memberikan izin akses penuh ke bot:\n\n"
        f"1️⃣ **[KLIK DI SINI UNTUK LOGIN]({auth_url})**\n\n"
        "2️⃣ Klik **'Agree'** atau **'Setuju'**.\n"
        "3️⃣ Anda akan melihat halaman error (127.0.0.1) — **INI NORMAL**.\n"
        "4️⃣ **Salin SELURUH URL** dari address bar browser Anda.\n"
        "5️⃣ Kirim ke bot dengan perintah:\n"
        "`/spotify_token [URL_YANG_DISALIN]`"
    )
    
    await message.reply(text, disable_web_page_preview=True)

@Client.on_message(filters.command("spotify_token") & filters.private)
async def spotify_token_handler(client, message):
    if message.from_user.id not in Config.ADMINS:
        return

    if len(message.command) < 2:
        return await message.reply("❌ Format salah! Gunakan: `/spotify_token [URL]`")

    url = message.text.split(None, 1)[1].strip()
    msg = await message.reply("⏳ **Sedang memvalidasi sesi...**")

    # Memproses login melalui manager
    if await spotify_manager.complete_login(url):
        await msg.edit(
            "✅ **LOGIN BERHASIL!**\n\n"
            "Semua perizinan (scopes) telah diperbarui. Sesi Metadata dan Streaming telah disimpan ke MongoDB."
        )
    else:
        await msg.edit(
            "❌ **GAGAL!**\n\n"
            "URL tidak valid atau sudah kadaluarsa. Pastikan Anda menyalin URL dari address bar segera setelah klik 'Agree'."
        )

@Client.on_message(filters.command("reset_spotify") & filters.private)
async def reset_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS:
        return
    
    # Menghapus sesi lama dari database untuk memicu login bersih
    await database.set_bot_setting("spotify_creds", None)
    await database.set_bot_setting("spotify_username", None)
    await database.set_bot_setting("spotify_librespot", None)
    
    await message.reply(
        "🗑️ **Sesi Spotify Berhasil Direset.**\n\n"
        "Silakan jalankan perintah `/login_spotify` untuk membuat sesi baru dengan izin yang benar."
    )

@Client.on_message(filters.command("set_librespot") & filters.private)
async def set_librespot_handler(client, message):
    if message.from_user.id not in Config.ADMINS:
        return
    
    if len(message.command) < 2:
        return await message.reply("Format: `/set_librespot [JSON_DATA]`")

    json_str = message.text.split(None, 1)[1].strip()
    
    try:
        # Validasi format JSON sebelum disimpan
        json.loads(json_str)
        await database.set_bot_setting("spotify_librespot", json_str)
        await spotify_manager.initialize_clients()
        await message.reply("✅ **Sesi Streaming (Librespot) berhasil disuntikkan secara manual!**")
    except Exception as e:
        await message.reply(f"❌ **JSON Tidak Valid:** `{str(e)}`")
