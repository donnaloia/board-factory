FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uvicorn --reload subprocesses need this even when WORKDIR is /app (path quirks).
ENV PYTHONPATH=/app:/repo/pipeline

COPY app/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install the boardfactory pipeline as an editable package so the web app
# can call its ops directly (draw_cell, orchestrate, style, preview, etc.)
# via the pipeline_adapters module.
COPY pipeline/requirements.txt /tmp/pipeline-requirements.txt
RUN pip install --no-cache-dir -r /tmp/pipeline-requirements.txt
# Install from /repo/pipeline so the runtime bind-mount (./:/repo) makes
# pipeline edits visible without a rebuild. The COPY here seeds the path
# for standalone image runs; the volume overlay replaces it at runtime.
COPY pipeline/pyproject.toml  /repo/pipeline/pyproject.toml
COPY pipeline/boardfactory    /repo/pipeline/boardfactory
RUN pip install --no-cache-dir -e /repo/pipeline

# Application code (FastAPI — sibling to ``pipeline/`` in the repo)
COPY app/routes              /app/routes
COPY app/server.py             /app/
COPY app/board_svg.py          /app/
COPY app/spec_data.py          /app/
COPY app/jobs.py               /app/
COPY app/cost_ledger.py        /app/
COPY app/pipeline_adapters.py  /app/
COPY app/auth.py               /app/
COPY app/sessions.py           /app/
COPY app/users.py              /app/
COPY app/pixellab_status.py    /app/
COPY app/templates             /app/templates
COPY app/static                /app/static

COPY app/storage               /app/storage
COPY app/services              /app/services
COPY app/migrations            /app/migrations
COPY app/alembic.ini           /app/alembic.ini
COPY app/tests                 /app/tests

EXPOSE 8473
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8473", \
     "--reload", "--reload-dir", "/app", "--reload-dir", "/app/routes", "--reload-dir", "/repo/pipeline/boardfactory", \
     "--timeout-graceful-shutdown", "2"]
