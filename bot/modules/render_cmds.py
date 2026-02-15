from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ForceReply
from config import Config
from bot.helpers.render_api import (
    get_services, get_service, trigger_deploy, get_last_deploy, 
    suspend_service, resume_service, get_env_vars, update_env_var, 
    delete_env_var, delete_service, cancel_deploy
)
import asyncio

# Pastikan Admin ID berupa List
admin_ids = list(Config.ADMINS)
admin_only = filters.user(admin_ids)

# --- FUNGSI MONITOR DEPLOY (BACKGROUND TASK) ---
async def monitor_deployment(client, chat_id, service_id, deploy_id, status_msg):
    timeout = 1200  # 20 menit batas waktu
    elapsed = 0
    
    while elapsed < timeout:
        await asyncio.sleep(15) 
        elapsed += 15
        
        deploy, err = await get_last_deploy(service_id)
        if err or not deploy:
            continue

        current_status = deploy['status']
        
        if current_status == "live":
            await client.send_message(
                chat_id,
                f"✅ **DEPLOY SELESAI!**\n\nService: `{service_id}`\nStatus: **LIVE** 🟢\nCommit: `{deploy.get('commit', {}).get('message', 'N/A')}`",
                reply_to_message_id=status_msg.id
            )
            return
            
        elif current_status in ["build_failed", "update_failed", "canceled"]:
            emoji = "🚫" if current_status == "canceled" else "🔴"
            await client.send_message(
                chat_id,
                f"❌ **DEPLOY BERHENTI!**\n\nService: `{service_id}`\nStatus: `{current_status}` {emoji}",
                reply_to_message_id=status_msg.id
            )
            return

    await client.send_message(chat_id, f"⚠️ Monitoring Deploy `{deploy_id}` berhenti (Timeout 20 menit). Silakan cek manual.")


# --- COMMAND: LOGOUT ---
@Client.on_message(filters.command("logout") & admin_only)
async def logout_command(client, message):
    # Penjelasan: Karena ini bot pribadi (Personal Mode) yang kuncinya ada di Config,
    # kita tidak bisa "menghapus" kunci itu tanpa mematikan bot.
    await message.reply(
        "🔒 **Info Keamanan**\n\n"
        "Anda saat ini login menggunakan **Mode Config (Environment Variable)**.\n"
        "Ini artinya akun Render terhubung secara permanen ke server bot ini.\n\n"
        "Untuk Logout sepenuhnya:\n"
        "1. Buka Dashboard Render\n"
        "2. Hapus variabel `RENDER_API_KEY`\n"
        "3. Bot akan otomatis restart dan kehilangan akses."
    )

# --- MENU UTAMA ---
@Client.on_message(filters.command(["render", "services"]) & admin_only)
async def render_dashboard(client, message):
    msg = await message.reply("🔄 Memuat layanan Render...", quote=True)
    data, err = await get_services()
    
    if err:
        return await msg.edit(f"❌ Error: {err}")
    
    buttons = []
    for item in data:
        svc = item.get('service', item) 
        status_icon = "🟢" if svc['suspended'] == 'not_suspended' else "🔴"
        buttons.append([InlineKeyboardButton(
            f"{status_icon} {svc['name']}", 
            callback_data=f"rnd_view_{svc['id']}"
        )])
    
    buttons.append([InlineKeyboardButton("❌ Tutup", callback_data="rnd_close")])
    
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
    
    if action == "close":
        await query.message.delete()
        return

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
            await query.message.reply(f"❌ Gagal Deploy: {err}")
        else:
            deploy_id = res['id']
            status_msg = await query.message.reply(
                f"🚀 <b>Deploy Dimulai!</b>\n"
                f"ID: <code>{deploy_id}</code>\n\n"
                f"⏳ <i>Bot akan memberi tahu Anda saat deploy selesai...</i>"
            )
            asyncio.create_task(monitor_deployment(client, query.message.chat.id, svc_id, deploy_id, status_msg))

    # 3. DEPLOY INFO (+ FITUR CANCEL)
    elif action == "dinfo":
        deploy, err = await get_last_deploy(svc_id)
        if err: return await query.answer(err, show_alert=True)
        
        status = deploy['status']
        deploy_id = deploy['id']
        commit = deploy.get('commit', {}).get('message', 'N/A')
        
        text = (
            f"<b>ℹ️ Last Deploy Info</b>\n\n"
            f"ID: <code>{deploy_id}</code>\n"
            f"Status: <code>{status}</code>\n"
            f"Commit: <i>{commit}</i>\n"
            f"Finished: <code>{deploy.get('finishedAt', 'Running...')}</code>"
        )
        
        # Tombol Kembali Standar
        buttons = [[InlineKeyboardButton("🔙 Kembali", callback_data=f"rnd_view_{svc_id}")]]
        
        # [FITUR BARU] Cek apakah status masih berjalan, jika ya tambahkan tombol Cancel
        if status in ["build_in_progress", "pre_deploy_in_progress", "live_in_progress", "created"]:
            buttons.insert(0, [InlineKeyboardButton("⛔ BATALKAN DEPLOY", callback_data=f"rnd_cancel_{svc_id}_{deploy_id}")])
            
        await query.answer(f"Status: {status}", show_alert=False)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    # 4. CANCEL DEPLOY (ACTION)
    elif action == "cancel":
        deploy_id = data[3] # Ambil ID deploy dari callback
        await query.answer("Mengirim perintah pembatalan...", show_alert=True)
        
        res, err = await cancel_deploy(svc_id, deploy_id)
        
        if err:
            await query.message.reply(f"❌ Gagal Membatalkan: {err}")
        else:
            await query.message.reply(f"🛑 <b>Deploy Dibatalkan!</b>\nID: `{deploy_id}` berhasil dihentikan.")
            # Refresh tampilan info
            await render_callbacks(client, query) # Panggil ulang logic dinfo? atau biarkan user klik manual

    # 5. VIEW ENV VARS
    elif action == "env":
        envs, err = await get_env_vars(svc_id)
        if err: return await query.answer(err, show_alert=True)
        
        text = f"<b>🔑 Environment Variables ({svc_id})</b>\n\n"
        for item in envs:
            text += f"• <b>{item['envVar']['key']}</b>: <code>{item['envVar']['value']}</code>\n"
        
        if len(text) > 4000:
            text = text[:4000] + "\n...(truncated)"
            
        await query.message.reply(text)

    # 6. EDIT ENV VAR
    elif action == "setenv":
        await query.message.reply(
            f"✍️ <b>Edit Env Var untuk {svc_id}</b>\n\n"
            "Silakan kirim variabel Anda (Bisa banyak baris sekaligus).\n"
            "Format per baris:\n"
            "<code>KEY = VALUE</code>\n\n"
            "Contoh Bulk:\n"
            "<code>EMAIL = tes@tes.com\nPASS = 12345\nPROXY = socks5://...</code>",
            reply_markup=ForceReply(selective=True)
        )

    # 7. POWER (SUSPEND/RESUME)
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

    # 8. BACK BUTTON
    elif action == "back":
        data, _ = await get_services()
        buttons = []
        for item in data:
            svc = item.get('service', item)
            status_icon = "🟢" if svc['suspended'] == 'not_suspended' else "🔴"
            buttons.append([InlineKeyboardButton(f"{status_icon} {svc['name']}", callback_data=f"rnd_view_{svc['id']}")])
        
        buttons.append([InlineKeyboardButton("❌ Tutup", callback_data="rnd_close")])

        await query.edit_message_text(
            "<b>🎛 Render Control Panel</b>\n\nPilih layanan untuk dikelola:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# --- HANDLER REPLY (BULK UPDATE) ---
@Client.on_message(filters.reply & admin_only)
async def env_update_handler(client, message):
    reply_msg = message.reply_to_message
    if not reply_msg or not reply_msg.text:
        return
    if "Edit Env Var untuk" not in reply_msg.text:
        return

    try:
        svc_id = reply_msg.text.split("untuk ")[1].split("\n")[0].strip()
        
        lines = message.text.strip().split('\n')
        if not lines: return

        progress_msg = await message.reply(f"🔄 Memproses {len(lines)} variabel...")
        report = []
        
        for line in lines:
            if "=" not in line: 
                continue 
            
            key, value = [x.strip() for x in line.split("=", 1)]
            
            if value.upper() == "DELETE":
                res, err = await delete_env_var(svc_id, key)
                status = "🗑 Dihapus"
            else:
                res, err = await update_env_var(svc_id, key, value)
                status = "✅ Diupdate"
            
            if err:
                report.append(f"❌ <b>{key}</b>: Gagal ({err})")
            else:
                report.append(f"{status}: <b>{key}</b>")
        
        final_report = "\n".join(report)
        await progress_msg.edit(f"<b>Laporan Bulk Update:</b>\n\n{final_report}")
            
    except Exception as e:
        await message.reply(f"❌ Error processing: {e}")
