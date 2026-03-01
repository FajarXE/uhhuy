# [FILE: Dockerfile]

# --- FIX 1: Tambahkan --platform=linux/amd64 untuk memaksa 64-bit ---
FROM --platform=linux/amd64 python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Jakarta

WORKDIR /usr/src/app

# Install curl dan dependencies sistem (DITAMBAHKAN: aria2)
RUN apt-get update -qq && \
    apt-get install -qq -y ffmpeg gcc libffi-dev curl zip cargo pkg-config git aria2 && \
    rm -rf /var/lib/apt/lists/*

# Builder Stage
FROM --platform=linux/amd64 base AS builder
RUN apt-get update -qq && \
    apt-get install -qq -y git wget unzip && \
    rm -rf /var/lib/apt/lists/*

# Download Rclone (Hardcode amd64 karena kita sudah paksa platform di atas)
RUN curl -O https://downloads.rclone.org/v1.70.2/rclone-v1.70.2-linux-amd64.zip && \
    unzip rclone-v1.70.2-linux-amd64.zip && \
    install -m 755 rclone-v1.70.2-linux-amd64/rclone /usr/bin/rclone && \
    rm -rf rclone-v1.70.2-linux-amd64*

# Final Stage
FROM --platform=linux/amd64 base AS final

COPY --from=builder /usr/bin/rclone /usr/bin/rclone
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENTRYPOINT ["bash", "start.sh"]
