from flask import Blueprint, render_template, request, redirect, url_for

from app.models import Reward, WishlistItem
from app.services import progress_service
from app.services.config_service import get_current_configuration
from app.services.wishlist_service import activate_wishlist_item
from app.extensions import db

rewards_bp = Blueprint("rewards", __name__)


@rewards_bp.route("/recompensas", methods=["GET"])
def rewards():
    reward_list = Reward.query.all()
    
    focus_id_raw = request.args.get("focus_id")
    selected_reward = None
    if focus_id_raw:
        try:
            selected_reward = db.session.get(Reward, int(focus_id_raw))
        except (ValueError, TypeError):
            pass

    wishlist = WishlistItem.query.filter_by(status="wishlist").order_by(WishlistItem.order).all()
    absolute = progress_service.get_active_absolute()
    cfg = get_current_configuration()

    return render_template(
        "rewards.html",
        rewards=reward_list,
        selected_reward=selected_reward,
        wishlist=wishlist,
        absolute=absolute,
        cfg=cfg
    )


@rewards_bp.route("/recompensas/criar", methods=["POST"])
def create_reward():
    title = request.form.get("title", "").strip()
    progress_type = request.form.get("progress_type", "")
    if title and progress_type in ("daily_minimum", "daily_ideal", "weekly"):
        # Deactivate all other rewards of the same progress_type
        Reward.query.filter_by(progress_type=progress_type).update({"active": False})
        
        reward = Reward(title=title, progress_type=progress_type, active=True)
        db.session.add(reward)
        db.session.commit()
        return redirect(url_for("rewards.rewards", focus_id=reward.id))
    return redirect(url_for("rewards.rewards"))


@rewards_bp.route("/recompensas/<int:reward_id>/ativar", methods=["POST"])
def activate_reward(reward_id):
    reward = Reward.query.get_or_404(reward_id)
    # Deactivate all other rewards of the same progress_type
    Reward.query.filter_by(progress_type=reward.progress_type).update({"active": False})
    reward.active = True
    db.session.commit()
    return redirect(url_for("rewards.rewards", focus_id=reward.id))


@rewards_bp.route("/recompensas/<int:reward_id>/editar", methods=["POST"])
def edit_reward(reward_id):
    reward = Reward.query.get_or_404(reward_id)
    new_title = request.form.get("title", "").strip()
    if new_title:
        reward.title = new_title
        db.session.commit()
    return redirect(url_for("rewards.rewards", focus_id=reward.id))


@rewards_bp.route("/recompensas/<int:reward_id>/excluir", methods=["POST"])
def delete_reward(reward_id):
    reward = Reward.query.get_or_404(reward_id)
    db.session.delete(reward)
    db.session.commit()
    return redirect(url_for("rewards.rewards"))


@rewards_bp.route("/recompensas/wishlist/<int:item_id>/ativar", methods=["POST"])
def activate(item_id):
    activate_wishlist_item(item_id)
    return redirect(url_for("rewards.rewards"))


@rewards_bp.route("/recompensas/wishlist/adicionar", methods=["POST"])
def add_wishlist_item():
    title = request.form.get("title", "").strip()
    goal = request.form.get("suggested_goal", "").strip()
    if title and goal.isdigit():
        max_order = db.session.query(db.func.max(WishlistItem.order)).scalar() or 0
        db.session.add(WishlistItem(title=title, suggested_goal=int(goal), order=max_order + 1))
        db.session.commit()
    return redirect(url_for("rewards.rewards"))
