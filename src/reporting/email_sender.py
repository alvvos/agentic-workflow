"""
Envío de informes PDF por email vía Resend.
Requiere RESEND_API_KEY y opcionalmente REPORT_FROM_EMAIL en el entorno.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def send_report_email(
    to_emails: list[str],
    loc_nombre: str,
    period_label: str,
    pdf_bytes: bytes,
    filename: str,
) -> None:
    import resend

    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY no configurada en el entorno")

    resend.api_key = api_key
    from_email = os.environ.get("REPORT_FROM_EMAIL", "informes@69summer.com")

    body_html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto">
      <h2 style="color:#1a1a1a">Informe de afluencia</h2>
      <p><strong>{loc_nombre}</strong> &mdash; {period_label}</p>
      <p style="color:#555">Adjunto encontrarás el informe PDF generado automáticamente
      con el análisis de tráfico, zonas y señales externas del período.</p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="font-size:0.8rem;color:#999">Generado por Agentic Workflow &middot;
      Para cambiar la frecuencia o cancelar el envío, accede al panel de Informes.</p>
    </div>
    """

    params: resend.Emails.SendParams = {
        "from": from_email,
        "to": to_emails,
        "subject": f"Informe {loc_nombre} — {period_label}",
        "html": body_html,
        "attachments": [
            {
                "filename": filename,
                "content": list(pdf_bytes),
            }
        ],
    }
    result = resend.Emails.send(params)
    log.info("Email enviado a %s — id=%s", to_emails, result.get("id"))
