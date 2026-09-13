#!/usr/bin/env bash
# scripts/build_lambda.sh
set -euo pipefail

cd "$(dirname "$0")/.."

rm -rf build
mkdir -p build

pip install -r requirements.txt -t build/ --no-cache-dir
cp -r src/magicbooking_sync build/

echo "Lambda build artifact ready in build/"
