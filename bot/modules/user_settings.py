# [GANTI TOTAL ISI FILE: bot/modules/user_settings.py]

import bot.helpers.translations as lang
import logging, asyncio
from traceback import format_exc

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ButtonStyle

from config import Config
from bot import cmd
from bot import BOT_QOBUZ_CLIENTS 

# --- IMPORT MANAGERS (DENGAN ERROR HANDLING) ---
def safe_import_manager(module_path, manager_name):
    try:
        mod = __import__(module_path, fromlist=[manager_name])
        return getattr(mod, manager_name)
    except ImportError:
        logging.warning(f"UserSettings: Gagal mengimpor {manager_name}.")
        return None

beatport_manager = safe_import_manager("bot.helpers.beatport.manager", "beatport_manager")
deezer_manager = safe_import_manager("bot.helpers.deezer.manager", "deezer_manager")
tidal_manager = safe_import_manager("bot.helpers.tidal.manager", "tidal_manager")
kkbox_manager = safe_import_manager("bot.helpers.kkbox.manager", "kkbox_manager")
soundcloud_manager = safe_import_manager("bot.helpers.soundcloud.manager", "soundcloud_manager")
idagio_manager = safe_import_manager("bot.helpers.idagio.manager", "idagio_manager")
bugs_manager = safe_import_manager("bot.helpers.bugs.manager", "bugs_manager")
moov_manager = safe_import_manager("bot.helpers.moov.manager", "moov_manager")
livephish_manager = safe_import_manager("bot.helpers.livephish.manager", "livephish_manager")
highresaudio_manager = safe_import_manager("bot.helpers.highresaudio.manager", "highresaudio_manager")
khinsider_manager = safe_import_manager("bot.helpers.khinsider.manager", "khinsider_manager")
qobuz_manager = safe_import_manager("bot.helpers.qobuz.qopy", "qobuz_manager")
amazon_manager = safe_import_manager("bot.helpers.amazon.manager", "amazon_manager")
genie_manager = safe_import_manager("bot.helpers.genie.manager", "genie_manager")

# --- IMPORT BUTTONS ---
from ..helpers.buttons.settings import (
    usetting_button, tidal_quality_button,
    qb_button, bp_button, dz_button, kk_button,
    sc_button, id_button, bugs_button, lyrics_button, mv_button,
    lp_button, khi_button, beatport_user_auth_buttons, highresaudio_user_auth_buttons, hra_button, qb_user_auth_buttons, deezer_user_auth_buttons, amz_button, amazon_user_auth_buttons, gn_button
)
from ..helpers.database.mongo_async import database
from ..helpers.utils import fetch_zip_settings
from ..settings import bot_set
from ..helpers.message import send_message, edit_message, check_user, fetch_user_details
from ..helpers.tidal.tidal_api import TidalApi


# ==================================
# 1. DYNAMIC CLOUD TOKEN COMMANDS
# ==================================
async def _save_token(message, key, name):
    user_id = message.from_user.id
    try:
        if len(message.command) < 2: raise IndexError
        token = message.text.split(maxsplit=1)[1].strip()
        bot_set.user_data.setdefault(user_id, {})[key] = token
        await database.save_user_settings(user_id, {key: token})
        await message.reply_text(f"✅ <b>{name} Token Saved!</b>\nToken: <code>{token}</code>")
    except IndexError:
        await message.reply_text(f"❌ <b>Format Salah.</b>\nContoh: <code>/set_{name.lower()} your_token_here</code>")

async def _del_token(message, key, name):
    user_id = message.from_user.id
    if user_id in bot_set.user_data:
        bot_set.user_data[user_id].pop(key, None)
    await database.save_user_settings(user_id, {key: None})
    await message.reply_text(f"🗑️ <b>{name} Token Deleted!</b>")

CLOUD_KEYS = {
    "gofile": ("gofile_token", "Gofile"),
    "buzzheavier": ("buzzheavier_token", "Buzzheavier"),
    "viking": ("viking_token", "Vikingfiles")
}

@Client.on_message(filters.command(["set_gofile", "set_buzzheavier", "set_viking"]))
async def set_cloud_cmd(client, message):
    if not await check_user(msg=message): return
    prov = message.command[0].split('_')[1]
    if prov in CLOUD_KEYS:
        await _save_token(message, CLOUD_KEYS[prov][0], CLOUD_KEYS[prov][1])

@Client.on_message(filters.command(["del_gofile", "delete_gofile", "del_buzzheavier", "delete_buzzheavier", "del_viking", "delete_viking"]))
async def del_cloud_cmd(client, message):
    if not await check_user(msg=message): return
    prov = message.command[0].split('_')[1].replace('ete', '')
    if prov in CLOUD_KEYS:
        await _del_token(message, CLOUD_KEYS[prov][0], CLOUD_KEYS[prov][1])


# ==================================
# 2. PRIVATE AUTH COMMANDS & MENUS
# ==================================
# Note: Karena alur otentikasi (TV Code, Proxy, Email) sangat unik per layanan, 
# kita tetap mempertahankan handler individual untuk Auth Commands agar tidak merusak logika spesifiknya.

# --- BEATPORT AUTH ---
@Client.on_message(filters.command("beatport_login"))
async def uset_bp_login_cmd(client, message):
    if not await check_user(msg=message): return
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 3: return await message.reply_text("❌ **Format Salah**\nGunakan: <code>/beatport_login email password</code>")
    status_msg = await message.reply_text("🔄 **Verifying Account...**\nMencoba login ke Beatport...")
    try:
        await beatport_manager.add_user_account(user_id, args[1], args[2])
        await status_msg.edit_text(f"✅ **Login Berhasil!**\nAkun: <code>{args[1]}</code>\nMode: Private Session")
    except Exception as e: await status_msg.edit_text(f"❌ **Login Gagal:**\n{str(e)}")

@Client.on_callback_query(filters.regex("^uset_bp_auth"))
async def uset_bp_auth_handler(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    has_session = beatport_manager.has_private_session(user_id)
    text = "🔐 **BEATPORT PRIVATE SESSION**\n\n"
    if has_session:
        email_masked = beatport_manager.get_client(user_id).email
        text += f"✅ **Status: LOGGED IN**\n👤 Akun: <code>{email_masked}</code>\nBot menggunakan akun ini khusus untuk Anda."
    else:
        text += "❌ **Status: NOT LOGGED IN**\nBot menggunakan akun Global (Shared) untuk Anda jika tersedia."
    await edit_message(query.message, text, markup=beatport_user_auth_buttons(has_session))

@Client.on_callback_query(filters.regex("^uset_bp_logout"))
async def uset_bp_logout_handler(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    if beatport_manager.has_private_session(user_id):
        await beatport_manager.remove_user_account(user_id)
        await query.answer("✅ Sesi Beatport dihapus.", True)
    else: await query.answer("Anda belum login.", True)
    await uset_bp_auth_handler(client, query)

@Client.on_callback_query(filters.regex("^uset_bp_instr"))
async def uset_bp_instr_handler(client, query):
    if not await check_user(msg=query.message): return
    text = "📝 **CARA LOGIN BEATPORT**\n\n<code>/beatport_login email password</code>"
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="uset_bp_auth", style=ButtonStyle.PRIMARY)]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# --- HIGHRESAUDIO AUTH ---
@Client.on_message(filters.command("highresaudio_login"))
async def uset_hra_login_cmd(client, message):
    if not await check_user(msg=message): return
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 3: return await message.reply_text("❌ **Format Salah**\nGunakan: <code>/highresaudio_login email password</code>")
    status_msg = await message.reply_text("🔄 **Verifying Account...**\nMencoba login ke HighResAudio...")
    try:
        success, info = await highresaudio_manager.add_user_account(user_id, args[1], args[2])
        if success: await status_msg.edit_text(f"✅ **Login Berhasil!**\nAkun: <code>{args[1]}</code>")
        else: await status_msg.edit_text(f"❌ **Login Gagal:**\n{info}")
    except Exception as e: await status_msg.edit_text(f"❌ **Error:**\n{str(e)}")

@Client.on_callback_query(filters.regex("^uset_hra_auth"))
async def uset_hra_auth_handler(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    if not highresaudio_manager: return await query.answer("Modul HighResAudio tidak aktif.", show_alert=True)
    client_obj = highresaudio_manager.get_client(user_id)
    has_session = user_id in highresaudio_manager.user_clients
    text = "🔐 **HIGHRESAUDIO PRIVATE SESSION**\n\n"
    if has_session and client_obj:
        email_masked = getattr(client_obj, 'email', getattr(client_obj, 'username', 'Unknown User'))
        text += f"✅ **Status: LOGGED IN**\n👤 Akun: <code>{email_masked}</code>"
    else:
        text += "❌ **Status: NOT LOGGED IN**\nBot menggunakan akun Global (Shared) untuk Anda jika tersedia."
    await edit_message(query.message, text, markup=highresaudio_user_auth_buttons(has_session))

@Client.on_callback_query(filters.regex("^uset_hra_logout"))
async def uset_hra_logout_handler(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    if user_id in highresaudio_manager.user_clients:
        try: highresaudio_manager.user_clients[user_id].close_session()
        except: pass
        del highresaudio_manager.user_clients[user_id]
        await query.answer("✅ Sesi HighResAudio dihapus.", True)
    else: await query.answer("Anda belum login.", True)
    await uset_hra_auth_handler(client, query)

@Client.on_callback_query(filters.regex("^uset_hra_instr"))
async def uset_hra_instr_handler(client, query):
    if not await check_user(msg=query.message): return
    text = "📝 **CARA LOGIN HIGHRESAUDIO**\n\n<code>/highresaudio_login email password</code>"
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="uset_hra_auth", style=ButtonStyle.PRIMARY)]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# --- QOBUZ AUTH ---
@Client.on_message(filters.command("qobuz_login"))
async def uset_qb_login_cmd(client, message):
    if not await check_user(msg=message): return
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 3: return await message.reply_text("❌ **Format Salah**\nVia Email: <code>/qobuz_login email password</code>\nVia Token: <code>/qobuz_login user_id token</code>")
    app_id = args[3] if len(args) > 3 else None
    app_secret = args[4] if len(args) > 4 else None
    status_msg = await message.reply_text("🔄 **Verifying Qobuz Account...**")
    try:
        if "@" in args[1]: success, info = await qobuz_manager.add_user_account(tg_user_id=user_id, email=args[1], password=args[2], app_id=app_id, app_secret=app_secret)
        else: success, info = await qobuz_manager.add_user_account(tg_user_id=user_id, q_user_id=args[1], q_token=args[2], app_id=app_id, app_secret=app_secret)
        if success: await status_msg.edit_text(f"✅ **{info}**")
        else: await status_msg.edit_text(f"❌ **Login Gagal:**\n{info}")
    except Exception as e: await status_msg.edit_text(f"❌ **Error:**\n{str(e)}")

@Client.on_callback_query(filters.regex("^uset_qb_auth"))
async def uset_qb_auth_handler(client, query):
    if not await check_user(msg=query.message): return
    accounts_list = bot_set.user_data.get(query.from_user.id, {}).get('qobuz_accounts', [])
    text = "🔐 **QOBUZ PRIVATE SESSION**\n\n"
    if accounts_list: text += f"✅ **Status: {len(accounts_list)} Akun Tersimpan**\n"
    else: text += "❌ **Status: TIDAK ADA AKUN**\n"
    await edit_message(query.message, text, markup=qb_user_auth_buttons(accounts_list))

@Client.on_callback_query(filters.regex(r"^uset_qb_rm_(.+)"))
async def uset_qb_remove_handler(client, query):
    if not await check_user(msg=query.message): return
    if await qobuz_manager.remove_specific_account(query.from_user.id, query.matches[0].group(1)):
        await query.answer("✅ Akun dihapus.", True)
    else: await query.answer("❌ Gagal menghapus.", True)
    await uset_qb_auth_handler(client, query)

@Client.on_callback_query(filters.regex("^uset_qb_instr"))
async def uset_qb_instr_handler(client, query):
    if not await check_user(msg=query.message): return
    text = "📝 **CARA LOGIN QOBUZ**\n\n<code>/qobuz_login user_id user_token</code>"
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="uset_qb_auth", style=ButtonStyle.PRIMARY)]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# --- DEEZER AUTH ---
@Client.on_message(filters.command("deezer_login"))
async def uset_dz_login_cmd(client, message):
    if not await check_user(msg=message): return
    if len(message.text.split()) < 2: return await message.reply_text("❌ **Format Salah**\nGunakan: <code>/deezer_login arl_anda</code>")
    status_msg = await message.reply_text("🔄 **Verifying Deezer Account...**")
    try:
        success, info = await deezer_manager.add_user_account(message.from_user.id, message.text.split()[1].strip())
        await status_msg.edit_text(f"✅ **{info}**" if success else f"❌ **Login Gagal:**\n{info}")
    except Exception as e: await status_msg.edit_text(f"❌ **Error:**\n{str(e)}")

@Client.on_callback_query(filters.regex("^uset_dz_auth"))
async def uset_dz_auth_handler(client, query):
    if not await check_user(msg=query.message): return
    accounts_list = bot_set.user_data.get(query.from_user.id, {}).get('deezer_accounts', [])
    text = "🔐 **DEEZER PRIVATE SESSION**\n\n"
    if accounts_list:
        text += f"✅ **Status: {len(accounts_list)} Akun Tersimpan**\n"
        for idx, acc in enumerate(accounts_list): text += f"{idx+1}. <b>{acc.get('label', 'Unknown')}</b>\n"
    else: text += "❌ **Status: TIDAK ADA AKUN**\n"
    await edit_message(query.message, text, markup=deezer_user_auth_buttons(accounts_list))

@Client.on_callback_query(filters.regex(r"^uset_dz_rm_(.+)"))
async def uset_dz_remove_handler(client, query):
    if not await check_user(msg=query.message): return
    if await deezer_manager.remove_specific_account(query.from_user.id, query.matches[0].group(1)):
        await query.answer("✅ Akun dihapus.", True)
    else: await query.answer("❌ Gagal.", True)
    await uset_dz_auth_handler(client, query)

@Client.on_callback_query(filters.regex("^uset_dz_instr"))
async def uset_dz_instr_handler(client, query):
    text = "Ketik: <code>/deezer_login arl_anda_disini</code>"
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="uset_dz_auth", style=ButtonStyle.PRIMARY)]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# --- TIDAL AUTH ---
@Client.on_callback_query(filters.regex("^utd_auth_menu"))
async def uset_tidal_auth_menu(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    user_data_mem = bot_set.user_data.get(user_id, {})
    accounts_list = user_data_mem.get('tidal_accounts', [])
    if not accounts_list and user_data_mem.get('tidal_auth'):
        accounts_list = [user_data_mem['tidal_auth']]
        user_data_mem['tidal_accounts'] = accounts_list
    
    text = "**🔐 TIDAL PRIVATE SESSION (MULTI-ACCOUNT)**\n\n"
    buttons = []
    if accounts_list:
        text += f"✅ **Status: {len(accounts_list)} Akun Tersimpan**\n"
        for i, acc in enumerate(accounts_list):
            text += f"**{i+1}. User ID:** `{acc.get('user_id', 'Unknown')}`\n   🏳️ Region: `{acc.get('country_code', '??')}` | 💎 Plan: `{acc.get('sub_type', 'Premium')}`\n\n"
        buttons.append([InlineKeyboardButton("🔻 HAPUS AKUN (KLIK DI BAWAH) 🔻", callback_data="ignore")])
        for acc in accounts_list:
            uid = acc.get('user_id', 'Unknown')
            buttons.append([InlineKeyboardButton(text=f"🗑️ {acc.get('sub_type', 'Premium')} - {uid}", callback_data=f"utd_rm_{uid}", style=ButtonStyle.DANGER)])
    else:
        text += "❌ **Status: NOT LOGGED IN**\n"
        
    buttons.append([InlineKeyboardButton("➕ LOGIN ACCOUNT (TV CODE)", callback_data="utd_login_start", style=ButtonStyle.SUCCESS)])
    buttons.append([InlineKeyboardButton("➕ LOGIN VIA TOKEN", callback_data="utd_instr_token", style=ButtonStyle.SUCCESS)])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="uset_tidal", style=ButtonStyle.PRIMARY)])
    await edit_message(query.message, text, InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex("^utd_login_start"))
async def uset_tidal_login_start(client, query):
    if not await check_user(msg=query.message): return
    temp_client = TidalApi()
    try:
        auth_url, err = await temp_client.get_tv_login_url()
        if err: return await query.answer(f"Error: {err}", True)
        bot_set.user_data.setdefault(query.from_user.id, {})['temp_tidal_auth'] = temp_client
        text = f"**TIDAL TV LOGIN**\n\n1. Buka link ini: [LOGIN LINK]({auth_url})\n2. Login dan izinkan akses.\n3. Setelah sukses, klik tombol 'CLICK I HAVE LOGGED IN'."
        buttons = [[InlineKeyboardButton("CLICK I HAVE LOGGED IN", callback_data="utd_login_verify", style=ButtonStyle.SUCCESS)],
                   [InlineKeyboardButton("🔙 Back", callback_data="utd_auth_menu", style=ButtonStyle.PRIMARY)]]
        await edit_message(query.message, text, InlineKeyboardMarkup(buttons))
    except Exception as e: await query.answer(f"Error: {e}", True)

@Client.on_callback_query(filters.regex("^utd_login_verify"))
async def uset_tidal_login_verify(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    temp_client = bot_set.user_data.get(user_id, {}).get('temp_tidal_auth')
    if not temp_client: return await query.answer("Sesi kadaluarsa. Ulangi login.", True)
    await edit_message(query.message, "🔄 **Verifying...**")
    try:
        sub, err = await temp_client.login_tv()
        if err:
            await temp_client.close()
            return await edit_message(query.message, f"❌ **Login Gagal:** {err}", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="utd_auth_menu")]]))
        
        auth_data = {'refresh_token': temp_client.tv_session.refresh_token, 'country_code': temp_client.tv_session.country_code, 'user_id': temp_client.tv_session.user_id, 'sub_type': sub}
        user_data_mem = bot_set.user_data.setdefault(user_id, {})
        accounts_list = user_data_mem.get('tidal_accounts', [])
        if not accounts_list and user_data_mem.get('tidal_auth'): accounts_list = [user_data_mem['tidal_auth']]
        
        if not any(str(acc.get('user_id')) == str(auth_data['user_id']) for acc in accounts_list):
            accounts_list.append(auth_data)
            user_data_mem['tidal_accounts'] = accounts_list
            user_data_mem['tidal_auth'] = None
            await database.save_user_settings(user_id, {'tidal_accounts': accounts_list, 'tidal_auth': None})
            try: await tidal_manager.add_user_account(user_id, auth_data)
            except: pass
            await query.answer("✅ Login Berhasil!", True)
        else: await query.answer("⚠️ Akun sudah ada.", True)
        
        await temp_client.close()
        bot_set.user_data[user_id].pop('temp_tidal_auth', None)
        await uset_tidal_auth_menu(client, query)
    except Exception as e:
        if temp_client: await temp_client.close()
        await edit_message(query.message, f"Error Fatal: {e}")

@Client.on_callback_query(filters.regex(r"^utd_rm_(.+)"))
async def uset_tidal_remove_specific(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    target_uid = query.matches[0].group(1)
    user_data_mem = bot_set.user_data.get(user_id, {})
    accounts_list = user_data_mem.get('tidal_accounts', [])
    if not accounts_list and user_data_mem.get('tidal_auth'): accounts_list = [user_data_mem['tidal_auth']]
    new_list = [acc for acc in accounts_list if str(acc.get('user_id')) != str(target_uid)]
    user_data_mem['tidal_accounts'] = new_list
    user_data_mem['tidal_auth'] = None
    await database.save_user_settings(user_id, {'tidal_accounts': new_list, 'tidal_auth': None})
    try:
        if hasattr(tidal_manager, 'remove_specific_user_account'): await tidal_manager.remove_specific_user_account(user_id, target_uid)
    except: pass
    await query.answer(f"✅ Akun dihapus.", True)
    await uset_tidal_auth_menu(client, query)

@Client.on_message(filters.command("tidal_login"))
async def uset_td_login_cmd(client, message):
    if not await check_user(msg=message): return
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 3: return await message.reply_text("❌ **Format Salah**\n<code>/tidal_login user_id refresh_token [country_code]</code>")
    t_cc = args[3].upper() if len(args) > 3 else "US"
    status_msg = await message.reply_text("🔄 **Verifying Tidal Account...**")
    auth_data = {'refresh_token': args[2].strip(), 'country_code': t_cc, 'user_id': args[1].strip()}
    try:
        user_data_mem = bot_set.user_data.setdefault(user_id, {})
        accounts_list = user_data_mem.get('tidal_accounts', [])
        if not accounts_list and user_data_mem.get('tidal_auth'): accounts_list = [user_data_mem['tidal_auth']]
        if any(str(acc.get('user_id')) == str(auth_data['user_id']) for acc in accounts_list): return await status_msg.edit_text("⚠️ Akun ini sudah ada.")
        success, info = await tidal_manager.add_user_account(user_id, auth_data)
        if success:
            accounts_list.append(auth_data)
            user_data_mem['tidal_accounts'] = accounts_list
            user_data_mem['tidal_auth'] = None
            await database.save_user_settings(user_id, {'tidal_accounts': accounts_list, 'tidal_auth': None})
            await status_msg.edit_text(f"✅ **Login Berhasil!**\nAkun ID <code>{auth_data['user_id']}</code> ({t_cc}) ditambahkan.")
        else: await status_msg.edit_text(f"❌ **Login Gagal:**\n{info}")
    except Exception as e: await status_msg.edit_text(f"❌ **Error:**\n{str(e)}")

@Client.on_callback_query(filters.regex("^utd_instr_token"))
async def uset_tidal_instr_token(client, query):
    text = "📝 **CARA LOGIN TIDAL (TOKEN)**\n\n<code>/tidal_login user_id refresh_token [country_code]</code>"
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="utd_auth_menu", style=ButtonStyle.PRIMARY)]]
    await edit_message(query.message, text, InlineKeyboardMarkup(buttons))


# --- AMAZON AUTH ---
PENDING_AMAZON_AUTH = {}
@Client.on_message(filters.command("amazon_login"))
async def uset_amz_login_cmd(client, message):
    if not await check_user(msg=message): return
    await message.reply_text("🔐 **AMAZON MUSIC TV LOGIN**\n\nGunakan perintah ini:\n<code>/amazon_auth jp</code> (atau region lain)")

@Client.on_message(filters.command("amazon_auth"))
async def amz_tv_auth_cmd(client, message):
    user_id = message.from_user.id
    if len(PENDING_AMAZON_AUTH) >= 5 and user_id not in PENDING_AMAZON_AUTH:
        return await message.reply_text("❌ **Antrean Penuh!** Silakan coba nanti.")
    region = message.text.split()[1].lower() if len(message.text.split()) > 1 else "us"
    valid_regions = ["us", "jp", "uk", "de", "fr", "mx", "br", "au", "nz", "ca", "it", "es", "ar", "in"]
    if region not in valid_regions: return await message.reply_text(f"❌ Region tidak valid.")
    msg = await message.reply_text("🔄 **Meminta kode TV dari Amazon...**")
    from bot.helpers.amazon.amazon_api import AmazonApi
    amz_api = AmazonApi(region=region)
    try:
        public_code, register_code, activation_url = await amz_api.get_tv_device_code()
        PENDING_AMAZON_AUTH[user_id] = {"api": amz_api, "register_code": register_code, "region": region}
        text = f"🔐 **AMAZON MUSIC TV LOGIN ({region.upper()})**\n\n1️⃣ Buka tautan: {activation_url}\n2️⃣ Masukkan kode ini: <code>{public_code}</code>\n3️⃣ Tekan **Allow / Izinkan**\n4️⃣ Klik tombol di bawah jika selesai."
        buttons = [[InlineKeyboardButton("✅ Saya Sudah Login", callback_data="amz_auth_verify")]]
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await amz_api.close()
        await msg.edit_text(f"❌ **Gagal:**\n`{str(e)[:400]}`")

@Client.on_callback_query(filters.regex("^amz_auth_verify"))
async def amz_auth_verify_cb(client, query):
    user_id = query.from_user.id
    if user_id not in PENDING_AMAZON_AUTH: return await query.answer("Sesi kadaluarsa.", True)
    await query.answer("Memverifikasi...", show_alert=False)
    auth_data = PENDING_AMAZON_AUTH[user_id]
    amz_api = auth_data["api"]
    try:
        tokens = await amz_api.poll_tv_auth(auth_data["register_code"])
        if not tokens: return await query.message.reply_text("❌ **Verifikasi gagal.** Anda belum menekan Allow.")
        await amz_api.close()
        
        user_data_mem = bot_set.user_data.setdefault(user_id, {})
        accounts_list = user_data_mem.get('amazon_accounts', [])
        if not accounts_list and user_data_mem.get('amazon_account'): accounts_list = [user_data_mem['amazon_account']]
        
        if not any(acc.get('tokens', {}).get('customerId') == tokens.get('customerId') for acc in accounts_list):
            acc_data = {"region": auth_data["region"], "tokens": tokens}
            accounts_list.append(acc_data)
            user_data_mem['amazon_accounts'] = accounts_list
            user_data_mem['amazon_account'] = None
            await database.save_user_settings(user_id, {'amazon_accounts': accounts_list, 'amazon_account': None})
            if amazon_manager and hasattr(amazon_manager, 'add_user_account'): await amazon_manager.add_user_account(user_id, acc_data)
            await query.message.edit_text("✅ **Login Berhasil!**\nSesi ditambahkan.")
        else: await query.message.edit_text("⚠️ **Akun ini sudah ada**.")
        del PENDING_AMAZON_AUTH[user_id]
    except Exception as e:
        if 'amz_api' in locals() and not amz_api.session.closed: await amz_api.close()
        if user_id in PENDING_AMAZON_AUTH: del PENDING_AMAZON_AUTH[user_id]
        await query.message.reply_text(f"❌ **Error:** {str(e)[:400]}")

@Client.on_callback_query(filters.regex("^uamz_auth"))
async def uset_amz_auth_handler(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    user_data_mem = bot_set.user_data.get(user_id, {})
    accounts_list = user_data_mem.get('amazon_accounts', [])
    if not accounts_list and user_data_mem.get('amazon_account'):
        accounts_list = [user_data_mem['amazon_account']]
        user_data_mem['amazon_accounts'] = accounts_list
    text = "🔐 **AMAZON MUSIC PRIVATE SESSION**\n\n"
    if accounts_list:
        text += f"✅ **Status: {len(accounts_list)} Akun Tersimpan**\n"
        for i, acc in enumerate(accounts_list): text += f"**{i+1}. Region:** `{acc.get('region', '??').upper()}` | **ID:** `{acc.get('tokens', {}).get('customerId', 'Unknown')}`\n"
    else: text += "❌ **Status: NOT LOGGED IN**\n"
    await edit_message(query.message, text, markup=amazon_user_auth_buttons(accounts_list))

@Client.on_callback_query(filters.regex(r"^uamz_rm_(.+)"))
async def uset_amz_remove_specific(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    user_data_mem = bot_set.user_data.get(user_id, {})
    accounts_list = user_data_mem.get('amazon_accounts', [])
    if not accounts_list and user_data_mem.get('amazon_account'): accounts_list = [user_data_mem['amazon_account']]
    new_list = [acc for acc in accounts_list if acc.get('tokens', {}).get('customerId') != query.matches[0].group(1)]
    user_data_mem['amazon_accounts'] = new_list
    user_data_mem['amazon_account'] = None
    await database.save_user_settings(user_id, {'amazon_accounts': new_list, 'amazon_account': None})
    try:
        if hasattr(amazon_manager, 'remove_specific_user_account'): await amazon_manager.remove_specific_user_account(user_id, query.matches[0].group(1))
    except: pass
    await query.answer(f"✅ Akun dihapus.", True)
    await uset_amz_auth_handler(client, query)

@Client.on_callback_query(filters.regex("^uamz_instr"))
async def uset_amz_instr_handler(client, query):
    text = "📝 **CARA LOGIN AMAZON MUSIC**\n\n<code>/amazon_auth jp</code> (atau region lain)"
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="uamz_auth", style=ButtonStyle.PRIMARY)]]
    await edit_message(query.message, text, markup=InlineKeyboardMarkup(buttons))


# --- KKBOX AUTH ---
@Client.on_message(filters.command("kkbox_login"))
async def uset_kkb_login_cmd(client, message):
    if not await check_user(msg=message): return
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 3: return await message.reply_text("❌ **Format Salah**\n<code>/kkbox_login email password [proxy]</code>")
    status_msg = await message.reply_text("🔄 **Verifying KKBox Account...**")
    auth_data = {'email': args[1].strip(), 'password': args[2].strip(), 'proxy': args[3].strip() if len(args) > 3 else None}
    try:
        user_data_mem = bot_set.user_data.setdefault(user_id, {})
        accounts_list = user_data_mem.get('kkbox_accounts', [])
        if any(acc.get('email') == auth_data['email'] for acc in accounts_list): return await status_msg.edit_text("⚠️ Akun ini sudah ada.")
        success, info = await kkbox_manager.add_user_account(user_id, auth_data)
        if success:
            accounts_list.append(auth_data)
            user_data_mem['kkbox_accounts'] = accounts_list
            await database.save_user_settings(user_id, {'kkbox_accounts': accounts_list})
            await status_msg.edit_text(f"✅ **Login Berhasil!**\nAkun <code>{auth_data['email']}</code> ditambahkan.")
        else: await status_msg.edit_text(f"❌ **Login Gagal:**\n{info}")
    except Exception as e: await status_msg.edit_text(f"❌ **Error:**\n{str(e)}")

@Client.on_callback_query(filters.regex("^ukk_auth_menu"))
async def uset_kkb_auth_handler(client, query):
    if not await check_user(msg=query.message): return
    accounts_list = bot_set.user_data.get(query.from_user.id, {}).get('kkbox_accounts', [])
    text = "🔐 **KKBOX PRIVATE SESSION**\n\n"
    if accounts_list:
        text += f"✅ **Status: {len(accounts_list)} Akun Tersimpan**\n"
        for i, acc in enumerate(accounts_list): text += f"**{i+1}. Email:** `{acc['email']}` | Proxy: {'Aktif' if acc.get('proxy') else 'Tidak'}\n"
    else: text += "❌ **Status: NOT LOGGED IN**\n"
    from bot.helpers.buttons.settings import kkbox_user_auth_buttons
    await edit_message(query.message, text, markup=kkbox_user_auth_buttons(accounts_list))

@Client.on_callback_query(filters.regex(r"^ukk_rm_(.+)"))
async def uset_kkb_remove_specific(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    accounts_list = bot_set.user_data.get(user_id, {}).get('kkbox_accounts', [])
    new_list = [acc for acc in accounts_list if acc.get('email') != query.matches[0].group(1)]
    bot_set.user_data[user_id]['kkbox_accounts'] = new_list
    await database.save_user_settings(user_id, {'kkbox_accounts': new_list})
    await kkbox_manager.remove_specific_user_account(user_id, query.matches[0].group(1))
    await query.answer(f"✅ Akun dihapus.", True)
    await uset_kkb_auth_handler(client, query)

@Client.on_callback_query(filters.regex("^ukk_instr"))
async def uset_kkb_instr_handler(client, query):
    text = "📝 **CARA LOGIN KKBOX**\n\n<code>/kkbox_login email password [proxy]</code>"
    buttons = [[InlineKeyboardButton("🔙 Back", callback_data="ukk_auth_menu", style=ButtonStyle.PRIMARY)]]
    await edit_message(query.message, text, InlineKeyboardMarkup(buttons))


# ==================================
# 3. SETTING MAIN ROUTERS & UI MENUS
# ==================================

# Konfigurasi Utama Pengaturan Per-Provider (DRY Architecture)
MENU_CFG = {
    "qobuz": {"mgr": qobuz_manager, "btn": qb_button, "db_key": "qobuz_qual", "qual_dict": {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ', 27:'24B>96KHZ'}, "default": 6},
    "beatport": {"mgr": beatport_manager, "btn": bp_button, "db_key": "beatport_qual", "qual_dict": {"lossless": "Lossless (FLAC)", "high": "High (AAC 256)", "medium": "Medium (AAC 128)"}},
    "soundcloud": {"mgr": soundcloud_manager, "btn": sc_button, "db_key": "soundcloud_qual", "qual_dict": {"original": "Original (Jika Ada)", "stream": "Stream (Default AAC/MP3)"}},
    "deezer": {"mgr": deezer_manager, "btn": dz_button, "db_key": "deezer_qual", "qual_dict": {"FLAC": "FLAC", "MP3_320": "MP3 320", "MP3_128": "MP3 128"}},
    "kkbox": {"mgr": kkbox_manager, "btn": kk_button, "db_key": "kkbox_qual", "qual_dict": {"128k": "MP3 128k", "192k": "MP3 192k", "320k": "AAC 320k", "hifi": "FLAC 16-bit", "hires": "FLAC 24-bit"}},
    "idagio": {"mgr": idagio_manager, "btn": id_button, "db_key": "idagio_qual", "qual_dict": {"FLAC": "FLAC", "MP3_320": "AAC 320k", "MP3_160": "AAC 160k"}},
    "bugs": {"mgr": bugs_manager, "btn": bugs_button, "db_key": "bugs_qual", "qual_dict": {"flac": "FLAC 16-bit", "aac256": "AAC 320k", "320k": "MP3 320k", "aac": "AAC 128k"}},
    "moov": {"mgr": moov_manager, "btn": mv_button, "db_key": "moov_qual", "qual_dict": {"FLAC": "Max (24bit/HR)", "MP3_320": "Std (16bit/LL)"}},
    "livephish": {"mgr": livephish_manager, "btn": lp_button, "db_key": "livephish_qual", "qual_dict": {"FLAC": "FLAC (16-bit)", "ALAC": "ALAC (16-bit)", "AAC": "AAC"}},
    "khinsider": {"mgr": khinsider_manager, "btn": khi_button, "db_key": "khinsider_qual", "qual_dict": {"flac": "FLAC", "mp3": "MP3"}},
    "amazon": {"mgr": amazon_manager, "btn": amz_button, "db_key": "amazon_qual", "qual_dict": {"AC-4": "AC-4 (Dolby Atmos)", "EC-3": "EC-3 (Dolby Digital Plus)", "MHA1": "MPEG-H 3D (mha1)", "MHM1": "MPEG-H 3D (mhm1)", "UHD": "UHD (Hi-Res)", "HD": "HD (Lossless)", "SD": "SD (Opus - High)", "LD": "LD (Opus - Med/Low)"}, "default": "HD"},
    "genie": {"mgr": genie_manager, "btn": gn_button, "db_key": "genie_qual", "qual_dict": {"flac24": "FLAC 24-bit", "flac16": "FLAC 16-bit", "mp3": "MP3 320kbps", "mp3192": "MP3 192kbps"}, "default": "flac24"}
}

@Client.on_message(filters.command(cmd.USETTING))
async def start_user_setting(client: Client, m: Message, edit=False, users_: dict=None):
    if not await check_user(msg=m): return
    
    user_id = users_.get('user_id') if users_ else (await fetch_user_details(m))['user_id']
    if user_id not in bot_set.user_data: bot_set.user_data.setdefault(user_id, {})
    curr = bot_set.user_data.get(user_id, {})
    
    # Priority Fetching ZIP
    def _fetch_zip(k):
        return curr.get(k.upper(), curr.get(k.lower(), False))

    upload_mode = curr.get('upload_mode', 'Telegram')
    t_gf = "✅" if curr.get('gofile_token') else "❌"
    t_bh = "✅" if curr.get('buzzheavier_token') else "❌"
    t_vk = "✅" if curr.get('viking_token') else "❌"

    text = f"""
<blockquote>
<b>📦 ZIP SETTINGS</b>
PLAYLIST : {_fetch_zip('PLAYLIST_ZIP')} | ALBUM : {_fetch_zip('ALBUM_ZIP')}
ARTIST : {_fetch_zip('ARTIST_ZIP')} | POSTER : {_fetch_zip('ART_POSTER')}
VIDEO : {_fetch_zip('VIDEO_ZIP')}

<b>☁️ UPLOAD MODE: {upload_mode}</b>
Gofile: {t_gf} | Buzz: {t_bh} | Viking: {t_vk}
</blockquote>
{m.date.now().strftime("%d/%m/%Y %H:%M:%S")}
Choose Menu option below:
"""
    if not edit: await send_message(m, text, markup=usetting_button(user_id))
    else: await edit_message(m, text, markup=usetting_button(user_id))

@Client.on_callback_query(filters.regex("^uset_upload_mode"))
async def uset_upload_mode_handler(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    modes = ['Telegram', 'Gofile', 'Buzzheavier', 'Vikingfiles']
    curr = bot_set.user_data.get(user_id, {}).get('upload_mode', 'Telegram')
    next_idx = (modes.index(curr) + 1) % len(modes) if curr in modes else 0
    bot_set.user_data.setdefault(user_id, {})['upload_mode'] = modes[next_idx]
    await database.save_user_settings(user_id, {'upload_mode': modes[next_idx]})
    await start_user_setting(client, query.message, True, {"user_id": user_id})

@Client.on_callback_query(filters.regex("^uset_(tidal|back|qobuz|close|beatport|deezer|kkbox|beatsource|soundcloud|napster|idagio|bugs|moov|livephish|highresaudio|khinsider|amazon|genie)"))
async def uset_cb(client, query, datatype=""):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    action = query.data.split("_")[1] if not datatype else datatype

    if action == "back": return await start_user_setting(client, query.message, True, {"user_id": user_id})
    if action == "close": return await query.message.delete()
    
    if action == "highresaudio":
        if not highresaudio_manager: return await edit_message(query.message, "Layanan HighResAudio tidak aktif.")
        return await edit_message(query.message, "HighResAudio Settings:", markup=hra_button(user_id))
        
    elif action == "tidal":
        if not tidal_manager: return await edit_message(query.message, "Layanan Tidal tidak aktif.")
        qualities = {'LOW':'LOW', 'HIGH':'HIGH', 'LOSSLESS':'LOSSLESS'}
        main_user_dict = bot_set.user_data.get(user_id, {})
        await tidal_manager.setup_user_settings(user_id, qual=main_user_dict.get("tidal_qual"), spatial=main_user_dict.get("tidal_spatial"), mqa_fix=main_user_dict.get("tidal_mqa_fix"), convert_m4a=main_user_dict.get("tidal_convert_m4a"))
        user_qual, user_spatial, _, __ = tidal_manager.get_user_quality_settings(user_id)
        
        has_hires = False
        if tidal_manager.clients and any(c.mobile_hires for c in tidal_manager.clients): has_hires = True
        user_client = await tidal_manager.get_user_client(user_id)
        if user_client and getattr(user_client, 'mobile_hires', False): has_hires = True

        if has_hires or user_qual == 'HI_RES': qualities['HI_RES'] = 'MAX'
        if user_qual in qualities: qualities[user_qual] += '✅'
        else: qualities.get('LOSSLESS', '') and qualities.update({'LOSSLESS': qualities['LOSSLESS'] + '✅'})
            
        return await edit_message(query.message, "Choose Tidal Audio Quality bellow:", tidal_quality_button(qualities, user_id, spatial=user_spatial))

    elif action in MENU_CFG:
        cfg = MENU_CFG[action]
        mgr = cfg['mgr']
        has_client = False
        
        if action == "qobuz":
            if BOT_QOBUZ_CLIENTS or (mgr and mgr.has_private_session(user_id)): has_client = True
        elif action == "amazon":
            if mgr and (getattr(mgr, 'global_clients', []) or getattr(mgr, 'clients', []) or mgr.has_private_session(user_id)): has_client = True
        elif action == "kkbox":
            if mgr and (getattr(mgr, 'clients', []) or bot_set.user_data.get(user_id, {}).get('kkbox_accounts')): has_client = True
        else:
            if mgr and (getattr(mgr, 'clients', []) or getattr(mgr, 'global_clients', []) or (hasattr(mgr, 'has_private_session') and mgr.has_private_session(user_id))): has_client = True

        if not has_client: return await edit_message(query.message, f"Layanan {action.title()} tidak aktif (tidak ada klien yang login).")

        current = bot_set.user_data.get(user_id, {}).get(cfg['db_key'], getattr(mgr, 'quality', cfg.get('default', '')))
        if hasattr(mgr, 'setup_quality'): await mgr.setup_quality(user_id, current)
        if action == "qobuz":
            try: current = int(current)
            except: pass
            
        q_dict = cfg['qual_dict'].copy()
        if current in q_dict: q_dict[current] += '✅'
        
        text = f"Choose {action.title()} Audio Quality bellow:"
        if action == "bugs": text += "\n(Kualitas FLAC tergantung langganan akun bot)"
        elif action == "moov": text += "\n(Moov menyediakan FLAC 16bit & 24bit)"
        elif action == "amazon": text += "\n(Tergantung pada tier langganan akun)"
        
        # [PERBAIKAN]: Pass nama argumen untuk custom button jika ada, 
        # Beberapa button cuma butuh (q_dict, user_id), beberapa butuh (q_dict) lalu dibalut.
        # Format umum di button yang kita gunakan sekarang aman dengan 2 argument ini.
        return await edit_message(query.message, text, markup=cfg['btn'](q_dict, user_id))


# ==================================
# 4. UNIFIED QUALITY SETTERS ROUTER
# ==================================
QUAL_ROUTES = {
    "uqbs": {"prov": "qobuz", "db_key": "qobuz_qual", "mgr": qobuz_manager, "is_int": True},
    "ubps": {"prov": "beatport", "db_key": "beatport_qual", "mgr": beatport_manager, "map": {"Lossless (FLAC)": "lossless", "High (AAC 256)": "high", "Medium (AAC 128)": "medium"}},
    "uscs": {"prov": "soundcloud", "db_key": "soundcloud_qual", "mgr": soundcloud_manager, "map": {"Original (Jika Ada)": "original", "Stream (Default AAC/MP3)": "stream"}},
    "udzs": {"prov": "deezer", "db_key": "deezer_qual", "mgr": deezer_manager, "map": {"FLAC": "FLAC", "MP3 320": "MP3_320", "MP3 128": "MP3_128"}},
    "ukks": {"prov": "kkbox", "db_key": "kkbox_qual", "mgr": kkbox_manager, "map": {"MP3 128k": "128k", "MP3 192k": "192k", "AAC 320k": "320k", "FLAC 16-bit": "hifi", "FLAC 24-bit": "hires"}},
    "uids": {"prov": "idagio", "db_key": "idagio_qual", "mgr": idagio_manager, "map": {"FLAC": "FLAC", "AAC 320k": "MP3_320", "AAC 160k": "MP3_160"}},
    "ubgs": {"prov": "bugs", "db_key": "bugs_qual", "mgr": bugs_manager, "map": {"FLAC 16-bit": "flac", "AAC 320k": "aac256", "MP3 320k": "320k", "AAC 128k": "aac"}},
    "umvs": {"prov": "moov", "db_key": "moov_qual", "mgr": moov_manager},
    "ulps": {"prov": "livephish", "db_key": "livephish_qual", "mgr": livephish_manager},
    "ukhis": {"prov": "khinsider", "db_key": "khinsider_qual", "mgr": khinsider_manager},
    "uamzs": {"prov": "amazon", "db_key": "amazon_qual", "mgr": amazon_manager},
    "ugns": {"prov": "genie", "db_key": "genie_qual", "mgr": genie_manager},
}

@Client.on_callback_query(filters.regex(r"^(uqbs|ubps|uscs|udzs|ukks|uids|ubgs|umvs|ulps|ukhis|uamzs|ugns)(_|$)"))
async def unified_quality_setter(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    prefix = query.data.split('_')[0]
    
    if prefix not in QUAL_ROUTES: return await query.answer("Invalid Setting.", True)
    
    c = QUAL_ROUTES[prefix]
    to_set = query.data[len(prefix)+1:]
    
    if 'map' in c:
        to_set = c['map'].get(to_set)
        if not to_set: return await query.answer("Kualitas tidak valid.", True)
    if c.get('is_int'):
        try: to_set = int(to_set)
        except: pass
        
    if hasattr(c['mgr'], 'setup_quality'):
        await c['mgr'].setup_quality(user_id, to_set)
    elif c['prov'] == "qobuz" and BOT_QOBUZ_CLIENTS:
        for qc in BOT_QOBUZ_CLIENTS.values(): await qc.setup_quality(int(user_id), to_set)

    bot_set.user_data.setdefault(user_id, {})[c['db_key']] = to_set
    await database.save_user_settings(user_id, {c['db_key']: to_set})
    await uset_cb(client, query, c['prov'])


# --- SETTING TIDAL KUALITAS SPECIFIC (Tidal Punya Parameter Kompleks) ---
@Client.on_callback_query(filters.regex("^utdqs"))
async def uset_tidal_setter(client, query):
    if not await check_user(msg=query.message): return
    if not tidal_manager: return await query.answer("Layanan Tidal tidak aktif!", show_alert=True)
    
    user_id = query.from_user.id
    data = query.data 
    
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
        has_atmos, has_360 = False, False
        
        if tidal_manager.clients:
            if any(c.mobile_atmos for c in tidal_manager.clients): has_atmos = True
            if any(c.mobile_atmos or c.mobile_hires for c in tidal_manager.clients): has_360 = True
        if user_client:
            if getattr(user_client, 'mobile_atmos', False): has_atmos = True
            if getattr(user_client, 'mobile_atmos', False) or getattr(user_client, 'mobile_hires', False): has_360 = True

        options = ['OFF', 'ATMOS AC3 JOC']
        if has_atmos: options.append('ATMOS AC4')
        if has_360: options.append('Sony 360RA')
            
        current = options.index(bot_set.user_data.get(user_id, {}).get("tidal_spatial", tidal_manager.spatial)) if bot_set.user_data.get(user_id, {}).get("tidal_spatial", tidal_manager.spatial) in options else 0
        new_spatial = options[(current + 1) % len(options)]
        
        bot_set.user_data.setdefault(user_id, {})["tidal_spatial"] = new_spatial
        await database.save_user_settings(user_id, {"tidal_spatial": new_spatial})
        await tidal_manager.setup_user_settings(user_id, spatial=new_spatial)
    else:
        to_set = data.split('_')[1]
        qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
        to_set_qual = next((k for k, v in qualities.items() if v == to_set), "LOSSLESS")

        bot_set.user_data.setdefault(user_id, {})["tidal_qual"] = to_set_qual
        await database.save_user_settings(user_id, {"tidal_qual": to_set_qual})
        await tidal_manager.setup_user_settings(user_id, qual=to_set_qual)
    
    await uset_cb(client, query, "tidal")


# ==================================
# 5. UNIFIED COVER SOURCE ROUTER
# ==================================
@Client.on_callback_query(filters.regex("^(udzc|uqbc|utdc)_"))
async def unified_cover_source(client, query):
    if not await check_user(msg=query.message): return
    
    prefix = query.data.split('_')[0]
    selected = query.data.split('_')[1]
    user_id = query.from_user.id
    
    cfg = {
        "udzc": {"prov": "deezer", "db_key": "deezer_cover_source"},
        "uqbc": {"prov": "qobuz", "db_key": "qobuz_cover_source"},
        "utdc": {"prov": "tidal", "db_key": "tidal_cover_source"}
    }
    
    bot_set.user_data.setdefault(user_id, {})[cfg[prefix]['db_key']] = selected
    await database.save_user_settings(user_id, {cfg[prefix]['db_key']: selected})
    await uset_cb(client, query, cfg[prefix]['prov'])


# ==================================
# 6. LYRICS & ZIP SETTINGS ROUTER
# ==================================
@Client.on_callback_query(filters.regex("^uset_ly|^uset_sendly"))
async def uset_lyrics_handler(client, query):
    if not await check_user(msg=query.message): return
    user_id = query.from_user.id
    data = query.data
    bot_set.user_data.setdefault(user_id, {})

    if data == "uset_ly_on": await database.save_user_settings(user_id, {'lyrics_status': True}); bot_set.user_data[user_id]['lyrics_status'] = True
    elif data == "uset_ly_off": await database.save_user_settings(user_id, {'lyrics_status': False}); bot_set.user_data[user_id]['lyrics_status'] = False
    elif data == "uset_sendly_on": await database.save_user_settings(user_id, {'send_lyrics_file': True}); bot_set.user_data[user_id]['send_lyrics_file'] = True
    elif data == "uset_sendly_off": await database.save_user_settings(user_id, {'send_lyrics_file': False}); bot_set.user_data[user_id]['send_lyrics_file'] = False
    elif data.startswith("uset_ly_p_"): 
        prov = data.split("_")[-1]
        bot_set.user_data[user_id]['lyrics_provider'] = prov
        await database.save_user_settings(user_id, {'lyrics_provider': prov})
    elif data.startswith("uset_ly_t_"): 
        typ = data.split("_")[-1]
        bot_set.user_data[user_id]['lyrics_type'] = typ
        await database.save_user_settings(user_id, {'lyrics_type': typ})

    await edit_message(query.message, "<b>Lyrics Settings</b>\n\nConfigure how you want to download lyrics.", markup=lyrics_button(bot_set.user_data[user_id], user_id))

@Client.on_callback_query(filters.regex("^zip"))
async def uset_zip(self, query):
    if not await check_user(msg=query.message): return
    data = query.data.split("_")[1].lower()
    user_id = query.from_user.id
    
    bot_set.user_data.setdefault(user_id, {})
    curr = bot_set.user_data[user_id]
    
    if data == "video":
        new_val = not curr.get("VIDEO_ZIP", curr.get("video_zip", False))
        if isinstance(new_val, str): new_val = new_val.lower() in ['true', '1', 'on']
        curr.update({"VIDEO_ZIP": new_val})
        curr.pop("video_zip", None)
        await database.save_user_settings(user_id, {"VIDEO_ZIP": new_val, "video_zip": None})
    else:
        key = f"{data.upper()}_ZIP" if data != "poster" else "ART_POSTER"
        new_val = not curr.get(key, curr.get(f"{data}_zip" if data != "poster" else "art_poster", False))
        curr[key] = new_val
        await database.save_user_settings(user_id, {key: new_val})

    await query.answer(f"{data.capitalize()} setting: {new_val}")
    await start_user_setting(self, query.message, True, {"user_id": user_id})


# ==================================
# 7. DEBUG COMMAND
# ==================================
@Client.on_message(filters.command("debug") & filters.user(list(Config.ADMINS)))
async def debug(c, m): 
    # QOBUZ DEBUG
    dt_qb = "QOBUZ:\n"
    if BOT_QOBUZ_CLIENTS:
        first_client = BOT_QOBUZ_CLIENTS.get(1) or list(BOT_QOBUZ_CLIENTS.values())[0]
        dt_qb += f"{len(BOT_QOBUZ_CLIENTS)} klien Qobuz aktif.\nLabel Klien #1: {first_client.label}\nKualitas Default: {first_client.quality}"
    else: dt_qb += "Tidak ada klien Qobuz yang aktif."

    # OTHER MANAGERS
    mgrs = [
        ("BEATPORT", beatport_manager), ("SOUNDCLOUD", soundcloud_manager), ("DEEZER", deezer_manager),
        ("TIDAL", tidal_manager), ("KKBOX", kkbox_manager), ("IDAGIO", idagio_manager),
        ("BUGS", bugs_manager), ("MOOV", moov_manager), ("LIVEPHISH", livephish_manager),
        ("HIGHRESAUDIO", highresaudio_manager), ("KHINSIDER", khinsider_manager),
        ("AMAZON MUSIC", amazon_manager), ("GENIE", genie_manager)
    ]
    
    debug_text = dt_qb
    for name, mgr in mgrs:
        debug_text += f"\n\n{name}:\n"
        if mgr:
            gl = len(getattr(mgr, 'global_clients', getattr(mgr, 'clients', []))) if name != "SOUNDCLOUD" else (1 if mgr.get_client() else 0)
            pv = len(getattr(mgr, 'user_clients', {}))
            debug_text += f"Global: {gl} | Private: {pv}\n"
            if hasattr(mgr, 'quality'): debug_text += f"Default Qual: {mgr.quality}\n"
        else:
            debug_text += f"{name} tidak aktif/gagal diload."
            
    debug_text += f"\n\nAlbum Zip (Global): {bot_set.album_zip}"
    await m.reply(debug_text, True)
