#!/usr/bin/env bash
# Real-LLM smoke verification against a local Ollama model (no API keys).
#
# Runs the full Docker stack with the agents pointed at the HOST's Ollama
# (Metal-accelerated on macOS), then executes the real-LLM smoke tests.
#
# Usage:
#   ./scripts/smoke_local_llm.sh                 # default model (llama3.1:8b)
#   LOCAL_OLLAMA_MODEL=mistral-nemo ./scripts/smoke_local_llm.sh
#   LOCAL_SMALL_OLLAMA_MODEL=qwen3:1.7b ./scripts/smoke_local_llm.sh   # Meta-Agent on its own model
#   ./scripts/smoke_local_llm.sh --keep          # leave the stack running
#
# Default is llama3.1:8b: it reliably emits structured tool calls under a
# multi-tool prompt and has no "thinking" phase, so turns stay under the 120s
# client timeout. Qwen3.5 degrades to raw-JSON-text tool calls; qwen3:8b's
# <think> blocks can blow the per-turn timeout on modest (16GB) hardware.

set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/smoke_common.sh

MODEL="${LOCAL_OLLAMA_MODEL:-llama3.1:8b}"
unset CLOUD_MODEL_NAME  # the smoke tests take the model from whichever name is set
export LOCAL_MODEL_NAME="ollama_chat/${MODEL}"
# The Meta-Agent (mode switching) model, passed to the agents as DAK_SMALL_MODEL.
# Empty = the main model. Exported even when empty, so it overrides a stale value
# in the caller's environment or in .env. DAK_SMALL_MODEL is for the smoke tests' messages.
SMALL_MODEL="${LOCAL_SMALL_OLLAMA_MODEL:-}"
export LOCAL_SMALL_MODEL_NAME="${SMALL_MODEL:+ollama_chat/${SMALL_MODEL}}"
export DAK_SMALL_MODEL="${LOCAL_SMALL_MODEL_NAME}"
COMPOSE=(env "COMPOSE_FILE=$(./scripts/compose_files.sh test):docker-compose.local-llm.yml" docker compose -p "${DAK_SMOKE_COMPOSE_PROJECT:-dak-ollama-smoke}")
KEEP="${1:-}"

echo "==> Checking host Ollama..."
if ! curl -sf --max-time 3 http://localhost:11434/api/version > /dev/null; then
    echo "Ollama is not running on the host. Start it first (e.g. 'ollama serve' or the menu-bar app)." >&2
    exit 1
fi

for m in "${MODEL}" ${SMALL_MODEL:+"${SMALL_MODEL}"}; do
    if ! ollama list | awk '{print $1}' | grep -qx "${m}"; then
        echo "==> Pulling ${m}..."
        ollama pull "${m}"
    fi
done

for m in "${MODEL}" ${SMALL_MODEL:+"${SMALL_MODEL}"}; do
    echo "==> Warming up ${m} (loads weights into memory)..."
    curl -sf http://localhost:11434/api/generate \
        -d "{\"model\": \"${m}\", \"prompt\": \"hi\", \"stream\": false}" > /dev/null
done

echo "==> Model: ${LOCAL_MODEL_NAME}"
echo "==> Meta-Agent model: ${LOCAL_SMALL_MODEL_NAME:-(the main model)}"
run_smoke_stack "${KEEP}" "${COMPOSE[@]}"
