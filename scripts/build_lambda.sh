#!/usr/bin/env bash
# scripts/build_lambda.sh
set -euo pipefail

cd "$(dirname "$0")/.."

rm -rf build
mkdir -p build

pip install -r requirements.txt -t build/ --no-cache-dir \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --abi cp312 \
    --only-binary=:all:
cp -r src/magicbooking_sync build/

# Smoke test: verify the packaged artifact can actually import the handler
# module (and therefore all its dependencies) before it gets zipped and
# deployed. This is the exact class of bug that let a missing `requests`
# dependency ship to production undetected.
#
# The package above is deliberately cross-built for Linux/x86_64/cp312
# (AWS Lambda's python3.12 runtime), which is usually NOT the host
# platform (e.g. this repo is developed on macOS arm64) — native
# extensions in that build (cryptography, cffi, lxml) cannot be dlopen'd
# by a local, differently-platformed Python interpreter. So the smoke
# test runs inside the actual AWS Lambda Python 3.12 base image via
# Docker, which matches the real deploy target exactly, rather than
# trying (and necessarily failing) to import cross-built binaries with
# the host's own Python. If Docker isn't available, this step is skipped
# with a warning rather than failing the whole build — but that means
# this particular safety net doesn't run, so prefer running this in an
# environment with Docker (or in CI) before deploying.
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker run --rm --platform linux/amd64 \
        --entrypoint python3 \
        -w /var/task \
        -v "$(pwd)/build:/var/task:ro" \
        public.ecr.aws/lambda/python:3.12 \
        -c "import magicbooking_sync.handler"
    echo "Smoke test passed: handler module imports cleanly under the real Lambda runtime (via Docker)."
else
    echo "WARNING: Docker not available — skipping the Lambda-runtime import smoke test." >&2
    echo "         Run this script where Docker is available before deploying, to catch" >&2
    echo "         missing/broken dependencies before they reach production." >&2
fi

echo "Lambda build artifact ready in build/"
