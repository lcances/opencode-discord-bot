#!/bin/sh
set -e

echo "Starting OpenCode server..."
sh -c 'opencode serve --port 4096 --hostname 0.0.0.0' &

echo "Waiting for OpenCode server to be ready..."
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:4096/global/health > /dev/null 2>&1; then
        echo "OpenCode server is ready!"
        break
    fi
    sleep 1
done

echo "Starting Discord bot..."
export EXTERNAL_OPENCODE=1
exec python3 main.py
