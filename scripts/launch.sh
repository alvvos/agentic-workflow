#!/usr/bin/env bash
# Lanza la app apuntando a la BD de producción vía túnel SSH.
#
# Uso:
#   ./scripts/launch.sh          → abre túnel, arranca app, queda en espera
#   Ctrl+C                       → para la app y cierra el túnel

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="/home/alvvos/.ssh/id_ed25519"
REMOTE_USER="alvaro.salis"
REMOTE_HOST="34.175.22.17"
LOCAL_PORT=5434
REMOTE_PORT=5432
APP_PORT=8051

TUNNEL_PID=""
APP_PID=""

cleanup() {
    echo ""
    echo "Parando..."
    [ -n "$APP_PID" ]    && kill "$APP_PID"    2>/dev/null || true
    [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$APP_PID"    2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    echo "Listo."
    exit 0
}
trap cleanup INT TERM

# ── Verificar puerto libre ────────────────────────────────────────────────────
if ss -tlnp 2>/dev/null | grep -q ":${LOCAL_PORT} "; then
    echo "Error: el puerto $LOCAL_PORT ya está en uso. Cámbialo en .env (DB_PORT)."
    exit 1
fi

# ── Abrir túnel SSH ───────────────────────────────────────────────────────────
echo "→ Abriendo túnel SSH: localhost:$LOCAL_PORT → $REMOTE_HOST:$REMOTE_PORT"
ssh -i "$SSH_KEY" \
    -L "${LOCAL_PORT}:localhost:${REMOTE_PORT}" \
    -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    "${REMOTE_USER}@${REMOTE_HOST}" &
TUNNEL_PID=$!

# Esperar a que el túnel esté listo
for i in $(seq 1 10); do
    sleep 1
    if ss -tlnp 2>/dev/null | grep -q ":${LOCAL_PORT} "; then
        echo "→ Túnel activo (PID $TUNNEL_PID)"
        break
    fi
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "Error: el túnel SSH no se pudo abrir."
        exit 1
    fi
done

# ── Matar instancia anterior de la app si existe ─────────────────────────────
fuser -k "${APP_PORT}/tcp" 2>/dev/null || true
sleep 1

# ── Arrancar app ─────────────────────────────────────────────────────────────
echo "→ Arrancando app en http://localhost:$APP_PORT"
cd "$REPO_ROOT"
source venv/bin/activate 2>/dev/null || true
python app.py &
APP_PID=$!

echo "→ App arrancada (PID $APP_PID)"
echo "  Ctrl+C para parar todo."
echo ""

# Mantener vivo hasta Ctrl+C
wait "$APP_PID"
