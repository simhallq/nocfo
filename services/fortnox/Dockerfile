FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
COPY rules.yaml .
RUN pip install --no-cache-dir .
RUN playwright install chromium --with-deps

EXPOSE 8790
CMD ["fortnox", "browser", "start"]
