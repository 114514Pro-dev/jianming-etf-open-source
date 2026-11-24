FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG GIT_REVISION
ARG SOURCE_ARCHIVE_SHA
LABEL org.opencontainers.image.revision=$GIT_REVISION
LABEL io.project.source-archive-sha256=$SOURCE_ARCHIVE_SHA
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RELEASE_REVISION=$GIT_REVISION
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && groupadd --gid 10001 etf && useradd --uid 10001 --gid etf --no-create-home etf
COPY --chown=10001:10001 . /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
