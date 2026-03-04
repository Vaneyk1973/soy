#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_SPEC="$ROOT_DIR/src/main/resources/openapi/openapi.yaml"
OUTPUT_FILE="$ROOT_DIR/generated/openapi_models.py"

mkdir -p "$(dirname "$OUTPUT_FILE")"

datamodel-codegen \
  --input "$INPUT_SPEC" \
  --input-file-type openapi \
  --output "$OUTPUT_FILE" \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --use-standard-collections

echo "Generated: $OUTPUT_FILE"
