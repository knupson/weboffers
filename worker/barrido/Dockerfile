FROM python:3.12-slim
ARG BARRIDO_GIT_COMMIT=no_disponible
ENV BARRIDO_GIT_COMMIT=${BARRIDO_GIT_COMMIT}
ENV BARRIDO_VERSION=observabilidad-v1
WORKDIR /app
ENV PYTHONUNBUFFERED=1
# Sólo cliente CDP: no descarga Chromium ni ejecuta playwright install.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY barrido/requirements.txt /tmp/barrido-requirements.txt
RUN pip install --no-cache-dir -r /tmp/barrido-requirements.txt
COPY barrido /app/barrido
# 10/11: ml_prices importa diario, requisitos, publicacion y amazon_prices; sin ellos barrido_ml falla con ModuleNotFoundError.
COPY amazon_shipping.py ml_prices.py refresh_lock.py article_log.py publish.py variants.py diario.py requisitos.py publicacion.py amazon_prices.py /app/
CMD ["python", "-m", "barrido.server"]
