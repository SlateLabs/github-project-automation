#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
SCHEMA=".github/schemas/orchestration-contract-v1.json"

python3 - "$SCHEMA" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    schema = json.load(fh)

defs = schema.get("$defs", {})
checkpoint = defs.get("checkpointEnvelope", {})
artifact = defs.get("artifactPayloadEnvelope", {})
status_enum = defs.get("stageStatus", {}).get("enum", [])

assert checkpoint.get("properties", {}).get("kind", {}).get("const") == "checkpoint"
assert artifact.get("properties", {}).get("kind", {}).get("const") == "artifact_payload"
assert checkpoint.get("properties", {}).get("version", {}).get("const") == "gpa.v1"
assert artifact.get("properties", {}).get("version", {}).get("const") == "gpa.v1"
assert set(status_enum) == {"started", "completed", "failed", "blocked", "waiting", "skipped"}

checkpoint_required = set(checkpoint.get("required", []))
artifact_required = set(artifact.get("required", []))
assert {"kind", "version", "run_key", "stage", "decision"} <= checkpoint_required
assert {"kind", "version", "stage", "data"} <= artifact_required

print("orchestration contract schema looks valid")
PY
