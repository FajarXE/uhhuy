import asyncio
import speedtest
import os
import sys
from pyrogram import Client, filters
from config import Config

# Filter Admin
admin_only = filters.user(list(Config.ADMINS))

# --- CLASS PEREDAM OUTPUT (Supaya tidak Error 'NoneType write') ---
class SuppressOutput:
    def __enter__(self):
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

# --- HANDLER ---
@Client.on_message(filters.command(["speedtest", "speed"]) & admin_only)
async def speedtest_handler(client, message):
    m = await message.reply_text("🚀 **Menjalankan Speedtest...**\nMohon tunggu sekitar 30 detik...", quote=True)
    
    try:
        # Jalankan di thread terpisah agar bot tidak macet
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_speedtest)
        
        # Format Text Output
        output_text = (
            "**📊 Speedtest Results**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"**ISP:** {result['client']['isp']}\n"
            f"**Ping:** `{result['ping']} ms`\n"
            f"**Download:** `{result['download_str']}`\n"
            f"**Upload:** `{result['upload_str']}`\n"
            f"**Server:** {result['server']['name']} ({result['server']['country']})"
        )
        
        # Kirim Gambar Hasil
        # result['share'] adalah link gambar PNG dari speedtest.net
        await message.reply_photo(
            photo=result['share'],
            caption=output_text
        )
        await m.delete()
        
    except Exception as e:
        await m.edit(f"❌ **Speedtest Gagal:**\n`{e}`")

def run_speedtest():
    # Gunakan peredam agar tidak print progress bar ke console (Penyebab Error)
    with SuppressOutput():
        # secure=True penting untuk HTTPS
        s = speedtest.Speedtest(secure=True)
        s.get_best_server()
        s.download()
        s.upload()
        
        # [PENTING] Generate Link Gambar
        s.results.share()
        
        res = s.results.dict()
        
        # Konversi bit ke Mbit
        d_mbit = res["download"] / 1024 / 1024
        u_mbit = res["upload"] / 1024 / 1024
        
        res['download_str'] = f"{d_mbit:.2f} Mbit/s"
        res['upload_str'] = f"{u_mbit:.2f} Mbit/s"
        
        return res
