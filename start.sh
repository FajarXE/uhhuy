#!/bin/bash

# Tangkap sinyal terminasi (SIGINT, SIGTERM, EXIT) dan bunuh semua proses anak
trap 'kill $(jobs -p) 2>/dev/null; exit' SIGINT SIGTERM EXIT

# Menjalankan daemon aria2c dengan RPC Secret dan akses lokal
aria2c --daemon=true \
       --enable-rpc \
       --rpc-listen-all=false \
       --rpc-listen-port=6800 \
       --rpc-secret=siesta_secret_token \
       -j 20 \
       --max-connection-per-server=1 \
       --split=1 \
       --min-split-size=5M \
       --continue=true \
       --allow-overwrite=true \
       --rpc-max-request-size=1024M \
       --seed-time=0

# Menjalankan API Scraper Audiomack dan menyimpan lognya
uvicorn audiomack_api.main:app --host 127.0.0.1 --port 8000 > uvicorn_error.log 2>&1 &

# [FIX] Tunggu secara dinamis hingga Uvicorn siap (Maksimal 20 detik)
echo "Menunggu API Uvicorn Audiomack siap..."
for i in {1..20}; do
    if curl -s http://127.0.0.1:8000/docs > /dev/null; then
        echo "Uvicorn siap dalam ${i} detik!"
        break
    fi
    sleep 1
done

echo "=== LOG UVICORN AUDIOMACK ==="
cat uvicorn_error.log
echo "============================="

# Menjalankan bot utama
python3 -m bot & 
wait
