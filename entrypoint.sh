#!/bin/sh
set -e
dockerd --exec-opt native.cgroupdriver=cgroupfs 2>/dev/null &
echo "Waiting for Docker daemon..."
until docker info >/dev/null 2>&1; do sleep 1; done
echo "Docker daemon ready."
exec uvicorn main:app --host 0.0.0.0 --port 8082 --app-dir /app
