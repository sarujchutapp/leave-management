#!/usr/bin/env bash
# Build the Lambda deployment artifact. Run in WSL so the dependency wheels are
# Linux/x86_64 (matching the python3.12/x86_64 runtime), regardless of the host.
#
# Produces terraform/build/, which archive_file (main.tf) zips into leave-bot.zip
# and hashes for source_code_hash. boto3/moto/pytest are excluded (boto3 ships in
# the Lambda runtime; moto/pytest are test-only). service-account.json is never
# bundled — the Google credentials come from SSM at runtime.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/.." && pwd)"
build_dir="$here/build"

rm -rf "$build_dir"
mkdir -p "$build_dir"

# Runtime deps only. grep drops boto3, moto[dynamodb], and pytest.
req_file="$(mktemp)"
grep -vE '^(boto3|moto|pytest)' "$repo_root/requirements.txt" > "$req_file"

pip install \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --target "$build_dir" \
  -r "$req_file"

rm -f "$req_file"

# Application code.
cp "$repo_root/app.py" "$build_dir/"
cp "$repo_root/lambda_handler.py" "$build_dir/"
cp -r "$repo_root/leave" "$build_dir/"

# Drop bytecode caches so the zip hash is stable across builds.
find "$build_dir" -type d -name '__pycache__' -prune -exec rm -rf {} +

echo "Build complete: $build_dir"
echo "Next: terraform init && terraform apply (from WSL)."
