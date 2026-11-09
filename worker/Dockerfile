FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app/worker
RUN pip install --no-cache-dir requests Pillow
COPY worker.py creators_api.py ml_prices.py ml_fichas.py amazon_prices.py rates.py publish.py telegram.py catalog.py catalog_auto.py variants.py refresh_lock.py article_log.py alta_state.py requisitos.py ./
CMD ["python", "worker.py"]
