# [FILE: bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager
import urllib.parse

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS: return

    # DAFTAR SCOPE LENGKAP (Sesuai permintaan log error)
    scopes = [
        "user-read-private", "user-read-email", "user-library-read", 
        "user-library-modify", "streaming", "user-read-playback-state", 
        "user-modify-playback-state", "user-read-currently-playing", 
        "user-read-recently-played", "user-top-read", 
        "user-read-playback-position", "playlist-read-private", 
        "playlist-read-collaborative"
    ]
    
    params = {
        "client_id": Config.SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": "http://127.0.0.1:4381/login",
        "scope": " ".join(scopes), # Otomatis jadi spasi antar scope
        "show_dialog": "true"
    }
    
    auth_url = f"https://accounts.spotify.com/authorize?{urllib.parse.urlencode(params)}"

    text = (
        "🔐 **SPOTIFY LOGIN (FULL SCOPES)**\n\n"
        "Mesin download meminta izin tambahan. Silakan login ulang melalui link di bawah:\n\n"
        f"1. [KLIK DI SINI UNTUK LOGIN]({auth_url})\n"
        "2. Klik **'Agree'**.\n"
        "3. Salin URL error `127.0.0.1` dari browser.\n"
        "4. Kirim ke bot: `/spotify_token [URL]`"
    )
    await message.reply(text, disable_web_page_preview=True)

@Client.on_message(filters.command("spotify_token") & filters.private)
async def token_handler(client, message):
    if message.from_user.id not in Config.ADMINS or len(message.command) < 2: return
    
    url = message.text.split(None, 1)[1].strip()
    msg = await message.reply("⏳ Memperbarui sesi dengan izin lengkap...")
    
    if await spotify_manager.complete_login(url):
        await msg.edit("✅ **LOGIN BERHASIL!**\nSekarang izin sudah lengkap. Silakan coba kirim link lagu lagi.")
    else:
        await msg.edit("❌ **GAGAL!** Pastikan Anda menyalin URL dengan benar.")
