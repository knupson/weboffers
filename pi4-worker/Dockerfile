FROM python:3.12-slim

WORKDIR /app
COPY worker.py /app/worker.py

# Corre en ARM64 (Raspberry Pi 4) sin dependencias pesadas
CMD ["python", "/app/worker.py"]
