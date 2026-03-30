#!/bin/bash
# LiteLLM Proxy Starter for MoAI CG Mode
# Translates Claude Code API calls -> Gemini API
#
# Usage: bash .moai/start-litellm.sh
# Requires: GEMINI_API_KEY environment variable

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/litellm_config.yaml"
PYTHON="/c/Users/zuge3/AppData/Local/Programs/Python/Python311/python.exe"
LITELLM="/c/Users/zuge3/AppData/Local/Programs/Python/Python311/Scripts/litellm.exe"
PORT=4000

# Check GEMINI_API_KEY
if [ -z "$GEMINI_API_KEY" ]; then
    echo "ERROR: GEMINI_API_KEY environment variable is not set."
    echo "Set it with: export GEMINI_API_KEY='your-key-here'"
    exit 1
fi

# Fix Windows encoding
export PYTHONIOENCODING=utf-8

echo "========================================"
echo " MoAI CG Mode - LiteLLM Proxy"
echo " Gemini API -> Anthropic-compatible"
echo " Port: $PORT"
echo "========================================"
echo ""
echo "Claude Code teammates will use Gemini via this proxy."
echo "Press Ctrl+C to stop."
echo ""

$LITELLM --config "$CONFIG_FILE" --port $PORT --host 0.0.0.0
