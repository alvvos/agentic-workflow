#!/usr/bin/env bash
# Conecta la app local a la base de datos de producción vía túnel SSH.
#
# Uso:
#   ./scripts/db-prod.sh          → abre túnel, parchea .env, queda en espera
#   Ctrl+C                        → cierra túnel y restaura .env automáticamente
#
# Qué hace:
#   1. Abre localhost:5433 → 34.175.22.17:5432 (PostgreSQL en prod) vía SSH
#   2. Parchea DB_PORT=5433 en .env para que la app lo recoja al reiniciar
#   3. Al salir restaura DB_PORT=5432

set -euo pipefail

ENV_FILE="$(dirname "$0")/../.env"
SSH_KEY="$HOME/.ssh/id_ed25519_servidor"
REMOTE_USER="alvaro.salis"
REMOTE_HOST="34.175.22.17"
LOCAL_PORT=5433
REMOTE_PORT=5432

# ── Limpieza al salir ──────────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo "Cerrando túnel y restaurando .env..."
    kill "$TUNNEL_PID" 2>/dev/null || true
    # Restaurar DB_PORT a 5432
    sed -i "s/^DB_PORT=.*/DB_PORT=5432/" "$ENV_FILE"
    echo "Listo. La app vuelve a apuntar a la BD local."
    exit 0
}
trap cleanup INT TERM

# ── Verificar que no hay túnel previo en ese puerto ───────────────────────────
if ss -tlnp 2>/dev/null | grep -q ":${LOCAL_PORT} "; then
    echo "El puerto $LOCAL_PORT ya está en uso. Ciérralo antes de continuar."
    exit 1
fi

# ── Parchar .env ──────────────────────────────────────────────────────────────
sed -i "s/^DB_PORT=.*/DB_PORT=$LOCAL_PORT/" "$ENV_FILE"
echo "  .env actualizado: DB_PORT=$LOCAL_PORT"

# ── Abrir túnel ───────────────────────────────────────────────────────────────
echo "  Abriendo túnel SSH: localhost:$LOCAL_PORT → $REMOTE_HOST:$REMOTE_PORT"
ssh -i "$SSH_KEY" \
    -L "${LOCAL_PORT}:localhost:${REMOTE_PORT}" \
    -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    "${REMOTE_USER}@${REMOTE_HOST}" &
TUNNEL_PID=$!

# Esperar a que el túnel esté listo
sleep 2
if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "Error: el túnel SSH no se pudo abrir."
    sed -i "s/^DB_PORT=.*/DB_PORT=5432/" "$ENV_FILE"
    exit 1
fi

echo ""
echo "  Túnel activo (PID $TUNNEL_PID)"
echo "  La app ahora apunta a la BD de producción."
echo "  Reinicia el servidor local para que tome el cambio:"
echo ""
echo "    fuser -k 8051/tcp && venv/bin/python app.py"
echo ""
echo "  Pulsa Ctrl+C para cerrar el túnel y volver a la BD local."
echo ""

# Mantener el script vivo
wait "$TUNNEL_PID"
