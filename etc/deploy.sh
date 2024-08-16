#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel)
PROJECT_NAME=$(basename $PROJECT_ROOT)

printf " --\n"
printf " -- deploying $PROJECT_NAME (from $PROJECT_ROOT)\n"
printf " --\n"
rsync -az \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude "*.DS_Store" \
    --exclude ".git*" \
    --exclude ".venv" \
    --exclude ".ruff_*" \
    --exclude "data/" \
    --exclude "out/" \
    $PROJECT_ROOT/ fibonet:/home/$PROJECT_NAME/

## service recomposition
printf " --\n"
printf " -- rebuilding services\n"
printf " --\n"
ssh fibonet /bin/bash <<'EOT'
chown -R area51:area51 /home/$PROJECT_NAME
set -euo pipefail
cd /home/chatty-patty
docker-compose build
docker-compose down --remove-orphans
docker-compose up --detach --remove-orphans
EOT
