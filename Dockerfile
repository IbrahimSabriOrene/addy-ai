FROM python:3.12-slim

WORKDIR /app
ENV ADMAKER_MIGRATIONS_DIR=/app/migrations
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml .
COPY src ./src
COPY migrations ./migrations
RUN pip install --no-cache-dir --no-deps .

CMD ["admaker-api"]
