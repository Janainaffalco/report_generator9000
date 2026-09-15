FROM node:22-bookworm-slim AS frontend-builder

RUN corepack enable

WORKDIR /build/web
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN mkdir -p /build/report_generator9000 \
    && pnpm run build


FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY pyproject.toml README.md ./
COPY report_generator9000/ ./report_generator9000/
COPY --from=frontend-builder /build/report_generator9000/web_dist ./report_generator9000/web_dist

# LibreOffice renders the certified PDF and review pages from the same
# generated DOCX -- Montserrat is installed system-wide so that render
# matches the Master's typography instead of falling back to a substitute.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer-nogui \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/local/share/fonts/montserrat

COPY report_generator9000/assets/*.ttf /usr/local/share/fonts/montserrat/
RUN fc-cache -f

RUN python -m pip install --no-cache-dir --no-warn-script-location . \
    && mkdir -p /app/data \
    && chown -R pwuser:pwuser /app/data

USER pwuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "report_generator9000.web:app", "--host", "0.0.0.0", "--port", "8000"]
