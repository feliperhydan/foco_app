from datetime import date as date_

from flask import Blueprint, render_template

from app.services.config_service import get_current_configuration
from app.services import progress_service, water_service

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    today = date_.today()
    cfg = get_current_configuration()

    daily_min = progress_service.get_daily_minimum_snapshot(today)
    daily_ideal = progress_service.get_daily_ideal_snapshot(today)
    extra = progress_service.get_extraordinary_snapshot(today)
    weekly = progress_service.get_weekly_snapshot(today)
    absolute = progress_service.get_active_absolute()
    water = water_service.daily_summary(today)

    return render_template(
        "home.html",
        cfg=cfg,
        daily_min=daily_min,
        daily_ideal=daily_ideal,
        extra=extra,
        weekly=weekly,
        absolute=absolute,
        water=water,
    )
