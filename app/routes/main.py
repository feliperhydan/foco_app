import sys
from pathlib import Path

from flask import Blueprint, render_template
from flask import send_from_directory

from app.services.config_service import get_current_configuration
from app.services import progress_service, water_service, todo_service
from app.services.clock import today

main_bp = Blueprint("main", __name__)


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return Path(__file__).resolve().parents[2]


BASE_PROJECT_DIR = _get_base_dir()
ASSETS_DIR = BASE_PROJECT_DIR / "assets"
PNGS_DIR   = BASE_PROJECT_DIR / "PNGs"
GIFS_DIR   = BASE_PROJECT_DIR / "GIFs"



@main_bp.route("/")
def home():
    cfg = get_current_configuration()

    current_day = today()
    daily_min = progress_service.get_daily_minimum_snapshot(current_day)
    daily_ideal = progress_service.get_daily_ideal_snapshot(current_day)
    extra = progress_service.get_extraordinary_snapshot(current_day)
    weekly = progress_service.get_weekly_snapshot(current_day)
    absolute = progress_service.get_active_absolute()
    water = water_service.daily_summary(current_day)
    todos = todo_service.list_items()
    todo_can_add = todo_service.can_add_more()

    from app.models import Reward
    active_min = Reward.query.filter_by(progress_type='daily_minimum', active=True).first()
    active_ideal = Reward.query.filter_by(progress_type='daily_ideal', active=True).first()
    active_weekly = Reward.query.filter_by(progress_type='weekly', active=True).first()

    extraordinary_promo = None
    if extra:
        discount = progress_service.get_or_create_next_discount(extra) or 0
        base_minutes = cfg.focus_minutes
        effective_minutes = round(base_minutes * (1 - discount / 100))
        extraordinary_promo = {
            "discount_pct": discount,
            "base_minutes": base_minutes,
            "effective_minutes": effective_minutes,
        }

    return render_template(
        "home.html",
        cfg=cfg,
        daily_min=daily_min,
        daily_ideal=daily_ideal,
        extra=extra,
        extraordinary_promo=extraordinary_promo,
        weekly=weekly,
        absolute=absolute,
        water=water,
        todos=todos,
        todo_can_add=todo_can_add,
        active_min=active_min,
        active_ideal=active_ideal,
        active_weekly=active_weekly,
        current_day=current_day,
    )



@main_bp.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(ASSETS_DIR, filename)


@main_bp.route("/PNGs/<path:filename>")
def pngs(filename):
    return send_from_directory(PNGS_DIR, filename)


@main_bp.route("/GIFs/<path:filename>")
def gifs(filename):
    return send_from_directory(GIFS_DIR, filename)
