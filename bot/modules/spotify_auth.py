from pyrogram import Client, filters
from bot import Config
from bot.helpers.spotify.manager import spotify_manager
from bot.helpers.database.mongo_async import database
import urllib.parse

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS: return

    # Scopes lengkap untuk akses Metadata, Playlist, dan Streaming
    scopes = [
        "user-read-private", "user-read-email", "user-library-read", 
        "user-library-modify", "streaming", "user-read-playback-state", 
        "user-modify-playback-state", "user-read-currently-playing", 
        "user-read-recently-played", "user-top-read", 
        "user-read-playback-position", "playlist-read-private", 
        "playlist-read-collaborative", "playlist-read", "playlist-modify"
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
        "🔐 **SPOTIFY LOGIN (ADVANCED)**\n\n"
        "Silakan login untuk mengaktifkan fitur download:\n\n"
        f"1. [KLIK DI SINI UNTUK LOGIN]({auth_url})\n"
        "2. Klik **'Agree'**.\n"
        "3. Salin URL dari browser (yang berawal `127.0.0.1`).\n"
        "4. Kirim ke bot: `/spotify_token [URL]`"
    )
    await message.reply(text, disable_web_page_preview=True)

@Client.on_message(filters.command("spotify_token") & filters.private)
async def spotify_token_handler(client, message):
    if message.from_user.id not in Config.ADMINS or len(message.command) < 2: return
    
    url = message.text.split(None, 1)[1].strip()
    msg = await message.reply("⏳ Memproses otentikasi...")
    
    if await spotify_manager.complete_login(url):
        await msg.edit("✅ **LOGIN BERHASIL!** Sesi telah disimpan.")
    else:
        await msg.edit("❌ **GAGAL!** Pastikan URL benar dan belum kadaluarsa.")

@Client.on_message(filters.command("set_sp_dc") & filters.private)
async def set_sp_dc_handler(client, message):
    if message.from_user.id not in Config.ADMINS or len(message.command) < 2: return

    sp_dc = message.text.split(None, 1)[1].strip()
    await database.set_bot_setting("spotify_sp_dc", sp_dc)
    await spotify_manager.initialize_clients()
    
    await message.reply("✅ **Cookie sp_dc berhasil disimpan!** Ini akan membantu menembus proteksi streaming.")

@Client.on_message(filters.command("reset_spotify") & filters.private)
async def reset_spotify_handler(client, message):
    if message.from_user.id not in Config.ADMINS: return
    
    await database.set_bot_setting("spotify_creds", None)
    await database.set_bot_setting("spotify_username", None)
    await database.set_bot_setting("spotify_sp_dc", None)
    
    await message.reply("🗑️ **Sesi Spotify telah dihapus.**")
