#!/bin/env bash

# Debug entrypoint: runs Django's dev server under debugpy so VS Code can attach.
# Used by docker-compose.debug.yml. See docker/README.md.

bash ./Entrypoints/wait-for-it.sh yse_db:3306 --timeout=0 &&

# debugpy is installed into the bind-mounted repo (/app/.debugpy, git-ignored)
# rather than the image, so the runtime image stays untouched. It's a one-time
# install: later restarts find it and skip pip. Needs PyPI access on first start.
if [ ! -d /app/.debugpy/debugpy ]; then
    pip3 install --target /app/.debugpy debugpy==1.8.21
fi &&

# --noreload keeps a single process, which is what the debugger can follow.
# Without --wait-for-client the server starts immediately; attach whenever ready.
PYTHONPATH=/app/.debugpy exec python3 -m debugpy --listen 0.0.0.0:5678 \
    manage.py runserver 0.0.0.0:8000 --noreload
