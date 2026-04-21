# [FILE: bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager
import json

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS: return

    client_id = Config.SPOTIFY_CLIENT_ID
    redirect_uri = "http://127.0.0.1:4381/login"
    scopes = "user-read-private%20user-read-email%20playlist-read-private%20streaming%20user-library-read"
    
    auth_url = f"https://accounts.spotify.com/authorize?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}&scope={scopes}"

    text = (
        "🔐 **LOGIN SPOTIFY (WEB API)**\n\n"
        f"1. [KLIK DI SINI UNTUK LOGIN]({auth_url})\n"
        "2. Salin URL error (127.0.0.1) setelah 'Agree'.\n"
        "3. Kirim ke bot: `/spotify_token [URL]`"
    )
    await message.reply(text, disable_web_page_preview=True)

@Client.on_message(filters.command("spotify_token") & filters.private)
async def spotify_token_handler(client, message):
    if message.from_user.id not in Config.ADMINS: return
    if len(message.command) < 2: return

    url = message.text.split(None, 1)[1].strip()
    msg = await message.reply("⏳ **Sedang memproses...**")

    # Manager pintar akan otomatis tahu ini token Metadata atau Streaming
    result = await spotify_manager.complete_login(url)
    
    if result == "METADATA":
        await msg.edit("✅ **Login Metadata Berhasil!**\nSekarang coba download lagu, jika bot 'stuck', lihat link di Log Render.")
    elif result == "STREAMING":
        await msg.edit("✅ **Login Streaming (Librespot) Berhasil!**\nSekarang bot sudah bisa download lagu di Render.")
    else:
        await msg.edit("❌ **Gagal!** URL salah atau sudah kadaluarsa.")

# Perintah Cadangan (Jika cara otomatis gagal)
@Client.on_message(filters.command("set_librespot") & filters.private)
async def set_librespot_handler(client, message):
    if message.from_user.id not in Config.ADMINS: return
    if len(message.command) < 2: return
    try:
        json_str = message.text.split(None, 1)[1]
        await database.set_bot_setting("spotify_librespot", json_str)
        await spotify_manager.initialize_clients()
        await message.reply("✅ Sesi Librespot berhasil disuntikkan secara manual.")
    except:
        await message.reply("❌ Gagal menyuntikkan JSON.")
