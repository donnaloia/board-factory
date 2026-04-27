FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py /app/
COPY templates /app/templates
COPY static /app/static

EXPOSE 8473
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8473"]
