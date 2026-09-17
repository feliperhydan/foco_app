from flask import Blueprint, abort, jsonify, request

from app.services import cycles_service, engine, water_service, progress_service, calendar_service, todo_service
from app.services.config_service import get_current_configuration, update_configuration, debug_tools_enabled
from app.services.clock import today
from app.services.debug_service import (
    advance_time,
    clear_database_data,
    clear_generated_test_data,
    complete_session,
    reset_cycle_progress,
    reset_time,
    simulate_cycles,
    complete_day_goal,
    jump_to_next_week,
    generate_test_data,
)


api_bp = Blueprint("api", __name__, url_prefix="/api")


PAUSE_MESSAGES = [
    # Nomes reais no disco divergem do prompt:
    #   prompt diz "janela.gif" → real: "JANELAGIF.gif"
    #   prompt diz "cel.gif"    → real: "CELGIF.gif"
    #   prompt diz "garrafa.gif"→ real: "GARRAFAGIF.gif"
    #   prompt diz "gato.gif"   → real: "GIFGATO.gif"
    #   prompt diz "ampulheta.gif" → real: "AMPULHETAGIF.gif"
    {
        "id": "janela",
        "mensagem": "Olhe para longe",
        "gif_url": "/GIFs/JANELAGIF.gif",
        "elegibilidade": "ambas",
    },
    {
        "id": "cel",
        "mensagem": "Cheque as mensagens da namorada",
        "gif_url": "/GIFs/CELGIF.gif",
        "elegibilidade": "longa",
    },
    {
        "id": "garrafa",
        "mensagem": "Encha a garrafa de água",
        "gif_url": "/GIFs/GARRAFAGIF.gif",
        "elegibilidade": "ambas",
    },
    {
        "id": "gato",
        "mensagem": "Alongue-se",
        "gif_url": "/GIFs/GIFGATO.gif",
        "elegibilidade": "ambas",
    },
    {
        "id": "ampulheta",
        "mensagem": "Só pare um pouco",
        "gif_url": "/GIFs/AMPULHETAGIF.gif",
        "elegibilidade": "ambas",
    },
]




def _todo_payload(item):
    return {"id": item.id, "text": item.text, "done": item.done, "order": item.order}


def _home_state_payload():
    current_day = today()
    daily_min = progress_service.get_daily_minimum_snapshot(current_day)
    daily_ideal = progress_service.get_daily_ideal_snapshot(current_day)
    extra = progress_service.get_extraordinary_snapshot(current_day)
    weekly = progress_service.get_weekly_snapshot(current_day)
    absolute = progress_service.get_active_absolute()
    water = water_service.daily_summary(current_day)

    from app.models import Reward
    active_min = Reward.query.filter_by(progress_type='daily_minimum', active=True).first()
    active_ideal = Reward.query.filter_by(progress_type='daily_ideal', active=True).first()
    active_weekly = Reward.query.filter_by(progress_type='weekly', active=True).first()

    cfg_curr = get_current_configuration()
    return {
        "cfg": {
            "auto_start_focus": cfg_curr.auto_start_focus,
            "auto_start_break": cfg_curr.auto_start_break,
            "post_cycle_messages_enabled": cfg_curr.post_cycle_messages_enabled,
            "volume_system": getattr(cfg_curr, "volume_system", 100),
            "volume_focus_end": getattr(cfg_curr, "volume_focus_end", 100),
            "volume_rest_end": getattr(cfg_curr, "volume_rest_end", 100),
            "sound_focus_end": getattr(cfg_curr, "sound_focus_end", "/static/sounds/fim_de_foco.mp3"),
            "sound_conclude_btn": getattr(cfg_curr, "sound_conclude_btn", "/static/sounds/do_pos_conclusao.mp3"),
            "sound_rest_end": getattr(cfg_curr, "sound_rest_end", "/static/sounds/fim_de_descanso.mp3"),
        },
        "daily_minimum": {
            "current": daily_min.current_count, "goal": daily_min.goal, "pct": daily_min.pct,
            "title": active_min.title if active_min else ""
        },
        "daily_ideal": {
            "current": daily_ideal.current_count, "goal": daily_ideal.goal, "pct": daily_ideal.pct,
            "title": active_ideal.title if active_ideal else ""
        },
        "extraordinary": (
            {
                "cycles": extra.extra_cycles,
                "minutes": extra.extra_minutes,
                "next_discount_pct": progress_service.get_or_create_next_discount(extra) or 0,
                "next_base_minutes": get_current_configuration().focus_minutes,
                "next_effective_minutes": round(get_current_configuration().focus_minutes * (1 - (progress_service.get_or_create_next_discount(extra) or 0) / 100)),
            }
            if extra else None
        ),
        "weekly": {
            "current": weekly.current_count, "goal": weekly.goal, "pct": weekly.pct,
            "title": active_weekly.title if active_weekly else ""
        },
        "absolute": (
            {
                "title": absolute.title, "current": absolute.current_count,
                "goal": absolute.goal_cycles,
                "pct": min(100, round(100 * absolute.current_count / absolute.goal_cycles)),
            }
            if absolute else None
        ),
        "water": water,
    }


@api_bp.route("/home-state")
def home_state():
    return jsonify(_home_state_payload())


@api_bp.route("/cycles/start", methods=["POST"])
def start_cycle():
    current_day = today()
    daily_ideal = progress_service.get_daily_ideal_snapshot(current_day)
    extra = progress_service.get_extraordinary_snapshot(current_day)

    discount_pct = None
    is_extraordinary = daily_ideal.status == "completed"
    if is_extraordinary:
        if extra:
            discount_pct = progress_service.get_or_create_next_discount(extra)
        else:
            discount_pct = progress_service.draw_extraordinary_discount(0)

    cycle = cycles_service.start_focus_cycle(discount_pct=discount_pct)
    base_minutes = get_current_configuration().focus_minutes

    return jsonify({
        "cycle_id": cycle.id,
        "focus_duration_minutes": cycle.focus_duration_minutes,
        "started_at": cycle.started_at.isoformat(),
        "is_extraordinary": is_extraordinary,
        "discount_pct": discount_pct or 0,
        "base_duration_minutes": base_minutes,
    })




@api_bp.route("/cycles/<int:cycle_id>/complete", methods=["POST"])
def complete_cycle(cycle_id):
    title = (request.get_json(silent=True) or {}).get("title")
    result = engine.complete_focus_cycle(cycle_id, title=title)
    result["home_state"] = _home_state_payload()
    return jsonify(result)


@api_bp.route("/cycles/<int:cycle_id>/abandon", methods=["POST"])
def abandon_cycle(cycle_id):
    cycle = cycles_service.abandon_focus_cycle(cycle_id)
    return jsonify({"ok": cycle is not None, "status": cycle.status if cycle else None})


@api_bp.route("/rest/start", methods=["POST"])
def start_rest():
    import random

    payload = request.get_json(silent=True) or {}
    kind = payload.get("kind", "short")
    last_message_id = payload.get("last_message_id")
    water_alert = payload.get("water_alert", False)

    rest = cycles_service.start_rest_cycle(kind)

    # 1) Se alerta hídrico ativo, forçar mensagem "Beba água" (mesmo GIF da garrafa)
    if water_alert:
        chosen_msg = {
            "id": "garrafa",
            "mensagem": "Beba água",
            "gif_url": "/GIFs/GARRAFAGIF.gif",
        }
    else:
        # Filter eligible pause messages
        eligible = []
        for msg in PAUSE_MESSAGES:
            el = msg["elegibilidade"]
            if el == "ambas" or (kind == "short" and el == "curta") or (kind == "long" and el == "longa"):
                eligible.append(msg)

        # Avoid repeating the same message twice in a row if possible
        choices = [m for m in eligible if m["id"] != last_message_id]
        if not choices:
            choices = eligible

        # Pausa longa: 80% de chance de "Cheque as mensagens da namorada"
        if kind == "long":
            cel_msg = next((m for m in choices if m["id"] == "cel"), None)
            other_choices = [m for m in choices if m["id"] != "cel"]
            if cel_msg and random.random() < 0.80:
                chosen_msg = cel_msg
            elif other_choices:
                chosen_msg = random.choice(other_choices)
            elif cel_msg:
                chosen_msg = cel_msg  # fallback: só restou cel
            else:
                chosen_msg = random.choice(choices)
        else:
            chosen_msg = random.choice(choices)


    # 3) Progress calculation for the legend — use service snapshots for consistency
    current_day = today()
    daily_min = progress_service.get_daily_minimum_snapshot(current_day)
    daily_ideal = progress_service.get_daily_ideal_snapshot(current_day)
    extra = progress_service.get_extraordinary_snapshot(current_day)

    completed_today = daily_min.current_count  # total focus cycles completed today
    min_goal = daily_min.goal
    ideal_goal = daily_ideal.goal

    # Format legend and state per PDF page 6 semantics:
    # State 1: minimum not yet reached (completed < min_goal)
    # State 2: minimum reached, heading to ideal (min_goal <= completed < ideal_goal)
    # State 3: ideal already reached — extraordinary cycles (+W)
    legend_text = ""
    legend_state = 1
    if completed_today >= ideal_goal:
        # Ideal reached or exceeded — show extraordinary count
        extra_cycles = completed_today - ideal_goal
        label = "ciclo" if extra_cycles == 1 else "ciclos"
        legend_text = f"Fim do ciclo {completed_today} de foco · +{extra_cycles} {label} do ideal"
        legend_state = 3
    elif completed_today >= min_goal:
        # Minimum reached, heading to ideal
        needed_ideal = ideal_goal - completed_today
        label = "ciclo" if needed_ideal == 1 else "ciclos"
        legend_text = f"Fim do ciclo {completed_today} de foco · {needed_ideal} {label} do ideal"
        legend_state = 2
    else:
        # Still working toward minimum
        needed_min = min_goal - completed_today
        label = "ciclo" if needed_min == 1 else "ciclos"
        legend_text = f"Fim do ciclo {completed_today} de foco · {needed_min} {label} da média"
        legend_state = 1

    return jsonify({
        "rest_id": rest.id,
        "kind": rest.kind,
        "duration_minutes": rest.duration_minutes,
        "pause_message": chosen_msg,
        "legend_text": legend_text,
        "legend_state": legend_state
    })


@api_bp.route("/rest/<int:rest_id>/complete", methods=["POST"])
def complete_rest(rest_id):
    rest = cycles_service.complete_rest_cycle(rest_id)
    return jsonify({"ok": rest is not None})


@api_bp.route("/rest/<int:rest_id>/abandon", methods=["POST"])
def abandon_rest(rest_id):
    rest = cycles_service.abandon_rest_cycle(rest_id)
    return jsonify({"ok": rest is not None})


@api_bp.route("/water/log", methods=["POST"])
def log_water():
    water_service.log_bottle()
    return jsonify(water_service.daily_summary(today()))


@api_bp.route("/calendar")
def calendar():
    mode = request.args.get("mode", "cycles")
    weeks = int(request.args.get("weeks", 18))
    if mode not in ("cycles", "minutes"):
        mode = "cycles"
    grid = calendar_service.heatmap_grid(weeks=weeks, mode=mode)
    return jsonify({"mode": mode, "weeks": weeks, "grid": grid})


@api_bp.route("/stats/calendar")
def stats_calendar():
    from app.services.history_service import calendar_heatmap
    from datetime import date as date_
    
    mode = request.args.get("mode", "cycles")
    if mode not in ("cycles", "minutes"):
        mode = "cycles"
        
    try:
        weeks = int(request.args.get("weeks", 46))
    except (TypeError, ValueError):
        weeks = 46
        
    end_str = request.args.get("end")
    if end_str:
        try:
            end_date = date_.fromisoformat(end_str)
        except ValueError:
            end_date = today()
    else:
        end_date = today()
        
    grid = calendar_heatmap(end=end_date, weeks=weeks, mode=mode)
    return jsonify({
        "mode": mode,
        "weeks": weeks,
        "grid": grid
    })



@api_bp.route("/todos")
def todos():
    items = todo_service.list_items()
    return jsonify({
        "items": [_todo_payload(item) for item in items],
        "can_add_more": todo_service.can_add_more(),
    })


@api_bp.route("/todos", methods=["POST"])
def create_todo():
    payload = request.get_json(silent=True) or {}
    item = todo_service.create_item(payload.get("text", ""))
    if item is None:
        return jsonify({"ok": False, "error": "limite atingido"})
    return jsonify({"ok": True, "item": _todo_payload(item)})


@api_bp.route("/todos/<int:item_id>", methods=["PATCH"])
def update_todo(item_id):
    payload = request.get_json(silent=True) or {}
    item = None

    if "text" in payload:
        item = todo_service.update_item_text(item_id, payload.get("text", ""))
        if item is None:
            return jsonify({"ok": False, "error": "item nao encontrado"})

    if "done" in payload:
        if item is None:
            items = [candidate for candidate in todo_service.list_items() if candidate.id == item_id]
            item = items[0] if items else None
        if item is None:
            return jsonify({"ok": False, "error": "item nao encontrado"})
        requested_done = bool(payload.get("done"))
        if item.done != requested_done:
            item = todo_service.toggle_item(item_id)

    if item is None:
        return jsonify({"ok": False, "error": "nada para atualizar"})
    return jsonify({"ok": True, "item": _todo_payload(item)})


@api_bp.route("/todos/<int:item_id>", methods=["DELETE"])
def delete_todo(item_id):
    todo_service.delete_item(item_id)
    return jsonify({"ok": True})


@api_bp.route("/theme", methods=["POST"])
def toggle_theme():
    cfg = get_current_configuration()
    new_theme = "light" if cfg.theme == "dark" else "dark"
    update_configuration(theme=new_theme)
    return jsonify({"theme": new_theme})


def _debug_enabled():
    return debug_tools_enabled()


@api_bp.route("/debug/time/advance", methods=["POST"])
def debug_advance_time():
    if not _debug_enabled():
        abort(404)
    payload = request.get_json(silent=True) or {}
    try:
        days = int(payload.get("days", 1))
    except (TypeError, ValueError):
        days = 1
    days = max(-365, min(365, days))
    state = advance_time(days)
    return jsonify({
        "ok": True,
        "offset_days": state["offset_days"],
        "today": state["today"].isoformat(),
    })


@api_bp.route("/debug/time/reset", methods=["POST"])
def debug_reset_time():
    if not _debug_enabled():
        abort(404)
    state = reset_time()
    return jsonify({
        "ok": True,
        "offset_days": state["offset_days"],
        "today": state["today"].isoformat(),
    })


@api_bp.route("/debug/extraordinary/draw", methods=["POST"])
def debug_draw_extraordinary():
    if not _debug_enabled():
        abort(404)
    payload = request.get_json(silent=True) or {}
    try:
        extra_so_far = int(payload.get("extra_cycles_so_far", 0))
    except (TypeError, ValueError):
        extra_so_far = 0
    extra_so_far = max(0, extra_so_far)

    discount_pct = progress_service.draw_extraordinary_discount(extra_so_far)

    # Probabilidades exatas para auditoria
    if extra_so_far == 0:
        prob_map = {50: 30, 40: 40, 30: 20, None: 10}
    else:
        prob_map = {50: 20, 40: 35, 30: 20, None: 25}

    chance_pct = prob_map.get(discount_pct, 0)
    base_minutes = get_current_configuration().focus_minutes
    discount_val = discount_pct or 0
    effective_minutes = round(base_minutes * (1 - discount_val / 100))

    return jsonify({
        "ok": True,
        "extra_cycle_number": extra_so_far + 1,
        "discount_pct": discount_val,
        "chance_pct": chance_pct,
        "base_minutes": base_minutes,
        "effective_minutes": effective_minutes,
    })


@api_bp.route("/debug/cycles/simulate", methods=["POST"])
def debug_simulate_cycles():
    if not _debug_enabled():
        abort(404)
    payload = request.get_json(silent=True) or {}
    try:
        count = int(payload.get("count", 1))
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(50, count))
    title = (payload.get("title") or "Debug cycle").strip()[:280]
    result = simulate_cycles(count=count, title=title)

    return jsonify({
        "ok": True,
        "count": result["count"],
        "today": result["today"].isoformat(),
        "last_result": result["last_result"],
        "home_state": _home_state_payload(),
    })


@api_bp.route("/debug/progress/reset", methods=["POST"])
def debug_reset_cycle_progress():
    if not _debug_enabled():
        abort(404)
    result = reset_cycle_progress()
    return jsonify({
        "ok": True,
        "today": result["today"].isoformat(),
        "daily_minimum_reset": result["daily_minimum"],
        "daily_ideal_reset": result["daily_ideal"],
        "weekly_reset": result["weekly"],
        "extraordinary_deleted": result["extraordinary_deleted"],
        "absolute_reset": result["absolute_reset"],
        "home_state": _home_state_payload(),
    })


@api_bp.route("/debug/session/complete", methods=["POST"])
def debug_complete_session():
    if not _debug_enabled():
        abort(404)
    result = complete_session()
    return jsonify({
        "ok": result["ok"],
        "session_id": result["session_id"],
        "today": result["today"].isoformat(),
        "cycles_per_session": result.get("cycles_per_session"),
        "completed_cycles_before": result.get("completed_cycles_before"),
        "completed_cycles_after": result.get("completed_cycles_after"),
        "remaining_cycles": result.get("remaining_cycles"),
        "session_ended": result.get("session_ended", False),
        "last_result": result.get("last_result"),
        "post_cycle_message": result.get("post_cycle_message", ""),
        "home_state": _home_state_payload(),
    })


@api_bp.route("/debug/day/complete", methods=["POST"])
def debug_complete_day():
    if not _debug_enabled():
        abort(404)
    payload = request.get_json(silent=True) or {}
    target = payload.get("target", "ideal")
    if target not in ("minimum", "ideal"):
        target = "ideal"
    result = complete_day_goal(target=target)
    return jsonify({
        "ok": True,
        "target": result["target"],
        "goal": result["goal"],
        "current": result["current"],
        "needed": result["needed"],
        "today": result["today"].isoformat(),
        "result": result["result"],
        "home_state": _home_state_payload(),
    })


@api_bp.route("/debug/week/next", methods=["POST"])
def debug_next_week():
    if not _debug_enabled():
        abort(404)
    result = jump_to_next_week()
    return jsonify({
        "ok": True,
        "offset_days": result["offset_days"],
        "days_advanced": result["days_advanced"],
        "today": result["today"].isoformat(),
    })


@api_bp.route("/debug/data/generate", methods=["POST"])
def debug_generate_data():
    if not _debug_enabled():
        abort(404)
    payload = request.get_json(silent=True) or {}
    try:
        days = int(payload.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    try:
        cycles_per_day = int(payload.get("cycles_per_day", 3))
    except (TypeError, ValueError):
        cycles_per_day = 3
    try:
        water_per_day = int(payload.get("water_per_day", 2))
    except (TypeError, ValueError):
        water_per_day = 2
    result = generate_test_data(days=days, cycles_per_day=cycles_per_day, water_per_day=water_per_day)
    return jsonify({
        "ok": True,
        "days": result["days"],
        "cycles_per_day": result["cycles_per_day"],
        "water_per_day": result["water_per_day"],
        "start_day": result["start_day"].isoformat(),
        "end_day": result["end_day"].isoformat(),
        "home_state": _home_state_payload(),
    })


@api_bp.route("/debug/data/clear-generated", methods=["POST"])
def debug_clear_generated_data():
    if not _debug_enabled():
        abort(404)
    result = clear_generated_test_data()
    return jsonify({
        "ok": True,
        "cleared": result.get("cleared", False),
        "range": result.get("range"),
        "weeks": result.get("weeks"),
        "months": result.get("months"),
    })


@api_bp.route("/debug/data/clear", methods=["POST"])
def debug_clear_database():
    if not _debug_enabled():
        abort(404)
    result = clear_database_data()
    return jsonify({
        "ok": True,
        "deleted_tables": result["deleted_tables"],
    })
