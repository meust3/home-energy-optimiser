# Build context: immutable Panel archive plus a locally built Energy wheel.
# This is a test harness image, never an App/production image.
FROM python:3.12.11-slim
COPY apps/api /panel/apps/api
COPY services/system_one /panel/services/system_one
COPY packages/client-python /sdk
COPY wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl /sdk \
    fastapi==0.141.1 uvicorn==0.54.0 psycopg-pool==3.3.3 \
    cryptography==50.0.1 argon2-cffi==25.1.0
ENV PYTHONDONTWRITEBYTECODE=1
