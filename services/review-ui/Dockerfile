FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/review-ui/requirements.txt /app/
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

# Application code
COPY services/review-ui/server.py             /app/
COPY services/review-ui/board_svg.py          /app/
COPY services/review-ui/spec_data.py          /app/
COPY services/review-ui/jobs.py               /app/
COPY services/review-ui/cost_ledger.py        /app/
COPY services/review-ui/pipeline_adapters.py  /app/
COPY services/review-ui/auth.py               /app/
COPY services/review-ui/sessions.py           /app/
COPY services/review-ui/users.py              /app/
COPY services/review-ui/pixellab_status.py    /app/
COPY services/review-ui/templates             /app/templates
COPY services/review-ui/static                /app/static

EXPOSE 8473
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8473", \
     "--reload", "--reload-dir", "/app", "--reload-dir", "/repo/pipeline/boardfactory", \
     "--timeout-graceful-shutdown", "2"]
