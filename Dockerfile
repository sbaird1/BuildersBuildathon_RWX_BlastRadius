# # The scorer builds this on linux/amd64 and runs it with no network. The
# # digest is the image we labeled every commit in: its Python and SQLite
# # decide which sqlglot tests run, so keep it if your image runs them.
# FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
# COPY selector.py /app/selector.py
# CMD ["python", "/app/selector.py"]
# ^^^ OLD CODE ^^^

# Build-time analysis stage
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS coverage-build

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.lock /build/requirements.lock

RUN pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir coverage==7.10.6

# Fetch exactly the repository revision used by the challenge.
RUN git init /build/sqlglot \
    && cd /build/sqlglot \
    && git remote add origin https://github.com/tobymao/sqlglot.git \
    && git fetch --depth 1 origin eb11aec4be8cb2122afe713a4816662c3f0fb2fa \
    && git checkout FETCH_HEAD

COPY sample/tests.json /build/tests.json
COPY build_coverage.py /build/build_coverage.py

ENV PYTHONPATH=/build/sqlglot
ENV SKIP_INTEGRATION=0

RUN python /build/build_coverage.py


# Final runtime stage
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

WORKDIR /app

COPY selector.py /app/selector.py
COPY --from=coverage-build /build/coverage.json /app/coverage.json

CMD ["python", "/app/selector.py"]
