FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app/worker
RUN pip install --no-cache-dir requests
COPY worker.py creators_api.py rates.py publish.py telegram.py ./
CMD ["python", "worker.py"]
