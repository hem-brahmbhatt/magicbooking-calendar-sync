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
( cd build && python3 -c "import magicbooking_sync.handler" )

echo "Lambda build artifact ready in build/"
