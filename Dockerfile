FROM python:3-slim

RUN <<EOF
adduser --disabled-password --gecos "" --home=/app --uid=1051 patty
apt update && apt install --yes --no-install-recommends entr
rm -rf /var/lib/apt/lists/*
mkdir -p /app/src /app/data /app/out
EOF

# For development only
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY ./src /app/src
COPY entrypoint.sh /app/

ENV PYTHONPATH=/app/src

ARG CONTEXT=local
ENV CONTEXT=${CONTEXT}

ARG VERSION=development
ENV VERSION=${VERSION}

ENV ENTR_INOTIFY_WORKAROUND=1

VOLUME [ "/app/src" ]
VOLUME [ "/app/data" ]
VOLUME [ "/app/out" ]

USER patty
ENTRYPOINT [ "/app/entrypoint.sh" ]
CMD ["start"]

