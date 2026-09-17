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
from app.services.progress_service import week_bounds

stats_bp = Blueprint("stats", __name__)

_VALID_SCALES = ("day", "week", "month")
_VALID_SECTIONS = ("raw", "contexts", "timeline", "todo_water", "rewards", "analysis", "streaks")


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

    summary_scale = scale

    section = request.args.get("section", "raw")
    if section not in _VALID_SECTIONS:
        section = "raw"
    if scale != "day" and section == "timeline":
        # timeline cronológica só existe na granularidade do dia
        section = "raw"

    ref_date = _parse_date(request.args.get("date"))
    today = clock.today()
    if ref_date > today:
        ref_date = today

    current_day_data = history_service.get_day(ref_date)
    current_week_data = history_service.get_week(ref_date)
    current_month_data = history_service.get_month(ref_date)

    summary_data = {
        "day": current_day_data,
        "week": current_week_data,
        "month": current_month_data,
    }
    summary_comparisons = {
        "day": history_service.compare_days(history_service.previous_day(ref_date), ref_date),
        "week": history_service.compare_weeks(history_service.previous_week_ref(ref_date), ref_date),
        "month": history_service.compare_months(history_service.previous_month_ref(ref_date), ref_date),
    }
    summary_comparison = summary_comparisons[summary_scale]

    mode = request.args.get("mode", "cycles")
    if mode not in ("cycles", "minutes"):
        mode = "cycles"

    compare_mode = request.args.get("compare", "0") == "1"
    compare_date_str = request.args.get("compare_date")
    compare_date = None
    slot_comparison = None
    period_b_label = "Clique para escolher"
    active_slot = request.args.get("active_slot", "b" if ref_date else "a")
    
    period_a_data = None
    period_b_data = None

    # Normal single-period query (still needed for header comparison and Explorar mode details)
    if scale == "day":
        current = history_service.get_day(ref_date)
        comparison = history_service.compare_days(history_service.previous_day(ref_date), ref_date)
        prev_ref = history_service.previous_day(ref_date)
        next_ref = history_service.next_day(ref_date)
        period_label = ref_date.strftime("%d/%m/%Y")
        is_current_period = ref_date == today
        period_a_data = current
    elif scale == "week":
        current = history_service.get_week(ref_date)
        comparison = history_service.compare_weeks(history_service.previous_week_ref(ref_date), ref_date)
        prev_ref = history_service.previous_week_ref(ref_date)
        next_ref = history_service.next_week_ref(ref_date)
        period_label = f"{current['start_date']} — {current['end_date']}"
        is_current_period = date_.fromisoformat(current["start_date"]) <= today <= date_.fromisoformat(current["end_date"])
        period_a_data = current
    else:
        current = history_service.get_month(ref_date)
        comparison = history_service.compare_months(history_service.previous_month_ref(ref_date), ref_date)
        prev_ref = history_service.previous_month_ref(ref_date)
        next_ref = history_service.next_month_ref(ref_date)
        period_label = f"{current['start_date']} — {current['end_date']}"
        is_current_period = date_.fromisoformat(current["start_date"]) <= today <= date_.fromisoformat(current["end_date"])
        period_a_data = current

    # Compute header_comparison based on the selected period (ref_date)
    if scale == "day":
        header_comparison = history_service.compare_days(history_service.previous_day(ref_date), ref_date)
    elif scale == "week":
        header_comparison = history_service.compare_weeks(history_service.previous_week_ref(ref_date), ref_date)
    else:
        header_comparison = history_service.compare_months(history_service.previous_month_ref(ref_date), ref_date)

    # Handle comparison mode custom dates
    if compare_mode:
        if compare_date_str:
            try:
                compare_date = date_.fromisoformat(compare_date_str)
                if compare_date > today:
                    compare_date = today
            except ValueError:
                compare_date = None

        if compare_date:
            # Normalize: older_date → Period A (left), newer_date → Period B (right)
            if compare_date < ref_date:
                older_date, newer_date = compare_date, ref_date
            else:
                older_date, newer_date = ref_date, compare_date

            if scale == "day":
                slot_comparison = history_service.compare_days(older_date, newer_date)
            elif scale == "week":
                slot_comparison = history_service.compare_weeks(older_date, newer_date)
            else:
                slot_comparison = history_service.compare_months(older_date, newer_date)

            period_a_data = slot_comparison["a"]["raw"]
            period_b_data = slot_comparison["b"]["raw"]

            if scale == "day":
                period_a_label = older_date.strftime("%d/%m/%Y")
                period_b_label = newer_date.strftime("%d/%m/%Y")
            else:
                period_a_label = f"{period_a_data['start_date']} — {period_a_data['end_date']}"
                period_b_label = f"{period_b_data['start_date']} — {period_b_data['end_date']}"
        else:
            period_a_label = ref_date.strftime("%d/%m/%Y") if scale == "day" else period_label
    else:
        period_a_label = ref_date.strftime("%d/%m/%Y") if scale == "day" else period_label

    next_disabled = next_ref > today

    # Heatmap generation: always end up to todayalised week
    grid = history_service.calendar_heatmap(end=today, weeks=46, mode=mode)

    # Compute selection states and month labels
    ref_week_start, _ = week_bounds(ref_date)
    compare_week_start = None
    if compare_mode and compare_date:
        compare_week_start, _ = week_bounds(compare_date)

    month_labels = []
    current_month = None
    for week in grid:
        week_start_date = date_.fromisoformat(week[0]["date"])
        week_start, _ = week_bounds(week_start_date)
        
        # Month labels
        if week_start_date.month != current_month:
            month_abbrev = {
                1: "JAN", 2: "FEV", 3: "MAR", 4: "ABR", 5: "MAI", 6: "JUN",
                7: "JUL", 8: "AGO", 9: "SET", 10: "OUT", 11: "NOV", 12: "DEZ"
            }[week_start_date.month]
            month_labels.append(month_abbrev)
            current_month = week_start_date.month
        else:
            month_labels.append("")

        # Selection status for each cell in this week
        for day in week:
            day_date = date_.fromisoformat(day["date"])
            is_selected = False
            if scale == "day":
                is_selected = (day_date == ref_date or (compare_mode and compare_date and day_date == compare_date))
            elif scale == "week":
                is_selected = (week_start == ref_week_start or (compare_mode and compare_date and week_start == compare_week_start))
            elif scale == "month":
                is_selected = (
                    (day_date.year == ref_date.year and day_date.month == ref_date.month) or
                    (compare_mode and compare_date and day_date.year == compare_date.year and day_date.month == compare_date.month)
                )
            day["selected"] = is_selected

    global_analysis = history_service.get_global_analysis()
    period_analysis = history_service.get_period_analysis(scale, ref_date)

    return render_template(
        "stats.html",
        cfg=get_current_configuration(),
        scale=scale,
        summary_scale=summary_scale,
        section=section,
        ref_date=ref_date,
        period_label=period_label,
        is_current_period=is_current_period,
        current=current,
        comparison=comparison,
        header_comparison=header_comparison,
        prev_ref=prev_ref.isoformat(),
        next_ref=next_ref.isoformat(),
        next_disabled=next_disabled,
        today=today.isoformat(),
        summary_data=summary_data,
        summary_comparisons=summary_comparisons,
        summary_comparison=summary_comparison,
        
        # New context variables for heatmap and compare mode
        mode=mode,
        compare_mode=compare_mode,
        compare_date=compare_date,
        active_slot=active_slot,
        period_a_label=period_a_label,
        period_b_label=period_b_label,
        period_a_data=period_a_data,
        period_b_data=period_b_data,
        slot_comparison=slot_comparison,
        grid=grid,
        month_labels=month_labels,
        global_analysis=global_analysis,
        period_analysis=period_analysis
    )
