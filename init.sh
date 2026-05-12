#!/usr/bin/env bash
# PatternSnap dev environment setup and startup
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== PatternSnap — Dev Environment Init ==="

# ── Backend ──────────────────────────────────────────────────────────────────
echo "[backend] Setting up Python environment..."
cd "$ROOT_DIR/backend"

if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

# Activate venv (works on both Unix and Git Bash on Windows)
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate

pip install -q --upgrade pip
pip install -q -r requirements.txt

# Copy .env if not present
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[backend] Created .env from .env.example — add your ANTHROPIC_API_KEY"
fi

echo "[backend] Starting FastAPI on http://localhost:8000 ..."
uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!

# ── Frontend ─────────────────────────────────────────────────────────────────
echo "[frontend] Installing npm dependencies..."
cd "$ROOT_DIR/frontend"

if [ ! -f ".env" ]; then
  cp .env.example .env 2>/dev/null || true
fi

npm install --silent

echo "[frontend] Starting Vite dev server on http://localhost:5173 ..."
npm run dev &
FRONTEND_PID=$!

# ── Health check ─────────────────────────────────────────────────────────────
echo ""
echo "Services starting:"
echo "  Backend:  http://localhost:8000/api/health"
echo "  Frontend: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop both servers."

# Wait for both processes; kill both on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait $BACKEND_PID $FRONTEND_PID
