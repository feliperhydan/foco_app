"""
Rota da página Estatísticas.

Fina de propósito: toda a lógica de leitura/comparação vive em
`app.services.history_service` (Camada 1 + recorte da Camada 2). Esta
rota só resolve os parâmetros de navegação (escala/data/seção) e
monta o contexto para o template.
"""
from datetime import date as date_

from flask import Blueprint, render_template, request

from app.services import clock, history_service
from app.services.config_service import get_current_configuration

stats_bp = Blueprint("stats", __name__)

_VALID_SCALES = ("day", "week", "month")
_VALID_SECTIONS = ("raw", "contexts", "timeline", "todo_water", "rewards")


def _parse_date(raw: str | None) -> date_:
    if raw:
        try:
            return date_.fromisoformat(raw)
        except ValueError:
            pass
    return clock.today()


@stats_bp.route("/estatisticas")
def stats():
    scale = request.args.get("scale", "day")
    if scale not in _VALID_SCALES:
        scale = "day"

    section = request.args.get("section", "raw")
    if section not in _VALID_SECTIONS:
        section = "raw"
    if scale != "day" and section == "timeline":
        # timeline cronológica só existe na granularidade do dia (seção 10)
        section = "raw"

    ref_date = _parse_date(request.args.get("date"))
    today = clock.today()
    if ref_date > today:
        ref_date = today

    if scale == "day":
        current = history_service.get_day(ref_date)
        comparison = history_service.compare_days(history_service.previous_day(ref_date), ref_date)
        prev_ref = history_service.previous_day(ref_date)
        next_ref = history_service.next_day(ref_date)
        period_label = ref_date.strftime("%d/%m/%Y")
        is_current_period = ref_date == today
    elif scale == "week":
        current = history_service.get_week(ref_date)
        comparison = history_service.compare_weeks(history_service.previous_week_ref(ref_date), ref_date)
        prev_ref = history_service.previous_week_ref(ref_date)
        next_ref = history_service.next_week_ref(ref_date)
        period_label = f"{current['start_date']} — {current['end_date']}"
        is_current_period = date_.fromisoformat(current["start_date"]) <= today <= date_.fromisoformat(current["end_date"])
    else:
        current = history_service.get_month(ref_date)
        comparison = history_service.compare_months(history_service.previous_month_ref(ref_date), ref_date)
        prev_ref = history_service.previous_month_ref(ref_date)
        next_ref = history_service.next_month_ref(ref_date)
        period_label = f"{current['start_date']} — {current['end_date']}"
        is_current_period = date_.fromisoformat(current["start_date"]) <= today <= date_.fromisoformat(current["end_date"])

    next_disabled = next_ref > today

    return render_template(
        "stats.html",
        cfg=get_current_configuration(),
        scale=scale,
        section=section,
        ref_date=ref_date,
        period_label=period_label,
        is_current_period=is_current_period,
        current=current,
        comparison=comparison,
        prev_ref=prev_ref.isoformat(),
        next_ref=next_ref.isoformat(),
        next_disabled=next_disabled,
        today=today.isoformat(),
    )
