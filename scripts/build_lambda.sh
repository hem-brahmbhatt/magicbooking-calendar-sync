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

echo "Lambda build artifact ready in build/"
