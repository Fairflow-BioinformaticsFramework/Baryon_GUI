#!/bin/bash
set -e

echo ""
echo " ===================================="
echo "  BaryonRunner"
echo " ===================================="
echo ""

if ! docker info >/dev/null 2>&1; then
    echo "[ERROR] Docker is not running. Please start Docker and retry."
    exit 1
fi

echo "[1/2] Pulling latest image..."
docker pull ghcr.io/fairflow-bioinformaticsframework/baryon_gui:latest

echo ""
echo "[2/2] Starting BaryonRunner..."
echo ""
echo "  GUI  >  http://localhost:8082"
echo ""

docker rm -f baryonrunner >/dev/null 2>&1 || true
docker run --rm --name baryonrunner --privileged --cgroupns=host -p 8082:8082 ghcr.io/fairflow-bioinformaticsframework/baryon_gui:latest
