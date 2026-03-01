#!/bin/bash

# Menjalankan daemon aria2c di background dengan mode RPC aktif
aria2c --enable-rpc --rpc-listen-all=false --rpc-listen-port=6800 --max-connection-per-server=10 --rpc-max-request-size=1024M --seed-time=0 &

# Menjalankan bot utama
python3 -m bot
