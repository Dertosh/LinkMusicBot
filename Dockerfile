FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock && pip check

COPY --chown=10001:10001 linkmusicbot/ ./linkmusicbot/
COPY --chown=10001:10001 bot.py converter.py security.py ./
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
RUN mkdir -p /app/data && chown 10001:10001 /app/data

USER 10001:10001
CMD ["python", "-m", "linkmusicbot"]
