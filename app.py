from src.core.config import app, server  # noqa: F401
import src.core.auth  # noqa: F401 — registers /login, /logout, before_request
import src.core.pdf_endpoint  # noqa: F401 — registers /api/html-to-pdf
from src.layout.main_layout import serve_layout
import src.callbacks.filtros  # noqa: F401
import src.callbacks.sync  # noqa: F401
import src.callbacks.analytics  # noqa: F401
import src.callbacks.exports  # noqa: F401
import src.callbacks.resumen_exportacion  # noqa: F401
import src.callbacks.chat_callbacks      # noqa: F401
import src.callbacks.admin               # noqa: F401
import src.callbacks.estado_callbacks    # noqa: F401

app.layout = serve_layout

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=8051)
