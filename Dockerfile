FROM node:20-bookworm

# Install Electron dependencies + Xvfb + noVNC
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    libgtk-3-0 \
    libgbm1 \
    libnss3 \
    libatk-bridge2.0-0 \
    libasound2 \
    libxss1 \
    libx11-xcb1 \
    fonts-liberation \
    curl \
    dbus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files first for layer caching
COPY package.json package-lock.json ./
RUN npm install --production && \
    npm install electron@42.2.0 --save-dev

# Copy app source
COPY src/ src/
COPY assets/ assets/

# Default env vars
ENV HA_URL="" \
    HA_TOKEN="" \
    DEVICE_NAME="Docker Panel" \
    DISPLAY=:99 \
    RESOLUTION=1280x720 \
    NOVNC_PORT=8080 \
    ELECTRON_FLAGS="--no-sandbox --disable-gpu-sandbox --disable-dev-shm-usage"

# Copy entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Expose noVNC
EXPOSE 8080

VOLUME ["/config"]

ENTRYPOINT ["/docker-entrypoint.sh"]
