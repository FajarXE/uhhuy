# [TAMBAHKAN KE bot/modules/spotify_auth.py]

from pyrogram import Client, filters
from bot import Config
from bot.helpers.message import send_message

@Client.on_message(filters.command("login_spotify") & filters.private)
async def login_spotify_handler(client, message):
    # Proteksi: Hanya Admin yang bisa melihat instruksi login sensitif ini
    if message.from_user.id not in Config.ADMINS:
        return

    # Merakit URL Login Spotify
    # Redirect URI wajib: http://127.0.0.1:4381/login (sesuai standar OrpheusDL)
    client_id = Config.SPOTIFY_CLIENT_ID
    redirect_uri = "http://127.0.0.1:4381/login"
    scope = "app-remote-control,playlist-modify,playlist-modify-private,playlist-modify-public,playlist-read,playlist-read-collaborative,playlist-read-private,streaming,transfer-auth-session,ugc-image-upload,user-follow-modify,user-follow-read,user-library-modify,user-library-read,user-modify-playback-state,user-read-currently-playing,user-read-email,user-read-playback-position,user-read-playback-state,user-read-private,user-read-recently-played,user-top-read"
    
    auth_url = (
        f"https://accounts.spotify.com/authorize?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={redirect_uri}&"
        f"scope={scope}"
    )

    instruction_text = (
        "🔐 **PROSEDUR LOGIN SPOTIFY PREMIUM**\n\n"
        "Ikuti langkah-langkah berikut untuk mengaktifkan fitur Spotify di bot Anda:\n\n"
        f"1️⃣ **Buka Link Autentikasi:**\n[KLIK DI SINI UNTUK LOGIN]({auth_url})\n\n"
        "2️⃣ **Setujui Akses:**\nLogin ke akun Spotify Premium Anda dan klik **'Agree'** atau **'Setuju'**.\n\n"
        "3️⃣ **Salin URL Redirect:**\nBrowser akan mengarah ke halaman error (127.0.0.1). **Salin SELURUH URL** yang ada di address bar browser Anda.\n\n"
        "4️⃣ **Kirim ke Bot:**\nTempel URL tersebut dengan format perintah berikut:\n"
        "`/spotify_token [URL_YANG_DISALIN]`\n\n"
        "⚠️ *Pastikan Anda sudah menambahkan `http://127.0.0.1:4381/login` ke dalam 'Redirect URIs' di Spotify Developer Dashboard.*"
    )

    await message.reply(instruction_text, disable_web_page_preview=True)
