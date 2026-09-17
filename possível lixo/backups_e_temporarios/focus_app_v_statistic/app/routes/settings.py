from flask import Blueprint, render_template, request, redirect, url_for

from app.services.config_service import get_current_configuration, update_configuration, configuration_history
from app.models import WishlistItem, Reward
from app.extensions import db

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/configuracoes", methods=["GET"])
def settings():
    cfg = get_current_configuration()
    history = configuration_history()
    wishlist = WishlistItem.query.order_by(WishlistItem.order).all()
    rewards = Reward.query.all()
    return render_template(
        "settings.html", cfg=cfg, history=history, wishlist=wishlist, rewards=rewards
    )


@settings_bp.route("/configuracoes", methods=["POST"])
def update_settings():
    form = request.form
    changes = {}
    int_fields = [
        "focus_minutes", "short_break_minutes", "long_break_minutes",
        "cycles_per_session", "daily_minimum_goal", "daily_ideal_goal",
        "weekly_goal", "water_bottle_ml", "water_goal_ml",
    ]
    for field in int_fields:
        raw = form.get(field)
        if raw:
            try:
                changes[field] = int(raw)
            except ValueError:
                pass

    theme = form.get("theme")
    if theme in ("light", "dark", "auto"):
        changes["theme"] = theme

    update_configuration(**changes)
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/wishlist", methods=["POST"])
def add_wishlist_item():
    title = request.form.get("title", "").strip()
    goal = request.form.get("suggested_goal", "").strip()
    if title and goal.isdigit():
        max_order = db.session.query(db.func.max(WishlistItem.order)).scalar() or 0
        db.session.add(WishlistItem(title=title, suggested_goal=int(goal), order=max_order + 1))
        db.session.commit()
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/recompensas", methods=["POST"])
def add_reward():
    title = request.form.get("title", "").strip()
    progress_type = request.form.get("progress_type", "")
    if title and progress_type in ("daily_minimum", "daily_ideal", "weekly", "absolute"):
        db.session.add(Reward(title=title, progress_type=progress_type, active=True))
        db.session.commit()
    return redirect(url_for("settings.settings"))
