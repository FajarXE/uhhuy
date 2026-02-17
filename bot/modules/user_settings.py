# [FILE: bot/modules/user_settings.py]

import bot.helpers.translations as lang
import logging, asyncio
from traceback import format_exc

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from config import Config
from bot import cmd
from bot import BOT_QOBUZ_CLIENTS 

# --- IMPORT MANAGERS (DENGAN ERROR HANDLING) ---
try:
    from ..helpers.beatport.manager import beatport_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor beatport_manager.")
    beatport_manager = None
try:
    from ..helpers.deezer.manager import deezer_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor deezer_manager.")
    deezer_manager = None
try:
    from ..helpers.tidal.manager import tidal_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor tidal_manager.")
    tidal_manager = None
try:
    from ..helpers.kkbox.manager import kkbox_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor kkbox_manager.")
    kkbox_manager = None
try:
    from ..helpers.beatsource.manager import beatsource_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor beatsource_manager.")
    beatsource_manager = None
try:
    from ..helpers.soundcloud.manager import soundcloud_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor soundcloud_manager.")
    soundcloud_manager = None
try:
    from ..helpers.napster.manager import napster_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor napster_manager.")
    napster_manager = None
try:
    from ..helpers.idagio.manager import idagio_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor idagio_manager.")
    idagio_manager = None
try:
    from ..helpers.bugs.manager import bugs_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor bugs_manager.")
    bugs_manager = None
try:
    from ..helpers.moov.manager import moov_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor moov_manager.")
    moov_manager = None
try:
    from ..helpers.livephish.manager import livephish_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor livephish_manager.")
    livephish_manager = None
try:
    from ..helpers.highresaudio.manager import highresaudio_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor highresaudio_manager.")
    highresaudio_manager = None
try:
    from ..helpers.khinsider.manager import khinsider_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor khinsider_manager.")
    khinsider_manager = None
try:
    from ..helpers.qobuz.qopy import qobuz_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor qobuz_manager.")
    qobuz_manager = None

# --- IMPORT BUTTONS ---
# Pastikan Anda sudah menambahkan 'beatport_user_auth_buttons' di bot/helpers/buttons/settings.py
from ..helpers.buttons.settings import (
    usetting_button, tidal_quality_button, 
    qb_button, bp_button, dz_button, kk_button,
    bs_button, sc_button, np_button, id_button,
    bugs_button, lyrics_button, mv_button,
    lp_button, khi_button, beatport_user_auth_buttons, beatsource_user_auth_buttons, highresaudio_user_auth_buttons, hra_button, qb_user_auth_buttons, deezer_user_auth_buttons
)
from ..helpers.database.mongo_async import database
from ..helpers.utils import fetch_zip_settings
from ..settings import bot_set
from ..helpers.message import send_message, edit_message, check_user, fetch_user_details
from ..helpers.tidal.tidal_api import TidalApi


# ==================================
# COMMANDS SET/DEL TOKEN
# ==================================

# --- HELPER FUNCTION ---
async def _save_token(message, key, name):
    user_id = message.from_user.id
    try:
        if len(message.command) < 2:
            raise IndexError
        token = message.text.split(maxsplit=1)[1].strip()
        
        # Simpan ke Memory & DB
        bot_set.user_data.setdefault(user_id, {})[key] = token
        await database.save_user_settings(user_id, {key: token})
        
        await message.reply_text(f"✅ <b>{name} Token Saved!</b>\nToken: <code>{token}</code>")
    except IndexError:
        await message.reply_text(f"❌ <b>Format Salah.</b>\nContoh: <code>/set_{name.lower()} your_token_here</code>")

async def _del_token(message, key, name):
    user_id = message.from_user.id
    # Hapus dari Memory
    if user_id in bot_set.user_data:
        bot_set.user_data[user_id].pop(key, None)
    
    # Hapus dari DB
    await database.save_user_settings(user_id, {key: None})
    await message.reply_text(f"🗑️ <b>{name} Token Deleted!</b>")


# --- 1. GOFILE ---
@Client.on_message(filters.command("set_gofile"))
async def set_gofile_cmd(client, message):
    if await check_user(msg=message):
        await _save_token(message, 'gofile_token', 'Gofile')

@Client.on_message(filters.command(["del_gofile", "delete_gofile"]))
async def del_gofile_cmd(client, message):
    if await check_user(msg=message):
        await _del_token(message, 'gofile_token', 'Gofile')

# --- 2. BUZZHEAVIER ---
@Client.on_message(filters.command("set_buzzheavier"))
async def set_bh_cmd(client, message):
    if await check_user(msg=message):
        await _save_token(message, 'buzzheavier_token', 'Buzzheavier')

@Client.on_message(filters.command(["del_buzzheavier", "delete_buzzheavier"]))
async def del_bh_cmd(client, message):
    if await check_user(msg=message):
        await _del_token(message, 'buzzheavier_token', 'Buzzheavier')

# --- 3. VIKINGFILES ---
@Client.on_message(filters.command("set_viking"))
async def set_vk_cmd(client, message):
    if await check_user(msg=message):
        await _save_token(message, 'viking_token', 'Vikingfiles')

@Client.on_message(filters.command(["del_viking", "delete_viking"]))
async def del_vk_cmd(client, message):
    if await check_user(msg=message):
        await _del_token(message, 'viking_token', 'Vikingfiles')


# ==================================
# BEATPORT PRIVATE AUTH (USER SETTINGS)
# ==================================

# 1. COMMAND LOGIN
@Client.on_message(filters.command("beatport_login"))
async def uset_bp_login_cmd(client, message):
    if not await check_user(msg=message):
        return

    user_id = message.from_user.id
    args = message.text.split()
    
    if len(args) < 3:
        return await message.reply_text(
            "❌ **Format Salah**\n"
            "Gunakan: <code>/beatport_login email password</code>\n\n"
            "⚠️ Password Anda akan disimpan dengan aman untuk login otomatis."
        )
    
    email = args[1]
    password = args[2] 
    
    status_msg = await message.reply_text("🔄 **Verifying Account...**\nMencoba login ke Beatport...")
    
    try:
        # Panggil fungsi add_user_account yang baru di manager.py
        await beatport_manager.add_user_account(user_id, email, password)
        await status_msg.edit_text(
            f"✅ **Login Berhasil!**\n\n"
            f"Akun: <code>{email}</code>\n"
            f"Mode: Private Session\n"
            f"Sekarang bot akan menggunakan akun ini saat Anda mendownload dari Beatport."
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ **Login Gagal:**\n{str(e)}")


# 2. CALLBACK HANDLERS (MENU)
@Client.on_callback_query(filters.regex("^uset_bp_auth"))
async def uset_bp_auth_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    user_id = query.from_user.id
    has_session = beatport_manager.has_private_session(user_id)
    
    text = "🔐 **BEATPORT PRIVATE SESSION**\n\n"
    
    if has_session:
        client_obj = beatport_manager.get_client(user_id)
        email_masked = client_obj.email
        text += f"✅ **Status: LOGGED IN**\n"
        text += f"👤 Akun: <code>{email_masked}</code>\n"
        text += "Bot menggunakan akun ini khusus untuk Anda."
    else:
        text += "❌ **Status: NOT LOGGED IN**\n"
        text += "Bot menggunakan akun Global (Shared) untuk Anda jika tersedia.\n\n"
        text += "Login akun sendiri untuk akses region/konten yang lebih spesifik."

    await edit_message(query.message, text, markup=beatport_user_auth_buttons(has_session))


@Client.on_callback_query(filters.regex("^uset_bp_logout"))
async def uset_bp_logout_handler(client, query):
    if not await check_user(msg=query.message):
        return
        
    user_id = query.from_user.id
    if beatport_manager.has_private_session(user_id):
        await beatport_manager.remove_user_account(user_id)
        await query.answer("✅ Sesi Beatport dihapus. Kembali ke mode Global.", True)
    else:
        await query.answer("Anda belum login.", True)
    
    # Refresh menu
    await uset_bp_auth_handler(client, query)


@Client.on_callback_query(filters.regex("^uset_bp_instr"))
async def uset_bp_instr_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    text = (
        "📝 **CARA LOGIN BEATPORT**\n\n"
        "Kirim perintah ini di chat:\n"
        "<code>/beatport_login email password</code>\n\n"
        "Contoh:\n"
        "<code>/beatport_login myemail@gmail.com rahasia123</code>"
    )
    # Tombol Back
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="uset_bp_auth")]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# ==================================
# BEATSOURCE PRIVATE AUTH
# ==================================

# 1. COMMAND LOGIN (/beatsource_login email password)
@Client.on_message(filters.command("beatsource_login"))
async def uset_bs_login_cmd(client, message):
    if not await check_user(msg=message):
        return

    user_id = message.from_user.id
    args = message.text.split()
    
    if len(args) < 3:
        return await message.reply_text(
            "❌ **Format Salah**\n"
            "Gunakan: <code>/beatsource_login email password</code>\n\n"
            "⚠️ Password Anda akan disimpan dengan aman untuk login otomatis."
        )
    
    email = args[1]
    password = args[2] 
    
    status_msg = await message.reply_text("🔄 **Verifying Account...**\nMencoba login ke Beatsource...")
    
    try:
        # Memanggil fungsi add_user_account di manager yang baru
        await beatsource_manager.add_user_account(user_id, email, password)
        await status_msg.edit_text(
            f"✅ **Login Berhasil!**\n\n"
            f"Akun: <code>{email}</code>\n"
            f"Mode: Private Session\n"
            f"Sekarang bot akan menggunakan akun ini saat Anda mendownload dari Beatsource."
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ **Login Gagal:**\n{str(e)}")


# 2. CALLBACK MENU AUTH (uset_bs_auth)
@Client.on_callback_query(filters.regex("^uset_bs_auth"))
async def uset_bs_auth_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    user_id = query.from_user.id
    # Cek apakah user punya sesi
    has_session = beatsource_manager.has_private_session(user_id)
    
    text = "🔐 **BEATSOURCE PRIVATE SESSION**\n\n"
    
    if has_session:
        client_obj = beatsource_manager.get_client(user_id)
        email_masked = client_obj.email
        text += f"✅ **Status: LOGGED IN**\n"
        text += f"👤 Akun: <code>{email_masked}</code>\n"
        text += "Bot menggunakan akun ini khusus untuk Anda."
    else:
        text += "❌ **Status: NOT LOGGED IN**\n"
        text += "Bot menggunakan akun Global (Shared) untuk Anda jika tersedia.\n\n"
        text += "Login akun sendiri untuk akses region/konten yang lebih spesifik."

    # Render tombol Auth Beatsource
    await edit_message(query.message, text, markup=beatsource_user_auth_buttons(has_session))


# 3. CALLBACK LOGOUT (uset_bs_logout)
@Client.on_callback_query(filters.regex("^uset_bs_logout"))
async def uset_bs_logout_handler(client, query):
    if not await check_user(msg=query.message):
        return
        
    user_id = query.from_user.id
    if beatsource_manager.has_private_session(user_id):
        # Hapus sesi user
        await beatsource_manager.remove_user_account(user_id)
        await query.answer("✅ Sesi Beatsource dihapus. Kembali ke mode Global.", True)
    else:
        await query.answer("Anda belum login.", True)
    
    # Refresh tampilan menu auth
    await uset_bs_auth_handler(client, query)


# 4. CALLBACK INSTRUKSI (uset_bs_instr)
@Client.on_callback_query(filters.regex("^uset_bs_instr"))
async def uset_bs_instr_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    text = (
        "📝 **CARA LOGIN BEATSOURCE**\n\n"
        "Kirim perintah ini di chat:\n"
        "<code>/beatsource_login email password</code>\n\n"
        "Contoh:\n"
        "<code>/beatsource_login myemail@gmail.com rahasia123</code>"
    )
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="uset_bs_auth")]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# ==================================
# HIGHRESAUDIO PRIVATE AUTH
# ==================================

# 1. COMMAND LOGIN (/highresaudio_login email password)
@Client.on_message(filters.command("highresaudio_login"))
async def uset_hra_login_cmd(client, message):
    if not await check_user(msg=message):
        return

    user_id = message.from_user.id
    args = message.text.split()
    
    if len(args) < 3:
        return await message.reply_text(
            "❌ **Format Salah**\n"
            "Gunakan: <code>/highresaudio_login email password</code>\n\n"
            "⚠️ Password Anda akan disimpan dengan aman untuk login otomatis."
        )
    
    email = args[1]
    password = args[2] 
    
    status_msg = await message.reply_text("🔄 **Verifying Account...**\nMencoba login ke HighResAudio...")
    
    try:
        # Memanggil fungsi add_user_account di manager
        # Pastikan Anda sudah menambahkan fungsi add_user_account di HRA manager.py (seperti kode saya sebelumnya)
        success, info = await highresaudio_manager.add_user_account(user_id, email, password)
        
        if success:
            await status_msg.edit_text(
                f"✅ **Login Berhasil!**\n\n"
                f"Akun: <code>{email}</code>\n"
                f"Mode: Private Session\n"
                f"Sekarang bot akan menggunakan akun ini saat Anda mendownload dari HighResAudio."
            )
        else:
            await status_msg.edit_text(f"❌ **Login Gagal:**\n{info}")
            
    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:**\n{str(e)}")


# 2. CALLBACK MENU AUTH (uset_hra_auth)
@Client.on_callback_query(filters.regex("^uset_hra_auth"))
async def uset_hra_auth_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    user_id = query.from_user.id
    # Cek apakah user punya sesi (Logika manual karena get_client HRA mengembalikan objek/None)
    client_obj = highresaudio_manager.get_client(user_id)
    # Pastikan client yang didapat benar-benar milik user (ada di dict user_clients)
    has_session = user_id in highresaudio_manager.user_clients
    
    text = "🔐 **HIGHRESAUDIO PRIVATE SESSION**\n\n"
    
    if has_session and client_obj:
        email_masked = client_obj.email
        text += f"✅ **Status: LOGGED IN**\n"
        text += f"👤 Akun: <code>{email_masked}</code>\n"
        text += "Bot menggunakan akun ini khusus untuk Anda."
    else:
        text += "❌ **Status: NOT LOGGED IN**\n"
        text += "Bot menggunakan akun Global (Shared) untuk Anda jika tersedia.\n\n"
        text += "Login akun sendiri untuk akses region/konten yang lebih spesifik."

    await edit_message(query.message, text, markup=highresaudio_user_auth_buttons(has_session))


# 3. CALLBACK LOGOUT (uset_hra_logout)
@Client.on_callback_query(filters.regex("^uset_hra_logout"))
async def uset_hra_logout_handler(client, query):
    if not await check_user(msg=query.message):
        return
        
    user_id = query.from_user.id
    if user_id in highresaudio_manager.user_clients:
        try:
            highresaudio_manager.user_clients[user_id].close_session()
        except: pass
        del highresaudio_manager.user_clients[user_id]
        
        await query.answer("✅ Sesi HighResAudio dihapus. Kembali ke mode Global.", True)
    else:
        await query.answer("Anda belum login.", True)
    
    # Refresh tampilan menu auth
    await uset_hra_auth_handler(client, query)


# 4. CALLBACK INSTRUKSI (uset_hra_instr)
@Client.on_callback_query(filters.regex("^uset_hra_instr"))
async def uset_hra_instr_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    text = (
        "📝 **CARA LOGIN HIGHRESAUDIO**\n\n"
        "Kirim perintah ini di chat:\n"
        "<code>/highresaudio_login email password</code>\n\n"
        "Contoh:\n"
        "<code>/highresaudio_login myemail@gmail.com rahasia123</code>"
    )
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="uset_hra_auth")]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# ==================================
# QOBUZ PRIVATE AUTH (MULTI-ACCOUNT)
# ==================================

# 1. COMMAND LOGIN (/qobuz_login user_id token)
@Client.on_message(filters.command("qobuz_login"))
async def uset_qb_login_cmd(client, message):
    if not await check_user(msg=message):
        return

    user_id = message.from_user.id
    args = message.text.split()
    
    if len(args) < 3:
        return await message.reply_text(
            "❌ **Format Salah**\n"
            "Gunakan: <code>/qobuz_login user_id user_token</code>\n\n"
            "Cara mendapatkan User ID & Token:\n"
            "1. Buka player.qobuz.com -> Login\n"
            "2. Buka Console (F12) -> Application -> Local Storage\n"
            "3. Cari key `current_user`\n"
            "   - user_id: angka di `id`\n"
            "   - user_token: string di `credential.parameters.user_auth_token`"
        )
    
    q_user_id = args[1]
    q_token = args[2] 
    
    status_msg = await message.reply_text("🔄 **Verifying Qobuz Account...**")
    
    try:
        success, info = await qobuz_manager.add_user_account(user_id, q_user_id, q_token)
        if success:
            await status_msg.edit_text(
                f"✅ **{info}**\n\n"
                f"Akun ID: <code>{q_user_id}</code>\n"
                f"Bot akan mencoba akun ini secara otomatis jika akun lain gagal/region lock."
            )
        else:
            await status_msg.edit_text(f"❌ **Login Gagal:**\n{info}")
    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:**\n{str(e)}")


# 2. HANDLER MENU AUTH (Menampilkan Daftar Akun)
@Client.on_callback_query(filters.regex("^uset_qb_auth"))
async def uset_qb_auth_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    user_id = query.from_user.id
    
    user_data_mem = bot_set.user_data.get(user_id, {})
    accounts_list = user_data_mem.get('qobuz_accounts', [])
    
    text = "🔐 **QOBUZ PRIVATE SESSION**\n\n"
    
    if accounts_list:
        text += f"✅ **Status: {len(accounts_list)} Akun Tersimpan**\n"
            
        text += "\nBot akan mencoba akun secara berurutan. Klik tombol 🗑️ di bawah untuk menghapus akun yang spesifik (misal expired)."
    else:
        text += "❌ **Status: TIDAK ADA AKUN**\n"
        text += "Bot saat ini menggunakan akun Global (Shared).\n\n"
        text += "Anda bisa menambahkan banyak akun pribadi (misal: beda region) untuk melewati batasan geo-restriction."

    await edit_message(query.message, text, markup=qb_user_auth_buttons(accounts_list))


# 3. HANDLER HAPUS AKUN SPESIFIK
@Client.on_callback_query(filters.regex(r"^uset_qb_rm_(.+)"))
async def uset_qb_remove_handler(client, query):
    if not await check_user(msg=query.message):
        return

    user_id = query.from_user.id
    target_q_uid = query.matches[0].group(1) 
    
    result = await qobuz_manager.remove_specific_account(user_id, target_q_uid)
    
    if result:
        await query.answer(f"✅ Akun {target_q_uid} berhasil dihapus.", True)
    else:
        await query.answer("❌ Gagal menghapus (Akun tidak ditemukan).", True)
    
    await uset_qb_auth_handler(client, query)


# 4. HANDLER INSTRUKSI
@Client.on_callback_query(filters.regex("^uset_qb_instr"))
async def uset_qb_instr_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    text = (
        "📝 **CARA LOGIN QOBUZ (MULTI-AKUN)**\n\n"
        "Anda bisa menambahkan lebih dari satu akun.\n"
        "Kirim perintah ini di chat:\n"
        "<code>/qobuz_login user_id user_token</code>\n\n"
        "Contoh:\n"
        "<code>/qobuz_login 123456 r5T6y7U8...</code>"
    )
    buttons = [[InlineKeyboardButton("🔙 Kembali", callback_data="uset_qb_auth")]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# ==================================
# DEEZER PRIVATE AUTH (MULTI-ACCOUNT)
# ==================================

# 1. COMMAND LOGIN
@Client.on_message(filters.command("deezer_login"))
async def uset_dz_login_cmd(client, message):
    if not await check_user(msg=message):
        return

    user_id = message.from_user.id
    args = message.text.split()
    
    if len(args) < 2:
        return await message.reply_text(
            "❌ **Format Salah**\n"
            "Gunakan: <code>/deezer_login arl_anda</code>\n\n"
            "Cara mendapatkan ARL:\n"
            "1. Buka deezer.com -> Login\n"
            "2. F12 (Dev Tools) -> Application -> Cookies -> deezer.com\n"
            "3. Salin value dari cookie bernama `arl`."
        )
    
    arl = args[1].strip()
    status_msg = await message.reply_text("🔄 **Verifying Deezer Account...**")
    
    try:
        success, info = await deezer_manager.add_user_account(user_id, arl)
        if success:
            await status_msg.edit_text(f"✅ **{info}**")
        else:
            await status_msg.edit_text(f"❌ **Login Gagal:**\n{info}")
    except Exception as e:
        await status_msg.edit_text(f"❌ **Error:**\n{str(e)}")

# 2. MENU AUTH
@Client.on_callback_query(filters.regex("^uset_dz_auth"))
async def uset_dz_auth_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    user_id = query.from_user.id
    user_data_mem = bot_set.user_data.get(user_id, {})
    accounts_list = user_data_mem.get('deezer_accounts', [])
    
    text = "🔐 **DEEZER PRIVATE SESSION**\n\n"
    if accounts_list:
        text += f"✅ **Status: {len(accounts_list)} Akun Tersimpan**\n"
        for idx, acc in enumerate(accounts_list):
            label = acc.get('label', 'Unknown')
            text += f"{idx+1}. <b>{label}</b>\n"
    else:
        text += "❌ **Status: TIDAK ADA AKUN**\n"
        text += "Bot menggunakan akun Global jika tersedia.\n"

    # Pastikan Anda import 'deezer_user_auth_buttons' dari settings.py di bagian atas file ini!
    await edit_message(query.message, text, markup=deezer_user_auth_buttons(accounts_list))

# 3. HAPUS AKUN
@Client.on_callback_query(filters.regex(r"^uset_dz_rm_(.+)"))
async def uset_dz_remove_handler(client, query):
    if not await check_user(msg=query.message):
        return
    user_id = query.from_user.id
    target = query.matches[0].group(1) 
    if await deezer_manager.remove_specific_account(user_id, target):
        await query.answer("✅ Akun dihapus.", True)
    else:
        await query.answer("❌ Gagal.", True)
    await uset_dz_auth_handler(client, query)

# 4. INSTRUKSI
@Client.on_callback_query(filters.regex("^uset_dz_instr"))
async def uset_dz_instr_handler(client, query):
    text = "Ketik: <code>/deezer_login arl_anda_disini</code>"
    buttons = [[InlineKeyboardButton("🔙 Kembali", callback_data="uset_dz_auth")]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# ==================================
# TIDAL USER PRIVATE AUTH
# ==================================

# 1. Tombol Menu Auth di Panel Tidal (Callback)
@Client.on_callback_query(filters.regex("^utd_auth_menu"))
async def uset_tidal_auth_menu(client, query):
    if not await check_user(msg=query.message): return
    
    user_id = query.from_user.id
    
    # Cek apakah user sudah login
    user_client = await tidal_manager.get_user_client(user_id)
    
    text = "**🔐 TIDAL PRIVATE SESSION**\n\n"
    buttons = []

    if user_client:
        sub = user_client.sub_type or "Unknown"
        country = user_client.country_code or "??"
        text += f"✅ **Status: LOGGED IN**\n"
        text += f"👤 User ID: `{user_client.user_id}`\n"
        text += f"🏳️ Region: {country} | 💎 Plan: {sub}\n\n"
        text += "Bot akan menggunakan akun ini KHUSUS untuk Anda."
        
        # Tombol Logout
        buttons.append([InlineKeyboardButton("🚪 LOGOUT SESSION", callback_data="utd_logout")])
    else:
        text += "❌ **Status: NOT LOGGED IN**\n"
        text += "Bot menggunakan akun Global (Shared) untuk Anda.\n"
        text += "Login akun sendiri untuk akses region/konten khusus dan kualitas HiRes pribadi."
        
        # Tombol Login
        buttons.append([InlineKeyboardButton("➕ LOGIN ACCOUNT (TV CODE)", callback_data="utd_login_start")])

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="uset_tidal")])
    await edit_message(query.message, text, InlineKeyboardMarkup(buttons))


# 2. Proses Login (Generate Code)
@Client.on_callback_query(filters.regex("^utd_login_start"))
async def uset_tidal_login_start(client, query):
    if not await check_user(msg=query.message): return
    
    temp_client = TidalApi()
    try:
        auth_url, err = await temp_client.get_tv_login_url()
        if err:
            await temp_client.close()
            return await query.answer(f"Error: {err}", True)
        
        text = (
            "**TIDAL TV LOGIN**\n\n"
            f"1. Buka link ini: [LOGIN LINK]({auth_url})\n"
            "2. Login dan izinkan akses.\n"
            "3. Setelah sukses di browser, klik tombol **'✅ I HAVE LOGGED IN'** di bawah."
        )
        
        # Simpan temp_client di memory sementara bot (bukan manager) agar bisa diakses saat verify
        # Kita gunakan bot_set.user_data untuk simpan object sementara
        bot_set.user_data.setdefault(query.from_user.id, {})['temp_tidal_auth'] = temp_client
        
        buttons = [
            [InlineKeyboardButton("✅ I HAVE LOGGED IN", callback_data="utd_login_verify")],
            [InlineKeyboardButton("❌ Cancel", callback_data="utd_auth_menu")]
        ]
        await edit_message(query.message, text, InlineKeyboardMarkup(buttons))
        
    except Exception as e:
        await temp_client.close()
        await query.answer(f"Error: {e}", True)


# 3. Proses Verifikasi Login
@Client.on_callback_query(filters.regex("^utd_login_verify"))
async def uset_tidal_login_verify(client, query):
    if not await check_user(msg=query.message): return
    
    user_id = query.from_user.id
    temp_client = bot_set.user_data.get(user_id, {}).get('temp_tidal_auth')
    
    if not temp_client:
        return await query.answer("Sesi kadaluarsa. Silakan ulangi login.", True)
    
    await edit_message(query.message, "🔄 **Verifying...**")
    
    try:
        sub, err = await temp_client.login_tv()
        if err:
            await temp_client.close()
            # Kembali ke menu awal dengan error
            return await edit_message(
                query.message, 
                f"❌ **Login Gagal:** {err}\nSilakan coba lagi.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="utd_auth_menu")]])
            )
        
        # Sukses -> Simpan ke Manager & DB
        auth_data = {
            'refresh_token': temp_client.tv_session.refresh_token,
            'country_code': temp_client.tv_session.country_code,
            'user_id': temp_client.tv_session.user_id
        }
        
        await tidal_manager.add_user_account(user_id, auth_data)
        
        # Bersihkan temp
        await temp_client.close()
        bot_set.user_data[user_id].pop('temp_tidal_auth', None)
        
        await query.answer("✅ Login Berhasil!", True)
        await uset_tidal_auth_menu(client, query)
        
    except Exception as e:
        if temp_client: await temp_client.close()
        await edit_message(query.message, f"Error Fatal: {e}")


# 4. Logout
@Client.on_callback_query(filters.regex("^utd_logout"))
async def uset_tidal_logout(client, query):
    if not await check_user(msg=query.message): return
    
    user_id = query.from_user.id
    await tidal_manager.remove_user_account(user_id)
    
    await query.answer("✅ Sesi dihapus. Kembali ke mode Global.", True)
    await uset_tidal_auth_menu(client, query)


# ==================================
# MENU PENGATURAN UTAMA
# ==================================

@Client.on_message(filters.command(cmd.USETTING))
async def start_user_setting(client: Client, m: Message, edit=False, users_: dict=None):
    if not await check_user(msg=m):
        return
    
    user = await fetch_user_details(m)
    user_data = users_ if users_ else user
    user_id = user_data['user_id']
    
    # Ambil pengaturan ZIP
    PLAYLIST_ZIP, ALBUM_ZIP, ARTIST_ZIP, ART_POSTER = await asyncio.to_thread(fetch_zip_settings, user_data)
    
    # Ambil Pengaturan Cloud Upload
    curr_settings = bot_set.user_data.get(user_id, {})
    upload_mode = curr_settings.get('upload_mode', 'Telegram')
    
    # Cek status ketersediaan token (Indikator UI)
    t_gf = "✅" if curr_settings.get('gofile_token') else "❌"
    t_bh = "✅" if curr_settings.get('buzzheavier_token') else "❌"
    t_vk = "✅" if curr_settings.get('viking_token') else "❌"

    # Template Teks Menu
    USETTING_TEXT = f"""
<blockquote>
<b>📦 ZIP SETTINGS</b>
PLAYLIST : {PLAYLIST_ZIP} | ALBUM : {ALBUM_ZIP}
ARTIST : {ARTIST_ZIP} | POSTER : {ART_POSTER}

<b>☁️ UPLOAD MODE: {upload_mode}</b>
Gofile: {t_gf} | Buzz: {t_bh} | Viking: {t_vk}
</blockquote>
{m.date.now().strftime("%d/%m/%Y %H:%M:%S")}
Choose Menu option below:
"""
    
    if not edit:
        await send_message(user, USETTING_TEXT, markup=usetting_button(user_id))
        return
    await edit_message(m, USETTING_TEXT, markup=usetting_button(user_id))


# --- HANDLER GANTI MODE UPLOAD (CYCLING) ---
@Client.on_callback_query(filters.regex("^uset_upload_mode"))
async def uset_upload_mode_handler(client, query):
    if not await check_user(msg=query.message):
        return

    user_id = query.from_user.id
    current_mode = bot_set.user_data.get(user_id, {}).get('upload_mode', 'Telegram')
    
    # Daftar Mode yang tersedia
    modes = ['Telegram', 'Gofile', 'Buzzheavier', 'Vikingfiles']
    
    # Cari index saat ini
    try:
        idx = modes.index(current_mode)
    except ValueError:
        idx = 0
        
    # Pindah ke mode selanjutnya (Looping)
    next_idx = (idx + 1) % len(modes)
    new_mode = modes[next_idx]
    
    # Simpan Perubahan
    bot_set.user_data.setdefault(user_id, {})['upload_mode'] = new_mode
    await database.save_user_settings(user_id, {'upload_mode': new_mode})
    
    # Refresh Menu
    users_ = {"user_id": user_id}
    await start_user_setting(client, query.message, True, users_)


# --- HANDLER UTAMA TOMBOL MENU (PROVIDER SETTINGS) ---
@Client.on_callback_query(filters.regex("^uset_(tidal|back|qobuz|close|beatport|deezer|kkbox|beatsource|soundcloud|napster|idagio|bugs|moov|livephish|highresaudio|khinsider)"))
async def uset_cb(client, query, datatype=""):
    if not await check_user(msg=query.message):
        return
    data = query.data.split("_")
    user_id = query.from_user.id

    if data[1] == "back":
        users_ = {"user_id": user_id}
        return await start_user_setting(client, query.message, True, users_)
    if data[1] == "close":
        await query.message.delete()
        return
        
    # --- TIDAL MENU ---
    if data[1] == "tidal" or datatype == "tidal":
        if not tidal_manager:
            return await edit_message(query.message, "Layanan Tidal tidak aktif.")
            
        text = f"Choose Tidal Audio Quality bellow:"
        qualities = {
              'LOW': 'LOW',
              'HIGH': 'HIGH',
              'LOSSLESS': 'LOSSLESS'
        }
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        await tidal_manager.setup_user_settings(
            user_id,
            qual=main_user_dict.get("tidal_qual"),
            spatial=main_user_dict.get("tidal_spatial"),
            mqa_fix=main_user_dict.get("tidal_mqa_fix"),
            convert_m4a=main_user_dict.get("tidal_convert_m4a")
        )
        user_qual, user_spatial, _, __ = tidal_manager.get_user_quality_settings(user_id)
        
        # --- [LOGIKA BARU: CEK GLOBAL + PRIVATE] ---
        has_hires = False
        
        # 1. Cek Admin/Global
        if tidal_manager.clients and any(c.mobile_hires for c in tidal_manager.clients):
            has_hires = True
            
        # 2. Cek Akun Private User
        # (Kita panggil get_user_client agar status hires akun user terbaca)
        user_client = await tidal_manager.get_user_client(user_id)
        if user_client and getattr(user_client, 'mobile_hires', False):
            has_hires = True

        # Jika salah satu support HiRes, tampilkan tombol MAX
        if has_hires:
            qualities['HI_RES'] = 'MAX'
            
        # Safety Fallback: Jika user terlanjur set HI_RES tapi terdeteksi false
        # (misal error sesaat), tetap paksa munculkan agar tidak Crash (KeyError)
        if user_qual == 'HI_RES' and 'HI_RES' not in qualities:
            qualities['HI_RES'] = 'MAX'
        # -------------------------------------------

        if user_qual in qualities:
            qualities[user_qual] += '✅'
        else:
            # Fallback jika ada value aneh dari DB
            if 'LOSSLESS' in qualities:
                qualities['LOSSLESS'] += '✅'
            
        return await edit_message(query.message, text, tidal_quality_button(qualities, user_id, spatial=user_spatial))
    
    # --- QOBUZ MENU ---
    if data[1] == "qobuz" or datatype == "qobuz":
        text = f"Choose Qobuz Audio Quality bellow:"
        quality = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}
        
        # [MODIFIKASI] Cek apakah ada klien (Global ATAU Private Session)
        has_client = False
        
        # 1. Cek Klien Global (Bot)
        if BOT_QOBUZ_CLIENTS:
            has_client = True
        # 2. Cek Klien Private (User) via Manager
        elif qobuz_manager and qobuz_manager.has_private_session(user_id):
            has_client = True
            
        if not has_client:
            return await edit_message(query.message, "Layanan Qobuz tidak aktif (tidak ada klien yang login).")

        # Ambil setting user (Default ke 6/Lossless jika belum diatur)
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("qobuz_qual", 6) 
        
        # [MODIFIKASI] Simpan setting kualitas ke DB Manager agar terbaca oleh qopy.py
        if qobuz_manager:
            await qobuz_manager.setup_quality(user_id, current)
        
        try:
            current = int(current)
        except:
            pass

        if current in quality:
            quality[current] = quality[current] + '✅'
            
        # Tombol qb_button (yang sudah dimodifikasi di settings.py) akan menampilkan opsi "Private Account"
        return await edit_message(query.message, text, markup=qb_button(quality, user_id))

    # --- BEATPORT MENU ---
    if data[1] == "beatport" or datatype == "beatport":
        text = f"Choose Beatport Audio Quality bellow:"
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }
        # Cek apakah ada klien (Global ATAU User)
        has_client = False
        if beatport_manager and (beatport_manager.global_clients or beatport_manager.has_private_session(user_id)):
             has_client = True
             
        if not has_client:
            return await edit_message(query.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")

        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("beatport_qual", beatport_manager.quality) 
        await beatport_manager.setup_quality(user_id, current) 
        
        if current in quality:
            quality[current] = quality[current] + '✅'
            
        # Tombol bp_button sekarang akan menyertakan tombol "PRIVATE ACCOUNT"
        return await edit_message(query.message, text, markup=bp_button(quality, user_id))

    # --- BEATSOURCE MENU ---
    if data[1] == "beatsource" or datatype == "beatsource":
        text = f"Choose Beatsource Audio Quality bellow:"
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }
        if not beatsource_manager or not beatsource_manager.clients:
            return await edit_message(query.message, "Layanan Beatsource tidak aktif (tidak ada klien yang login).")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("beatsource_qual", beatsource_manager.quality) 
        await beatsource_manager.setup_quality(user_id, current) 
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        return await edit_message(
            query.message,
            text + "\n(Kualitas tergantung langganan akun bot)",
            markup=bs_button(quality, user_id)
        )
    
    # --- SOUNDCLOUD MENU ---
    if data[1] == "soundcloud" or datatype == "soundcloud":
        text = f"Choose Soundcloud Audio Quality bellow:"
        quality = {
            "original": "Original (Jika Ada)",
            "stream": "Stream (Default AAC/MP3)"
        }
        if not soundcloud_manager or not soundcloud_manager.get_client():
            return await edit_message(query.message, "Layanan Soundcloud tidak aktif.")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("soundcloud_qual", soundcloud_manager.quality) 
        await soundcloud_manager.setup_quality(user_id, current)
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        return await edit_message(
            query.message,
            text,
            markup=sc_button(quality, user_id)
        )

    # --- DEEZER MENU ---
    if data[1] == "deezer" or datatype == "deezer":
        text = f"Choose Deezer Audio Quality bellow:"
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "MP3 320",
            "MP3_128": "MP3 128"
        }
        
        # [MODIFIKASI] Cek Akun Global ATAU Akun Private
        has_client = False
        if deezer_manager:
            if deezer_manager.clients or deezer_manager.has_private_session(user_id):
                has_client = True

        if not has_client:
            return await edit_message(query.message, "Layanan Deezer tidak aktif (tidak ada klien yang login).")

        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("deezer_qual", deezer_manager.quality) 
        await deezer_manager.setup_quality(user_id, current) 
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text, markup=dz_button(quality, user_id))

    # --- KKBOX MENU ---
    if data[1] == "kkbox" or datatype == "kkbox":
        text = f"Choose KKBox Audio Quality bellow:"
        quality = {
            "128k": "MP3 128k",
            "192k": "MP3 192k",
            "320k": "AAC 320k",
            "hifi": "FLAC 16-bit",
            "hires": "FLAC 24-bit"
        }
        if not kkbox_manager or not kkbox_manager.clients:
            return await edit_message(query.message, "Layanan KKBox tidak aktif (tidak ada klien yang login).")

        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("kkbox_qual", kkbox_manager.quality) 
        await kkbox_manager.setup_quality(user_id, current) 
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text, markup=kk_button(quality, user_id))

    # --- NAPSTER MENU ---
    if data[1] == "napster" or datatype == "napster":
        text = f"Choose Napster Audio Quality bellow:"
        quality = {
            "FLAC": "FLAC (HiRes/Lossless)",
            "MP3_320": "AAC 320k",
            "MP3_192": "AAC 192k",
            "MP3_128": "AAC 128k",
            "MP3_64": "HE-AAC 64k"
        }
        if not napster_manager or not napster_manager.clients:
            return await edit_message(query.message, "Layanan Napster tidak aktif (tidak ada klien yang login).")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("napster_qual", napster_manager.quality) 
        await napster_manager.setup_quality(user_id, current)
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text + "\n(Kualitas akhir tergantung langganan akun bot)", markup=np_button(quality, user_id))

    # --- IDAGIO MENU ---
    if data[1] == "idagio" or datatype == "idagio":
        text = f"Choose Idagio Audio Quality bellow:"
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "AAC 320k",
            "MP3_160": "AAC 160k"
        }
        if not idagio_manager or not idagio_manager.clients:
            return await edit_message(query.message, "Layanan Idagio tidak aktif (tidak ada klien yang login).")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("idagio_qual", idagio_manager.quality) 
        await idagio_manager.setup_quality(user_id, current)
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text, markup=id_button(quality, user_id))

    # --- BUGS MENU ---
    if data[1] == "bugs" or datatype == "bugs":
        text = f"Choose Bugs Audio Quality bellow:"
        quality = {
            "flac": "FLAC 16-bit",
            "aac256": "AAC 320k",
            "320k": "MP3 320k",
            "aac": "AAC 128k"
        }
        if not bugs_manager or not bugs_manager.clients:
            return await edit_message(query.message, "Layanan Bugs tidak aktif (tidak ada klien yang login).")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("bugs_qual", bugs_manager.quality) 
        await bugs_manager.setup_quality(user_id, current)
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text + "\n(Kualitas FLAC tergantung langganan akun bot)", markup=bugs_button(quality, user_id))

    # --- MOOV MENU ---
    if data[1] == "moov" or datatype == "moov":
        text = f"Choose Moov Audio Quality bellow:\n(Moov menyediakan FLAC 16bit & 24bit)"
        quality = {
            "FLAC": "Max (24bit/HR)",
            "MP3_320": "Std (16bit/LL)"
        }
        if not moov_manager or not moov_manager.clients:
            return await edit_message(query.message, "Layanan Moov tidak aktif!")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("moov_qual", moov_manager.quality) 
        
        await moov_manager.setup_quality(user_id, current)
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        return await edit_message(query.message, text, markup=mv_button(quality, user_id))

    # --- LIVEPHISH MENU ---
    if data[1] == "livephish" or datatype == "livephish":
        text = f"Choose LivePhish Audio Quality bellow:"
        quality = {
            "FLAC": "FLAC (16-bit)",
            "ALAC": "ALAC (16-bit)",
            "AAC": "AAC"
        }
        if not livephish_manager or not livephish_manager.clients:
             return await edit_message(query.message, "Layanan LivePhish tidak aktif!")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("livephish_qual", livephish_manager.quality)
        
        await livephish_manager.setup_quality(user_id, current)
        
        if current in quality:
            quality[current] += '✅'
        
        return await edit_message(query.message, text, markup=lp_button(quality, user_id))

    # --- HIGHRESAUDIO SPECIFIC ---
    if data[1] == "highresaudio" or datatype == "highresaudio":
        text = f"HighResAudio Settings:"
        if not highresaudio_manager:
            return await edit_message(query.message, "Layanan HighResAudio tidak aktif.")
        
        # Tampilkan tombol HRA
        return await edit_message(query.message, text, markup=hra_button(user_id))

    # --- KHINSIDER MENU ---
    if data[1] == "khinsider" or datatype == "khinsider":
        text = f"Choose Khinsider Preferred Format:"
        quality = {
            "flac": "FLAC",
            "mp3": "MP3"
        }
        if not khinsider_manager:
             return await edit_message(query.message, "Layanan Khinsider tidak aktif!")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("khinsider_qual", khinsider_manager.quality)
        
        await khinsider_manager.setup_quality(user_id, current)
        
        if current in quality:
            quality[current] += '✅'
        
        return await edit_message(query.message, text, markup=khi_button(quality, user_id))


# --- HANDLER SETTING TIDAL SPECIFIC ---
@Client.on_callback_query(filters.regex("^utdqs"))
async def uset_tidal(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    data = query.data 
    user_id = query.from_user.id
    
    if not tidal_manager:
        await query.answer("Layanan Tidal tidak aktif!", show_alert=True)
        return
        
    try:
        if data.startswith("utdqs_mqa_"):
            new_state = data.split("_")[-1]
            bot_set.user_data.setdefault(user_id, {})["tidal_mqa_fix"] = new_state
            await database.save_user_settings(user_id, {"tidal_mqa_fix": new_state})
            await tidal_manager.setup_user_settings(user_id, mqa_fix=new_state)

        elif data.startswith("utdqs_convert_"):
            new_state = data.split("_")[-1]
            bot_set.user_data.setdefault(user_id, {})["tidal_convert_m4a"] = new_state
            await database.save_user_settings(user_id, {"tidal_convert_m4a": new_state})
            await tidal_manager.setup_user_settings(user_id, convert_m4a=new_state)

        elif data == "utdqs_spatial":
            user_client = await tidal_manager.get_user_client(user_id)
            
            has_atmos = False
            has_360 = False
            
            if tidal_manager.clients:
                if any(c.mobile_atmos for c in tidal_manager.clients): has_atmos = True
                if any(c.mobile_atmos or c.mobile_hires for c in tidal_manager.clients): has_360 = True
            
            if user_client:
                if getattr(user_client, 'mobile_atmos', False): has_atmos = True
                if getattr(user_client, 'mobile_atmos', False) or getattr(user_client, 'mobile_hires', False): has_360 = True

            options = ['OFF', 'ATMOS AC3 JOC']
            if has_atmos:
                options.append('ATMOS AC4')
            if has_360:
                options.append('Sony 360RA')
                
            main_user_dict = bot_set.user_data.get(user_id, {})
            user_spatial = main_user_dict.get("tidal_spatial", tidal_manager.spatial)
            
            try:
                current = options.index(user_spatial)
            except:
                current = 0
            nexti = (current + 1) % len(options)
            new_spatial = options[nexti]
            
            bot_set.user_data.setdefault(user_id, {})["tidal_spatial"] = new_spatial
            await database.save_user_settings(user_id, {"tidal_spatial": new_spatial})
            await tidal_manager.setup_user_settings(user_id, spatial=new_spatial)
        
        else:
            to_set = data.split('_')[1]
            qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
            
            to_set_qual = "LOSSLESS"
            for k, v in qualities.items():
                if v == to_set:
                    to_set_qual = k
                    break

            bot_set.user_data.setdefault(user_id, {})["tidal_qual"] = to_set_qual
            await database.save_user_settings(user_id, {"tidal_qual": to_set_qual})
            await tidal_manager.setup_user_settings(user_id, qual=to_set_qual)
        
        return await uset_cb(client, query, "tidal")

    except Exception:
        logging.error(format_exc())
        

# --- HANDLER SETTING QOBUZ SPECIFIC ---
@Client.on_callback_query(filters.regex("^uqbs"))
async def uset_qobuz(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qobuz = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}
    to_set = query.data.split('_')[1]
    qobuz_qual = list(filter(lambda x: qobuz[x] == to_set, qobuz))[0]
    
    if not BOT_QOBUZ_CLIENTS:
        await query.answer("Layanan Qobuz tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    bot_set.user_data.setdefault(user_id, {})["qobuz_qual"] = int(qobuz_qual)
    await database.save_user_settings(user_id, {"qobuz_qual": int(qobuz_qual)})
    
    for q_client in BOT_QOBUZ_CLIENTS.values():
        await q_client.setup_quality(int(user_id), int(qobuz_qual))
    
    await uset_cb(client, query, "qobuz")


# --- HANDLER BEATPORT SPECIFIC ---
@Client.on_callback_query(filters.regex("^ubps"))
async def uset_beatport(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "Lossless (FLAC)": "lossless",
        "High (AAC 256)": "high",
        "Medium (AAC 128)": "medium"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    
    has_client = False
    if beatport_manager and (beatport_manager.global_clients or beatport_manager.has_private_session(query.from_user.id)):
         has_client = True

    if not has_client:
        await query.answer("Layanan Beatport tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id
    
    await beatport_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['beatport_qual'] = to_set 
    await database.save_user_settings(user_id, {'beatport_qual': to_set})
    
    await uset_cb(client, query, "beatport")


# --- HANDLER BEATSOURCE SPECIFIC ---
@Client.on_callback_query(filters.regex("^usbs"))
async def uset_beatsource(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    qual_map_display = {
        "Lossless (FLAC)": "lossless",
        "High (AAC 256)": "high",
        "Medium (AAC 128)": "medium"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)

    if not beatsource_manager or not beatsource_manager.clients:
        await query.answer("Layanan Beatsource tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    await beatsource_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['beatsource_qual'] = to_set 
    await database.save_user_settings(user_id, {'beatsource_qual': to_set})
    
    await uset_cb(client, query, "beatsource")


# --- HANDLER SOUNDCLOUD SPECIFIC ---
@Client.on_callback_query(filters.regex("^uscs"))
async def uset_soundcloud(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    qual_map_display = {
        "Original (Jika Ada)": "original",
        "Stream (Default AAC/MP3)": "stream"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)

    if not soundcloud_manager or not soundcloud_manager.get_client():
        await query.answer("Layanan Soundcloud tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    await soundcloud_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['soundcloud_qual'] = to_set 
    await database.save_user_settings(user_id, {'soundcloud_qual': to_set})
    
    await uset_cb(client, query, "soundcloud")


# --- HANDLER DEEZER SPECIFIC ---
@Client.on_callback_query(filters.regex("^udzs"))
async def uset_deezer(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "FLAC": "FLAC",
        "MP3 320": "MP3_320",
        "MP3 128": "MP3_128"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not deezer_manager or not deezer_manager.clients:
        await query.answer("Layanan Deezer tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id

    await deezer_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['deezer_qual'] = to_set 
    await database.save_user_settings(user_id, {'deezer_qual': to_set})
    
    await uset_cb(client, query, "deezer")


# --- HANDLER KKBOX SPECIFIC ---
@Client.on_callback_query(filters.regex("^ukks"))
async def uset_kkbox(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "MP3 128k": "128k",
        "MP3 192k": "192k",
        "AAC 320k": "320k",
        "FLAC 16-bit": "hifi",
        "FLAC 24-bit": "hires"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not kkbox_manager or not kkbox_manager.clients:
        await query.answer("Layanan KKBox tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id
    
    await kkbox_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['kkbox_qual'] = to_set 
    await database.save_user_settings(user_id, {'kkbox_qual': to_set})

    await uset_cb(client, query, "kkbox")


# --- HANDLER NAPSTER SPECIFIC ---
@Client.on_callback_query(filters.regex("^unps"))
async def uset_napster(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "FLAC (HiRes/Lossless)": "FLAC",
        "AAC 320k": "MP3_320",
        "AAC 192k": "MP3_192",
        "AAC 128k": "MP3_128",
        "HE-AAC 64k": "MP3_64"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not napster_manager or not napster_manager.clients:
        await query.answer("Layanan Napster tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id
    
    await napster_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['napster_qual'] = to_set 
    await database.save_user_settings(user_id, {'napster_qual': to_set})

    await uset_cb(client, query, "napster")


# --- HANDLER IDAGIO SPECIFIC ---
@Client.on_callback_query(filters.regex("^uids"))
async def uset_idagio(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "FLAC": "FLAC",
        "AAC 320k": "MP3_320",
        "AAC 160k": "MP3_160"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not idagio_manager or not idagio_manager.clients:
        await query.answer("Layanan Idagio tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id
    
    await idagio_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['idagio_qual'] = to_set 
    await database.save_user_settings(user_id, {'idagio_qual': to_set})

    await uset_cb(client, query, "idagio")


# --- HANDLER BUGS SPECIFIC ---
@Client.on_callback_query(filters.regex("^ubgs"))
async def uset_bugs(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "FLAC 16-bit": "flac",
        "AAC 320k": "aac256",
        "MP3 320k": "320k",
        "AAC 128k": "aac"
    }
    
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not bugs_manager or not bugs_manager.clients:
        await query.answer("Layanan Bugs tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id
    
    await bugs_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['bugs_qual'] = to_set 
    await database.save_user_settings(user_id, {'bugs_qual': to_set})

    await uset_cb(client, query, "bugs")


# --- HANDLER MOOV SPECIFIC ---
@Client.on_callback_query(filters.regex("^umvs"))
async def uset_moov_handler(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    # Data format: umvs_FLAC, umvs_MP3_320
    to_set = query.data.split('_')[1]
    
    if not moov_manager or not moov_manager.clients:
        await query.answer("Layanan Moov tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    # Simpan ke Manager & DB
    await moov_manager.setup_quality(user_id, to_set) 
    bot_set.user_data.setdefault(user_id, {})['moov_qual'] = to_set 
    await database.save_user_settings(user_id, {'moov_qual': to_set})
    
    await uset_cb(client, query, "moov")


# --- HANDLER LIVEPHISH SPECIFIC ---
@Client.on_callback_query(filters.regex("^ulps"))
async def uset_livephish_handler(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    # Data format: ulps_FLAC, ulps_AAC
    to_set = query.data.split('_')[1]
    
    if not livephish_manager or not livephish_manager.clients:
        await query.answer("Layanan LivePhish tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    # Simpan ke Manager & DB
    await livephish_manager.setup_quality(user_id, to_set)
    bot_set.user_data.setdefault(user_id, {})['livephish_qual'] = to_set
    await database.save_user_settings(user_id, {'livephish_qual': to_set})
    
    await uset_cb(client, query, "livephish")


# --- HANDLER KHINSIDER SPECIFIC ---
@Client.on_callback_query(filters.regex("^ukhis"))
async def uset_khinsider_handler(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    # Data format: ukhis_flac, ukhis_mp3
    to_set = query.data.split('_')[1]
    
    if not khinsider_manager:
        await query.answer("Layanan Khinsider tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    # Simpan ke Manager & DB
    await khinsider_manager.setup_quality(user_id, to_set)
    bot_set.user_data.setdefault(user_id, {})['khinsider_qual'] = to_set
    await database.save_user_settings(user_id, {'khinsider_qual': to_set})
    
    await uset_cb(client, query, "khinsider")


# --- HANDLER CALLBACK BARU UNTUK LIRIK ---
@Client.on_callback_query(filters.regex("^uset_ly"))
async def uset_lyrics_handler(client, query):
    if not await check_user(msg=query.message):
        return
    
    data = query.data
    user_id = query.from_user.id
    
    # Inisialisasi dictionary jika belum ada
    if user_id not in bot_set.user_data:
        bot_set.user_data[user_id] = {}
    
    # 1. Masuk Menu
    if data == "uset_lyrics":
        pass # Langsung render di bawah

    # 2. Toggle ON/OFF
    elif data == "uset_ly_on":
        bot_set.user_data[user_id]['lyrics_status'] = True
        await database.save_user_settings(user_id, {'lyrics_status': True})
    elif data == "uset_ly_off":
        bot_set.user_data[user_id]['lyrics_status'] = False
        await database.save_user_settings(user_id, {'lyrics_status': False})

    # 3. Ganti Provider
    elif data.startswith("uset_ly_p_"):
        prov = data.split("_")[-1]
        bot_set.user_data[user_id]['lyrics_provider'] = prov
        await database.save_user_settings(user_id, {'lyrics_provider': prov})

    # 4. Ganti Tipe
    elif data.startswith("uset_ly_t_"):
        typ = data.split("_")[-1]
        bot_set.user_data[user_id]['lyrics_type'] = typ
        await database.save_user_settings(user_id, {'lyrics_type': typ})

    # Render Menu
    text = "<b>Lyrics Settings</b>\n\nConfigure how you want to download lyrics."
    await edit_message(query.message, text, markup=lyrics_button(bot_set.user_data[user_id], user_id))


# --- HANDLER ZIP SETTINGS ---
@Client.on_callback_query(filters.regex("^zip"))
async def uset_zip(self, query):
    if not await check_user(msg=query.message):
        return
    data = query.data.split("_")[1].lower()
    user_id = query.from_user.id
    users_ = {"user_id": user_id}
    
    # Toggle Playlist Zip
    if data == "playlist":
        user_dict = bot_set.user_data.get(user_id, {})
        playlist_zip = user_dict.get("playlist_zip", False)
        data_saved = {"PLAYLIST_ZIP".lower(): not playlist_zip}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Playlist zip: {data_saved['playlist_zip']}")
        return await start_user_setting(self, query.message, True, users_)
    
    # Toggle Album Zip
    if data == "album":
        user_dict = bot_set.user_data.get(user_id, {})
        album_zip = user_dict.get("album_zip", False)
        data_saved = {"ALBUM_ZIP".lower(): not album_zip}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Album zip: {data_saved['album_zip']}")
        return await start_user_setting(self, query.message, True, users_)
    
    # Toggle Artist Zip
    if data == "artist":
        user_dict = bot_set.user_data.get(user_id, {})
        artist_zip = user_dict.get("artist_zip", False)
        data_saved = {"ARTIST_ZIP".lower(): not artist_zip}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Artist zip: {data_saved['artist_zip']}")
        return await start_user_setting(self, query.message, True, users_)
    
    # Toggle Art Poster
    if data == "poster":
        user_dict = bot_set.user_data.get(user_id, {})
        art_poster = user_dict.get("art_poster", False)
        data_saved = {"art_poster": not art_poster}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Art poster: {data_saved['art_poster']}")
        return await start_user_setting(self, query.message, True, users_)


# --- DEBUG HANDLER (ADMIN ONLY) ---
@Client.on_message(filters.command("debug") & filters.user(list(Config.ADMINS)))
async def debug(c, m): 
    # QOBUZ DEBUG
    dt_qb = "QOBUZ:\n"
    if BOT_QOBUZ_CLIENTS:
        first_client = BOT_QOBUZ_CLIENTS.get(1) or list(BOT_QOBUZ_CLIENTS.values())[0]
        dt_qb += f"{len(BOT_QOBUZ_CLIENTS)} klien Qobuz aktif.\n"
        dt_qb += f"Label Klien #1: {first_client.label}\n"
        dt_qb += f"Kualitas Default Klien #1: {first_client.quality}"
    else:
        dt_qb += "Tidak ada klien Qobuz yang aktif."

    # BEATPORT DEBUG
    dt_bp = "\n\nBEATPORT:\n"
    if beatport_manager:
        dt_bp += f"Global Clients: {len(beatport_manager.global_clients)}\n"
        dt_bp += f"Private User Clients: {len(beatport_manager.user_clients)}\n"
        dt_bp += f"Global Default Quality: {beatport_manager.quality}\n"
    else:
        dt_bp += "Beatport Manager tidak aktif."

    # BEATSOURCE DEBUG
    dt_bs = "\n\nBEATSOURCE:\n"
    if beatsource_manager and beatsource_manager.clients:
        dt_bs += f"{len(beatsource_manager.clients)} klien Beatsource aktif.\n"
        dt_bs += f"Kualitas Default: {beatsource_manager.quality}\n"
        dt_bs += f"Cache User (Global): {len([u for u in bot_set.user_data if 'beatsource_qual' in bot_set.user_data[u]])} pengguna\n"
        dt_bs += f"Cache Langganan: { {k.session.cookie_jar.filter_cookies(k.API_URL).get('sessionid').value[:5]+'...': v for k, v in beatsource_manager.subscription_cache.items()} }"
    else:
        dt_bs += "Tidak ada klien Beatsource yang aktif."
    
    # SOUNDCLOUD DEBUG
    dt_sc = "\n\nSOUNDCLOUD:\n"
    if soundcloud_manager and soundcloud_manager.get_client():
        dt_sc += f"Klien Soundcloud aktif (Token diatur).\n"
        dt_sc += f"Kualitas Default: {soundcloud_manager.quality}\n"
        dt_sc += f"Cache User (Global): {len([u for u in bot_set.user_data if 'soundcloud_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_sc += "Tidak ada klien Soundcloud yang aktif (Token hilang)."

    # DEEZER DEBUG
    dt_dz = "\n\nDEEZER:\n"
    if deezer_manager and deezer_manager.clients:
        dt_dz += f"{len(deezer_manager.clients)} klien Deezer aktif.\n"
        dt_dz += f"Kualitas Default: {deezer_manager.quality}\n"
        dt_dz += f"Cache User (Global): {len([u for u in bot_set.user_data if 'deezer_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_dz += "Tidak ada klien Deezer yang aktif."

    # TIDAL DEBUG
    dt_td = "\n\nTIDAL:\n"
    if tidal_manager and tidal_manager.clients:
        dt_td += f"{len(tidal_manager.clients)} klien Tidal aktif.\n"
        dt_td += f"Kualitas Default: {tidal_manager.quality}, Spasial: {tidal_manager.spatial}\n"
        dt_td += f"Global MQA Fix: {tidal_manager.mqa_fix}, Global Convert M4A: {tidal_manager.convert_m4a}\n"
        dt_td += f"Cache User Kualitas: {len([u for u in bot_set.user_data if 'tidal_qual' in bot_set.user_data[u]])} pengguna\n"
        dt_td += f"Cache User MQA: {len([u for u in bot_set.user_data if 'tidal_mqa_fix' in bot_set.user_data[u]])} pengguna\n"
        dt_td += f"Cache User Convert: {len([u for u in bot_set.user_data if 'tidal_convert_m4a' in bot_set.user_data[u]])} pengguna"
    else:
        dt_td += "Tidak ada klien Tidal yang aktif."

    # KKBOX DEBUG
    dt_kk = "\n\nKKBOX:\n"
    if kkbox_manager and kkbox_manager.clients:
        dt_kk += f"{len(kkbox_manager.clients)} klien KKBox aktif.\n"
        dt_kk += f"Kualitas Default: {kkbox_manager.quality}\n"
        dt_kk += f"Cache User (Global): {len([u for u in bot_set.user_data if 'kkbox_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_kk += "Tidak ada klien KKBox yang aktif."

    # NAPSTER DEBUG
    dt_np = "\n\nNAPSTER:\n"
    if napster_manager and napster_manager.clients:
        dt_np += f"{len(napster_manager.clients)} klien Napster aktif.\n"
        dt_np += f"Kualitas Default: {napster_manager.quality}\n"
        dt_np += f"Cache User (Global): {len([u for u in bot_set.user_data if 'napster_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_np += "Tidak ada klien Napster yang aktif."
    
    # IDAGIO DEBUG
    dt_id = "\n\nIDAGIO:\n"
    if idagio_manager and idagio_manager.clients:
        dt_id += f"{len(idagio_manager.clients)} klien Idagio aktif.\n"
        dt_id += f"Kualitas Default: {idagio_manager.quality}\n"
        dt_id += f"Cache User (Global): {len([u for u in bot_set.user_data if 'idagio_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_id += "Tidak ada klien Idagio yang aktif."

    # BUGS DEBUG
    dt_bg = "\n\nBUGS:\n"
    if bugs_manager and bugs_manager.clients:
        dt_bg += f"{len(bugs_manager.clients)} klien Bugs aktif.\n"
        dt_bg += f"Kualitas Default: {bugs_manager.quality}\n"
        dt_bg += f"Cache User (Global): {len([u for u in bot_set.user_data if 'bugs_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_bg += "Tidak ada klien Bugs yang aktif."

    # MOOV DEBUG
    dt_mv = "\n\nMOOV:\n"
    if moov_manager and moov_manager.clients:
        dt_mv += f"{len(moov_manager.clients)} klien Moov aktif.\n"
        dt_mv += f"Kualitas Default: {moov_manager.quality}\n"
        dt_mv += f"Cache User (Global): {len([u for u in bot_set.user_data if 'moov_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_mv += "Tidak ada klien Moov yang aktif."

    # LIVEPHISH DEBUG
    dt_lp = "\n\nLIVEPHISH:\n"
    if livephish_manager and livephish_manager.clients:
        dt_lp += f"{len(livephish_manager.clients)} klien LivePhish aktif.\n"
        dt_lp += f"Kualitas Default: {livephish_manager.quality}\n"
        dt_lp += f"Cache User (Global): {len([u for u in bot_set.user_data if 'livephish_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_lp += "Tidak ada klien LivePhish yang aktif."

    # HIGHRESAUDIO DEBUG
    dt_hra = "\n\nHIGHRESAUDIO:\n"
    if highresaudio_manager and (highresaudio_manager.clients or getattr(highresaudio_manager, 'user_clients', {})):
        dt_hra += f"{len(highresaudio_manager.clients)} klien Global HRA aktif.\n"
        # Cek jumlah private account
        pv_count = len(highresaudio_manager.user_clients) if hasattr(highresaudio_manager, 'user_clients') else 0
        dt_hra += f"Private User Clients: {pv_count}\n"
    else:
        dt_hra += "Tidak ada klien HighResAudio yang aktif."

    # KHINSIDER DEBUG
    dt_khi = "\n\nKHINSIDER:\n"
    if khinsider_manager:
        dt_khi += f"Klien Khinsider aktif.\n"
        dt_khi += f"Kualitas Default: {khinsider_manager.quality}\n"
        dt_khi += f"Cache User (Global): {len([u for u in bot_set.user_data if 'khinsider_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_khi += "Tidak ada klien Khinsider yang aktif."

    # ZIP SETTINGS DEBUG
    zips = f"\n\nAlbum Zip (Global): {bot_set.album_zip}"
    
    # Combine all debug texts
    final_debug_text = dt_qb + dt_bp + dt_bs + dt_sc + dt_dz + dt_td + dt_kk + dt_np + dt_id + dt_bg + dt_mv + dt_lp + dt_hra + dt_khi + zips
    
    # Reply safely
    await m.reply(final_debug_text, True)
