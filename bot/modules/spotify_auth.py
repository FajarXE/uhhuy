# [FILE: bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS: return
    
    # Link 1: Untuk Metadata (Aplikasi Anda)
    client_id = Config.SPOTIFY_CLIENT_ID
    url_meta = f"https://accounts.spotify.com/authorize?response_type=code&client_id={client_id}&redirect_uri=http://127.0.0.1:4381/login&scope=user-read-private%20user-read-email%20playlist-read-private"
    
    # Link 2: Untuk Streaming (Official Desktop)
    url_stream = spotify_manager.get_streaming_link()

    text = (
        "🔐 **SPOTIFY AUTHENTICATION CENTER**\n\n"
        "Anda harus melakukan login pada **KEDUA** link di bawah ini secara bergantian:\n\n"
        f"1️⃣ **[LOGIN METADATA]({url_meta})**\n"
        "   *(Agar bot bisa baca judul lagu)*\n\n"
        f"2️⃣ **[LOGIN STREAMING]({url_stream})**\n"
        "   *(Agar bot bisa download file musik)*\n\n"
        "**Cara:** Klik link -> Agree -> Salin URL error `127.0.0.1` -> Kirim ke bot dengan `/spotify_token [URL]`"
    )
    await message.reply(text, disable_web_page_preview=True)

@Client.on_message(filters.command("spotify_token") & filters.private)
async def token_handler(client, message):
    if message.from_user.id not in Config.ADMINS or len(message.command) < 2: return
    
    url = message.text.split(None, 1)[1].strip()
    msg = await message.reply("⏳ Memproses token...")
    
    res = await spotify_manager.complete_login(url)
    if res == "METADATA":
        await msg.edit("✅ **Sesi Metadata Berhasil!** Sekarang silakan klik link nomor 2 (Streaming).")
    elif res == "STREAMING":
        await msg.edit("✅ **Sesi Streaming Berhasil!** Bot sekarang sudah siap tempur di Render.")
    else:
        await msg.edit("❌ **Gagal!** Token tidak valid atau salah urutan. Pastikan klik link dari bot, bukan dari Log Render.")
