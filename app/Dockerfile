FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    libpng16-16 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uvicorn --reload subprocesses need this even when WORKDIR is /app (path quirks).
ENV PYTHONPATH=/app:/repo/pipeline

COPY app/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install the boardfactory pipeline as an editable package so the web app
# can call its ops directly (draw_cell, orchestrate, style, preview, etc.)
# via domains/*/pipeline_jobs.py (e.g. domains.boards.pipeline_jobs).
COPY pipeline/requirements.txt /tmp/pipeline-requirements.txt
RUN pip install --no-cache-dir -r /tmp/pipeline-requirements.txt
# Install from /repo/pipeline so the runtime bind-mount (./:/repo) makes
# pipeline edits visible without a rebuild. The COPY here seeds the path
# for standalone image runs; the volume overlay replaces it at runtime.
COPY pipeline/pyproject.toml      /repo/pipeline/pyproject.toml
COPY pipeline/boardfactory        /repo/pipeline/boardfactory
COPY pipeline/space_animations    /repo/pipeline/space_animations
COPY pipeline/tokenfactory        /repo/pipeline/tokenfactory
COPY pipeline/cardfactory         /repo/pipeline/cardfactory
RUN pip install --no-cache-dir -e /repo/pipeline

# Pre-download the U2Net background-removal model (~176 MB) so the first
# clip/candidate generation doesn't stall on a live model fetch.
RUN python -c "from tokenfactory.steps.bg_remove import _session; _session()"

# Application code (FastAPI — sibling to ``pipeline/`` in the repo).
# We copy the entire app/ tree so adding new modules / domains doesn't need
# Dockerfile churn. Per-domain folders are organized vertical-slice; see
# ``app/ARCHITECTURE.md``.
COPY app/                    /app/

EXPOSE 8473
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8473", \
     "--reload", "--reload-dir", "/app", "--reload-dir", "/app/infrastructure", \
     "--reload-dir", "/repo/pipeline/boardfactory", "--reload-dir", "/repo/pipeline/space_animations", \
     "--reload-dir", "/repo/pipeline/tokenfactory", "--reload-dir", "/repo/pipeline/cardfactory", \
     "--timeout-graceful-shutdown", "2"]
