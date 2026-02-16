import asyncio
import speedtest
import os
import sys
import time
from pyrogram import Client, filters
from config import Config

# Filter Admin
admin_only = filters.user(list(Config.ADMINS))

# --- CLASS PEREDAM OUTPUT ---
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
    m = await message.reply_text("🚀 **Menjalankan Speedtest...**\nMohon tunggu...", quote=True)
    
    try:
        # Jalankan di thread terpisah
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_speedtest)
        
        # Format Text Output sesuai permintaan
        output_text = (
            "**📊 Speedtest Results**\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"**ISP:** {result['client']['isp']}\n"
            f"**Server:** {result['server']['name']}\n"
            f"**Region:** {result['server']['country']}, {result['server']['cc']}\n"
            f"**IP:** {result['ip_masked']}\n\n"
            
            f"**Download:** `{result['download_mbyte']}`\n"
            f"**Upload:** `{result['upload_mbyte']}`\n"
            f"**Ping:** `{result['ping']} ms`\n\n"
            
            f"**Executed Time:** `{result['exec_time']} sec`"
        )
        
        # Kirim Gambar Hasil
        await message.reply_photo(
            photo=result['share'],
            caption=output_text
        )
        await m.delete()
        
    except Exception as e:
        await m.edit(f"❌ **Speedtest Gagal:**\n`{e}`")

def run_speedtest():
    start_time = time.time()  # Mulai hitung waktu
    
    with SuppressOutput():
        s = speedtest.Speedtest(secure=True)
        s.get_best_server()
        s.download()
        s.upload()
        s.results.share()
        
        res = s.results.dict()
        
        # 1. Konversi ke MB/s (Megabyte/s)
        # Note: Speedtest memberikan bits. 1 Byte = 8 bits.
        d_mbyte = (res["download"] / 8) / 1024 / 1024
        u_mbyte = (res["upload"] / 8) / 1024 / 1024
        
        res['download_mbyte'] = f"{d_mbyte:.2f} MB/s"
        res['upload_mbyte'] = f"{u_mbyte:.2f} MB/s"
        
        # 2. Masking IP (Sensor IP)
        real_ip = res['client']['ip']
        try:
            # Ambil 2 segmen pertama, sisanya sensor
            parts = real_ip.split('.')
            if len(parts) >= 2:
                masked_ip = f"{parts[0]}.{parts[1]}xxxxxx"
            else:
                masked_ip = "Hidden"
        except:
            masked_ip = "Hidden"
        
        res['ip_masked'] = masked_ip
        
        # 3. Hitung Waktu Eksekusi
        end_time = time.time()
        exec_duration = end_time - start_time
        res['exec_time'] = f"{exec_duration:.2f}"
        
        return res
