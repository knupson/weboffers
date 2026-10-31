FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN git clone https://github.com/omkarcloud/amazon-scraper.git /app \
    && git checkout 8ffd4f976c705d009ec06d8e4e3e15fc77e35cee
RUN pip install --no-cache-dir -r requirements.txt
COPY ar_server.py .
CMD ["python", "ar_server.py"]
