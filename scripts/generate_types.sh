#!/usr/bin/env bash
# Regenerate Pydantic models from the pinned gp-schemas submodule.
# CI runs this and fails if the result differs from what's committed.
set -euo pipefail
cd "$(dirname "$0")/.."

datamodel-codegen \
  --input schemas/schemas \
  --input-file-type jsonschema \
  --output app/shared/schemas_generated \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --use-standard-collections \
  --use-union-operator \
  --disable-timestamp \
  --formatters builtin
