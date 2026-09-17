from datetime import date as date_

from flask import Blueprint, jsonify, request

from app.services import cycles_service, engine, water_service, progress_service, calendar_service
from app.services.config_service import get_current_configuration

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _home_state_payload():
    today = date_.today()
    daily_min = progress_service.get_daily_minimum_snapshot(today)
    daily_ideal = progress_service.get_daily_ideal_snapshot(today)
    extra = progress_service.get_extraordinary_snapshot(today)
    weekly = progress_service.get_weekly_snapshot(today)
    absolute = progress_service.get_active_absolute()
    water = water_service.daily_summary(today)

    return {
        "daily_minimum": {"current": daily_min.current_count, "goal": daily_min.goal, "pct": daily_min.pct},
        "daily_ideal": {"current": daily_ideal.current_count, "goal": daily_ideal.goal, "pct": daily_ideal.pct},
        "extraordinary": (
            {"cycles": extra.extra_cycles, "minutes": extra.extra_minutes} if extra else None
        ),
        "weekly": {"current": weekly.current_count, "goal": weekly.goal, "pct": weekly.pct},
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
    cycle = cycles_service.start_focus_cycle()
    return jsonify({
        "cycle_id": cycle.id,
        "focus_duration_minutes": cycle.focus_duration_minutes,
        "started_at": cycle.started_at.isoformat(),
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
    kind = (request.get_json(silent=True) or {}).get("kind", "short")
    rest = cycles_service.start_rest_cycle(kind)
    return jsonify({
        "rest_id": rest.id, "kind": rest.kind, "duration_minutes": rest.duration_minutes,
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
    return jsonify(water_service.daily_summary(date_.today()))


@api_bp.route("/calendar")
def calendar():
    mode = request.args.get("mode", "cycles")
    weeks = int(request.args.get("weeks", 18))
    if mode not in ("cycles", "minutes"):
        mode = "cycles"
    grid = calendar_service.heatmap_grid(weeks=weeks, mode=mode)
    return jsonify({"mode": mode, "weeks": weeks, "grid": grid})
