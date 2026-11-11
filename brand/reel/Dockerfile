# Reel diario de Franquicia 400 en la VM docker (11/11: «nada corre en la PC»).
# Uso: ver brand/reel/hacer_reel_vm.sh. El modelo de voz se monta en /voz (no va en la imagen).
FROM node:22-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg python3 ca-certificates curl \
        libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libgbm1 libasound2 libxrandr2 libxkbcommon0 \
        libxfixes3 libxcomposite1 libxdamage1 libpango-1.0-0 libcairo2 libcups2 libdrm2 libxshmfence1 \
        fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Piper 2023.11.14-2 para Linux x86_64 (la misma versión de voz que se usaba en Windows).
RUN curl -fsSL https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz \
        | tar -xz -C /opt && /opt/piper/piper --help >/dev/null

WORKDIR /repo/brand/reel
COPY package.json package-lock.json ./
RUN npm ci && npx remotion browser ensure
# Código del Reel dentro de la imagen; datos, fotos, voz, historial y salida se montan al correr.
COPY . .

ENV REEL_PIPER=/opt/piper/piper \
    REEL_MODELO=/voz/es_AR-daniela-high.onnx \
    TZ=America/Argentina/Buenos_Aires
