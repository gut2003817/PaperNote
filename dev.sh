#!/usr/bin/env bash
# 一鍵啟動 Paper Notes：後端 http://127.0.0.1:8000、前端 http://localhost:5173
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
trap 'kill 0' EXIT
(cd "$ROOT/backend" && .venv/bin/uvicorn paper_notes.main:app --port 8000) &
(cd "$ROOT/frontend" && npx vite --port 5173) &
sleep 2 && open "http://localhost:5173" || true
wait
