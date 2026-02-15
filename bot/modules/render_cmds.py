from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ForceReply
from config import Config
from bot.helpers.render_api import (
    get_services, get_service, trigger_deploy, get_last_deploy, 
    suspend_service, resume_service, get_env_vars, update_env_var, 
    delete_env_var, delete_service
)
import asyncio

# Pastikan Admin ID berupa List
admin_ids = list(Config.ADMINS)
admin_only = filters.user(admin_ids)

# --- MENU UTAMA ---
@Client.on_message(filters.command(["render", "services"]) & admin_only)
async def render_dashboard(client, message):
    msg = await message.reply("🔄 Memuat layanan Render...", quote=True)
    data, err = await get_services()
    
    if err:
        return await msg.edit(f"❌ Error: {err}")
    
    buttons = []
    # Render API mengembalikan List saat request banyak service
    for item in data:
        # Di endpoint list, data dibungkus dalam key 'service'
        svc = item.get('service', item) 
        status_icon = "🟢" if svc['suspended'] == 'not_suspended' else "🔴"
        buttons.append([InlineKeyboardButton(
            f"{status_icon} {svc['name']}", 
            callback_data=f"rnd_view_{svc['id']}"
        )])
    
    await msg.edit(
        "<b>🎛 Render Control Panel</b>\n\nPilih layanan untuk dikelola:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# --- CALLBACK HANDLER ---
@Client.on_callback_query(filters.regex(r"^rnd_"))
async def render_callbacks(client: Client, query: CallbackQuery):
    if query.from_user.id not in Config.ADMINS:
        return await query.answer("❌ Akses Ditolak!", show_alert=True)

    data = query.data.split("_")
    action = data[1]
    svc_id = data[2] if len(data) > 2 else None

    # 1. VIEW SERVICE DETAILS
    if action == "view":
        svc_data, _ = await get_service(svc_id)
        if not svc_data: return await query.answer("Gagal memuat data service", show_alert=True)
        
        svc = svc_data.get('service', svc_data)
        details = svc.get('serviceDetails', {})
        
        info = (
            f"<b>⚙️ {svc['name']}</b>\n"
            f"ID: <code>{svc['id']}</code>\n"
            f"Status: <code>{svc['suspended']}</code>\n"
            f"Region: <code>{details.get('region', '-')}</code>\n"
            f"Branch: <code>{svc.get('branch', 'main')}</code>\n"
            f"Updated: <code>{svc.get('updatedAt', 'N/A')[:10]}</code>"
        )
        
        buttons = [
            [
                InlineKeyboardButton("🚀 Deploy", callback_data=f"rnd_deploy_{svc_id}"),
                InlineKeyboardButton("ℹ️ Status Deploy", callback_data=f"rnd_dinfo_{svc_id}")
            ],
            [
                InlineKeyboardButton("🔑 Env Vars", callback_data=f"rnd_env_{svc_id}"),
                InlineKeyboardButton("⚙️ Edit Env", callback_data=f"rnd_setenv_{svc_id}")
            ],
            [
                InlineKeyboardButton("⏸ Suspend" if svc['suspended'] == 'not_suspended' else "▶️ Resume", 
                                     callback_data=f"rnd_power_{svc_id}_{svc['suspended']}")
            ],
            [InlineKeyboardButton("🔙 Kembali", callback_data="rnd_back")]
        ]
        await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(buttons))

    # 2. TRIGGER DEPLOY
    elif action == "deploy":
        await query.answer("Mengirim perintah deploy...", show_alert=True)
        res, err = await trigger_deploy(svc_id)
        if err:
            await query.message.reply(f"❌ Gagal: {err}")
        else:
            await query.message.reply(f"🚀 <b>Deploy Dimulai!</b>\nID: <code>{res['id']}</code>")

    # 3. DEPLOY INFO
    elif action == "dinfo":
        deploy, err = await get_last_deploy(svc_id)
        if err: return await query.answer(err, show_alert=True)
        
        status = deploy['status']
        commit = deploy.get('commit', {}).get('message', 'N/A')
        text = (
            f"<b>ℹ️ Last Deploy Info</b>\n\n"
            f"Status: <code>{status}</code>\n"
            f"Commit: <i>{commit}</i>\n"
            f"Finished: <code>{deploy.get('finishedAt', 'Running...')}</code>"
        )
        await query.answer(f"Status: {status}", show_alert=False)
        await query.message.reply(text)

    # 4. VIEW ENV VARS
    elif action == "env":
        envs, err = await get_env_vars(svc_id)
        if err: return await query.answer(err, show_alert=True)
        
        text = f"<b>🔑 Environment Variables ({svc_id})</b>\n\n"
        for item in envs:
            text += f"• <b>{item['envVar']['key']}</b>: <code>{item['envVar']['value']}</code>\n"
        
        if len(text) > 4000:
            text = text[:4000] + "\n...(truncated)"
            
        await query.message.reply(text)

    # 5. EDIT ENV VAR (INPUT HANDLER)
    elif action == "setenv":
        # ForceReply agar user mudah membalas
        await query.message.reply(
            f"✍️ <b>Edit Env Var untuk {svc_id}</b>\n\n"
            "Balas pesan ini dengan format:\n"
            "<code>KEY = VALUE</code>\n\n"
            "Contoh:\n<code>MAX_WORKERS = 4</code>\n"
            "Atau untuk HAPUS:\n<code>KEY = DELETE</code>",
            reply_markup=ForceReply(selective=True)
        )

    # 6. POWER (SUSPEND/RESUME)
    elif action == "power":
        current_status = data[3]
        if current_status == "not_suspended":
            await suspend_service(svc_id)
            await query.answer("Service Suspended ⏸")
        else:
            await resume_service(svc_id)
            await query.answer("Service Resumed ▶️")
        
        await asyncio.sleep(1) 
        new_data, _ = await get_service(svc_id)
        new_svc = new_data.get('service', new_data)
        
        await query.edit_message_text(
            f"Status Berubah! Sekarang: <code>{new_svc['suspended']}</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data=f"rnd_view_{svc_id}")]])
        )

    # 7. BACK BUTTON
    elif action == "back":
        data, _ = await get_services()
        buttons = []
        for item in data:
            svc = item.get('service', item)
            status_icon = "🟢" if svc['suspended'] == 'not_suspended' else "🔴"
            buttons.append([InlineKeyboardButton(f"{status_icon} {svc['name']}", callback_data=f"rnd_view_{svc['id']}")])
        await query.edit_message_text(
            "<b>🎛 Render Control Panel</b>\n\nPilih layanan:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# --- HANDLER REPLY (PERBAIKAN UTAMA) ---
@Client.on_message(filters.reply & admin_only)
async def env_update_handler(client, message):
    # Cek apakah pesan yang dibalas mengandung teks kunci dari Bot
    reply_msg = message.reply_to_message
    if not reply_msg or not reply_msg.text:
        return
        
    if "Edit Env Var untuk" not in reply_msg.text:
        return

    try:
        # Ambil Service ID dari teks pesan bot
        svc_id = reply_msg.text.split("untuk ")[1].split("\n")[0].strip()
        
        user_input = message.text.strip()
        if "=" not in user_input:
            return await message.reply("❌ Format salah. Gunakan: `KEY = VALUE`")
        
        key, value = [x.strip() for x in user_input.split("=", 1)]
        
        msg = await message.reply(f"🔄 Mengupdate <b>{key}</b> ke Render...")
        
        if value.upper() == "DELETE":
            res, err = await delete_env_var(svc_id, key)
            action_txt = "Dihapus"
        else:
            res, err = await update_env_var(svc_id, key, value)
            action_txt = "Diupdate"
            
        if err:
            await msg.edit(f"❌ Gagal: {err}")
        else:
            await msg.edit(f"✅ <b>{key}</b> berhasil {action_txt}!")
            
    except Exception as e:
        await message.reply(f"❌ Error processing: {e}")
