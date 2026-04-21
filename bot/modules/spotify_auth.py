# [FILE: bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager
from bot.helpers.message import send_message
from bot.logger import LOGGER

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    # PENTING: Cek apakah User ID Anda sudah ada di Config.ADMINS
    if message.from_user.id not in Config.ADMINS:
        LOGGER.warning(f"User {message.from_user.id} mencoba akses login_spotify tapi bukan Admin.")
        return

    client_id = Config.SPOTIFY_CLIENT_ID
    if not client_id:
        return await message.reply("❌ `SPOTIFY_CLIENT_ID` belum diatur di .env atau Config!")

    redirect_uri = "http://127.0.0.1:4381/login"
    
    # Daftar Scope yang sudah diperbaiki (Dihapus: transfer-auth-session, playlist-modify, playlist-read)
    scopes = [
        "user-read-private", "user-read-email", "playlist-read-private", 
        "playlist-read-collaborative", "user-library-read", "user-top-read", 
        "user-read-playback-state", "user-modify-playback-state", 
        "user-read-currently-playing", "streaming", "app-remote-control",
        "user-follow-read", "user-library-modify", "user-read-recently-played"
    ]
    
    scope_string = "%20".join(scopes)
    
    auth_url = (
        f"https://googleusercontent.com/spotify.com/8"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={redirect_uri}&"
        f"scope={scope_string}"
    )

    text = (
        "🔐 **LOGIN SPOTIFY PREMIUM**\n\n"
        f"1. [KLIK DI SINI UNTUK LOGIN]({auth_url})\n"
        "2. Klik **'Agree/Setuju'**.\n"
        "3. Anda akan diarahkan ke halaman error (127.0.0.1).\n"
        "4. **Salin SELURUH URL** dari address bar browser.\n"
        "5. Kirim ke bot dengan perintah:\n"
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
            await msg.edit("✅ **Login Berhasil!** Sesi telah disimpan di Database MongoDB.")
        else:
            await msg.edit("❌ **Gagal!** URL tidak valid atau sudah kadaluarsa.")
    except Exception as e:
        await msg.edit(f"❌ **Error:** `{str(e)}`")
