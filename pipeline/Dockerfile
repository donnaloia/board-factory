FROM python:3.12-slim

# System libraries needed by Pillow.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    libpng16-16 \
    libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml /app/
COPY boardfactory /app/boardfactory
RUN pip install --no-cache-dir -e .

# This image is a library used by the Board Factory web app (`app/`) — there is no CLI
# entrypoint anymore. The web app installs this package editable and calls
# `boardfactory.ops.draw_cell` directly.
WORKDIR /repo
