# [FILE: bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager
from bot.logger import LOGGER
import urllib.parse

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    # 1. Cek Admin
    if message.from_user.id not in Config.ADMINS:
        return

    # 2. Cek Client ID
    client_id = Config.SPOTIFY_CLIENT_ID
    if not client_id:
        return await message.reply("❌ `SPOTIFY_CLIENT_ID` kosong! Isi dulu di .env atau Config.")

    # 3. Setup Parameter OAuth
    redirect_uri = "http://127.0.0.1:4381/login"
    scopes = [
        "user-read-private", "user-read-email", "playlist-read-private", 
        "playlist-read-collaborative", "user-library-read", "user-top-read", 
        "user-read-playback-state", "user-modify-playback-state", 
        "user-read-currently-playing", "streaming", "app-remote-control",
        "user-follow-read", "user-library-modify", "user-read-recently-played"
    ]
    
    # Menggunakan urlencode agar formatnya dijamin standar dan tidak error
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes)
    }
    
    auth_url = f"https://open.spotify.com9?{urllib.parse.urlencode(params)}"

    text = (
        "🔐 **LOGIN SPOTIFY PREMIUM**\n\n"
        "Silakan klik link di bawah untuk memberikan izin akses ke bot:\n\n"
        f"1️⃣ **[KLIK DI SINI UNTUK LOGIN]({auth_url})**\n\n"
        "2️⃣ Klik **'Agree'** atau **'Setuju'**.\n"
        "3️⃣ Browser akan error (127.0.0.1) — **ITU NORMAL**.\n"
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
        return await message.reply("❌ Format: `/spotify_token [URL]`")

    url = message.text.split(None, 1)[1].strip()
    msg = await message.reply("⏳ **Sedang menukar token...**")

    try:
        success = await spotify_manager.complete_login(url)
        if success:
            await msg.edit("✅ **Login Berhasil!** Sesi telah aman tersimpan di Database MongoDB.")
        else:
            await msg.edit("❌ **Gagal!** URL tidak valid atau sudah kadaluarsa.")
    except Exception as e:
        LOGGER.error(f"Auth Error: {e}")
        await msg.edit(f"❌ **Error:** `{str(e)}`")
