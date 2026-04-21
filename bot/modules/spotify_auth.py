# [FILE: bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager
from bot.logger import LOGGER
import urllib.parse

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS:
        return

    client_id = Config.SPOTIFY_CLIENT_ID
    if not client_id:
        return await message.reply("❌ `SPOTIFY_CLIENT_ID` belum diisi di .env!")

    # Alamat Redirect yang didaftarkan di Dashboard Spotify
    redirect_uri = "http://127.0.0.1:4381/login"
    
    # Daftar Scope yang diizinkan untuk User Premium
    scopes = [
        "user-read-private", 
        "user-read-email", 
        "playlist-read-private", 
        "playlist-read-collaborative", 
        "user-library-read", 
        "streaming", 
        "user-read-playback-state", 
        "user-modify-playback-state", 
        "user-read-currently-playing",
        "user-library-modify"
    ]
    
    # Membangun URL secara otomatis (Tanpa kesalahan ketik)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "show_dialog": "true" # Memaksa muncul pilihan akun
    }
    
    # URL resmi Spotify Authorization
    auth_url = f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(params)}"

    text = (
        "🔐 **LOGIN SPOTIFY PREMIUM**\n\n"
        "Klik link di bawah untuk menghubungkan bot ke akun Spotify Anda:\n\n"
        f"1️⃣ **[KLIK DI SINI UNTUK LOGIN]({auth_url})**\n\n"
        "2️⃣ Klik **'Agree'** atau **'Setuju'**.\n"
        "3️⃣ Browser akan error 'Site cannot be reached' (127.0.0.1) — **ABAIKAN SAJA**.\n"
        "4️⃣ **Salin SELURUH URL** yang ada di kolom alamat browser.\n"
        "5️⃣ Kirim ke sini dengan format:\n"
        "`/spotify_token [URL_YANG_DISALIN]`"
    )
    
    await message.reply(text, disable_web_page_preview=True)

@Client.on_message(filters.command("spotify_token") & filters.private)
async def spotify_token_handler(client, message):
    if message.from_user.id not in Config.ADMINS:
        return

    if len(message.command) < 2:
        return await message.reply("❌ Format: `/spotify_token [URL_DARI_BROWSER]`")

    url = message.text.split(None, 1)[1].strip()
    msg = await message.reply("⏳ **Menghubungkan ke Spotify...**")

    try:
        success = await spotify_manager.complete_login(url)
        if success:
            await msg.edit("✅ **LOGIN BERHASIL!**\nSesi Anda telah aman disimpan di Database MongoDB. Bot siap mengunduh lagu Spotify.")
        else:
            await msg.edit("❌ **TOKEN GAGAL!**\nURL tidak valid atau sudah kadaluarsa. Coba klik link login lagi.")
    except Exception as e:
        LOGGER.error(f"Spotify Auth Error: {e}")
        await msg.edit(f"❌ **Error:** `{str(e)}`")
