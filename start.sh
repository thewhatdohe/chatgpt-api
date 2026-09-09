#!/usr/bin/env bash
# Starts the local chat stack:
#   your codex-oauth bridge (:10531)  <-  shim (:5100)  <-  LobeChat UI (:3210)
# The shim exists because off-the-shelf UIs default to model ids the bridge
# does not serve; it rewrites those to a real model. See app.py.
set -uo pipefail
cd "$(dirname "$0")"

BRIDGE=http://0.0.0.0:10531/v1
SHIM_LOG=/tmp/chat-shim.log

if ! curl -sf -o /dev/null --max-time 5 "$BRIDGE/models"; then
  echo "!! bridge not answering at $BRIDGE - start it first"
  exit 1
fi
echo "ok  bridge   :10531"

if curl -sf -o /dev/null --max-time 5 http://0.0.0.0:5100/v1/models; then
  echo "ok  shim     :5100 (already running)"
else
  VISION_API_KEY="${VISION_API_KEY:-}" nohup python3 app.py > "$SHIM_LOG" 2>&1 &
  for _ in $(seq 25); do
    curl -sf -o /dev/null --max-time 2 http://0.0.0.0:5100/v1/models && break
    sleep 1
  done
  echo "ok  shim     :5100 (started, log: $SHIM_LOG)"
fi

if [ "$(podman inspect -f '{{.State.Running}}' lobe-chat 2>/dev/null)" != "true" ]; then
  podman start lobe-chat >/dev/null 2>&1 && echo "ok  lobechat :3210 (started)" \
    || { echo "!! container 'lobe-chat' missing - see README-chat.md"; exit 1; }
else
  echo "ok  lobechat :3210 (already running)"
fi

echo
echo "open http://0.0.0.0:3210"
