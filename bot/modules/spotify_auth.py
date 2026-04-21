# [FILE: bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager
from bot.helpers.message import send_message

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS:
        return

    client_id = Config.SPOTIFY_CLIENT_ID
    redirect_uri = "http://127.0.0.1:4381/login"
    scope = "app-remote-control,playlist-modify,playlist-modify-private,playlist-modify-public,playlist-read,playlist-read-collaborative,playlist-read-private,streaming,transfer-auth-session,ugc-image-upload,user-follow-modify,user-follow-read,user-library-modify,user-library-read,user-modify-playback-state,user-read-currently-playing,user-read-email,user-read-playback-position,user-read-playback-state,user-read-private,user-read-recently-played,user-top-read"
    
    auth_url = f"https://accounts.spotify.com/authorize?client_id={client_id}&response_type=code&redirect_uri={redirect_uri}&scope={scope}"

    text = (
        "🔐 **LOGIN SPOTIFY PREMIUM**\n\n"
        f"1. [KLIK DI SINI UNTUK LOGIN]({auth_url})\n"
        "2. Klik 'Agree/Setuju'.\n"
        "3. Salin URL dari halaman error (127.0.0.1).\n"
        "4. Kirim ke bot: `/spotify_token [URL]`"
    )
    await message.reply(text, disable_web_page_preview=True)

@Client.on_message(filters.command("spotify_token") & filters.private)
async def spotify_token_handler(client, message):
    if message.from_user.id not in Config.ADMINS: return
    if len(message.command) < 2: return

    url = message.text.split(None, 1)[1]
    msg = await message.reply("⏳ Memvalidasi...")

    if await spotify_manager.complete_login(url):
        await msg.edit("✅ Login Berhasil & Tersimpan di Database!")
    else:
        await msg.edit("❌ Gagal menukar token.")
