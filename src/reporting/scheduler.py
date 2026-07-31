"""
Scheduler de envío automático de informes PDF.
Usa APScheduler BackgroundScheduler dentro del proceso Gunicorn.
Inicializar llamando a start_scheduler() una sola vez desde app.py.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)

_scheduler = None


def _periodo_para_tipo(tipo: str, fecha_concreta: str | None) -> tuple[str, str, str]:
    """Returns (period_key, date_from, date_to) for a schedule type."""
    hoy = date.today()
    if tipo == "semanal":
        lunes = hoy - timedelta(days=hoy.weekday() + 7)
        return "semana", lunes.isoformat(), (lunes + timedelta(days=6)).isoformat()
    if tipo == "mensual":
        primer_dia = hoy.replace(day=1)
        fin_mes_ant = primer_dia - timedelta(days=1)
        return "mes", fin_mes_ant.replace(day=1).isoformat(), fin_mes_ant.isoformat()
    # fecha concreta → informe de la semana anterior a esa fecha
    d = date.fromisoformat(fecha_concreta) if fecha_concreta else hoy
    lunes = d - timedelta(days=d.weekday() + 7)
    return "semana", lunes.isoformat(), (lunes + timedelta(days=6)).isoformat()


def _run_schedules(tipo: str) -> None:
    hoy = date.today().isoformat()
    try:
        from src.core.data_master import mapa_tiendas
        from src.db.queries import get_active_schedules, mark_schedule_executed
        from src.reporting.email_sender import send_report_email
        from src.reporting.pdf_generator import _period_label, generar_pdf_informe

        schedules = get_active_schedules(tipo, fecha=hoy if tipo == "fecha" else None)
        log.info("Scheduler [%s]: %d programaciones activas", tipo, len(schedules))

        for s in schedules:
            try:
                loc_uuid = s["loc_uuid"]
                period_key, d_from, d_to = _periodo_para_tipo(
                    s["tipo_periodo"], s.get("fecha_concreta")
                )
                pdf_bytes = generar_pdf_informe(loc_uuid, period_key, d_from, d_to)
                loc_nombre = mapa_tiendas.get(loc_uuid, loc_uuid)
                period_lbl, *_ = _period_label(d_from, d_to, period_key)
                filename = f"informe_{loc_nombre.lower().replace(' ', '_')}_{d_from}_{d_to}.pdf"
                send_report_email(s["emails"], loc_nombre, period_lbl, pdf_bytes, filename)
                mark_schedule_executed(s["id"])
                log.info("Informe enviado: %s → %s", loc_nombre, s["emails"])
            except Exception:
                log.exception("Error enviando informe para loc_uuid=%s", s.get("loc_uuid"))
    except Exception:
        log.exception("Error en _run_schedules [%s]", tipo)


def _run_weekly() -> None:
    _run_schedules("semanal")


def _run_monthly() -> None:
    _run_schedules("mensual")


def _run_date_specific() -> None:
    _run_schedules("fecha")


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler(timezone="Europe/Madrid")
        # Lunes 08:00 — informes semanales
        _scheduler.add_job(
            _run_weekly, "cron", day_of_week="mon", hour=8, minute=0, id="weekly_reports"
        )
        # Día 1 de cada mes 08:00 — informes mensuales
        _scheduler.add_job(_run_monthly, "cron", day=1, hour=8, minute=0, id="monthly_reports")
        # Cada día 08:05 — fechas concretas (revisar si hay programación para hoy)
        _scheduler.add_job(_run_date_specific, "cron", hour=8, minute=5, id="date_reports")
        _scheduler.start()
        log.info("Scheduler de informes iniciado")
    except Exception:
        log.exception("No se pudo iniciar el scheduler de informes")
