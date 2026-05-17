# [FILE: bot/modules/status.py]

import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message
from pyrogram.errors import FloodWait, MessageNotModified

# Mengimpor GLOBAL_UI_MSG dan GLOBAL_UI_PAGES untuk menyambungkan kabel radar Papan Global
from bot.helpers.utils import get_status_text, GLOBAL_UI_MSG, GLOBAL_UI_PAGES
from bot.logger import LOGGER

@Client.on_message(filters.command(["task", "tasks"]))
async def task_command(client: Client, message: Message):
    chat_id = message.chat.id
    
    # --- [FIX SPAM PAPAN GLOBAL] HAPUS PESAN LAMA JIKA ADA ---
    if chat_id in GLOBAL_UI_MSG:
        try:
            # Menggunakan delete_messages untuk penghapusan yang lebih pasti dan absolut
            await client.delete_messages(chat_id, GLOBAL_UI_MSG[chat_id].id)
        except Exception:
            pass
    # ---------------------------------------------------------

    # --- [MEMORI HALAMAN] Set halaman ke 1 saat /task dikirim ---
    GLOBAL_UI_PAGES[chat_id] = 1
    # ------------------------------------------------------------
    
    text, markup = get_status_text(page=1)
    
    try:
        # Menyimpan pesan yang dikirim bot ke dalam variabel
        sent_msg = await message.reply(text, reply_markup=markup, disable_web_page_preview=True)
        
        # Mendaftarkan pesan ini ke dalam memori Radar agar diperbarui secara real-time
        GLOBAL_UI_MSG[chat_id] = sent_msg
        
    except FloodWait as e:
        LOGGER.warning(f"Terkena FloodWait {e.value} detik saat mengirim /task.")
        await asyncio.sleep(e.value)
        # Coba kirim lagi setelah tidur sejenak
        try:
            sent_msg = await message.reply(text, reply_markup=markup, disable_web_page_preview=True)
            GLOBAL_UI_MSG[chat_id] = sent_msg
        except Exception:
            pass
    except Exception as e:
        LOGGER.error(f"Gagal mengirim /task: {e}")

@Client.on_callback_query(filters.regex(r"^status_"))
async def status_callback(client: Client, query: CallbackQuery):
    data = query.data
    chat_id = query.message.chat.id
    
    if data == "status_close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return
        
    if data.startswith("status_page_"):
        page = int(data.split("_")[-1])
        
        # --- [MEMORI HALAMAN] Simpan posisi halaman saat klik Next/Prev ---
        GLOBAL_UI_PAGES[chat_id] = page
        # ------------------------------------------------------------------
        
        text, markup = get_status_text(page=page)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            try: await query.answer()
            except Exception: pass
        except FloodWait as e:
            # --- [FIX SPAM TOMBOL] JANGAN DITIDURKAN, TOLAK KLIKNYA! ---
            try: await query.answer(f"⏳ Terlalu cepat! Tunggu {e.value} detik.", show_alert=True)
            except Exception: pass
            
            # Kembalikan posisi halaman karena edit ke halaman baru gagal
            try:
                if "Next" in query.message.reply_markup.inline_keyboard[0][0].text:
                    GLOBAL_UI_PAGES[chat_id] = page - 1
                else:
                    GLOBAL_UI_PAGES[chat_id] = page + 1
            except Exception: pass
        except MessageNotModified:
            try: await query.answer()
            except Exception: pass
        except Exception:
            pass
            
    elif data.startswith("status_refresh_"):
        page = int(data.split("_")[-1])
        
        # --- [MEMORI HALAMAN] Simpan posisi halaman saat klik Refresh ---
        GLOBAL_UI_PAGES[chat_id] = page
        # ----------------------------------------------------------------
        
        text, markup = get_status_text(page=page)
        try:
            await query.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            await query.answer("Status diperbarui!", show_alert=False)
        except FloodWait as e:
            # --- [FIX SPAM TOMBOL] JANGAN DITIDURKAN, TOLAK KLIKNYA! ---
            try: await query.answer(f"⏳ Terlalu cepat! Tunggu {e.value} detik.", show_alert=True)
            except Exception: pass
        except MessageNotModified:
            try: await query.answer("Status sudah yang terbaru!", show_alert=False)
            except Exception: pass
        except Exception:
            pass
