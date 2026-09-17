from flask import Blueprint, render_template, request, redirect, url_for

from app.models import Reward, WishlistItem
from app.services import progress_service
from app.services.wishlist_service import activate_wishlist_item

rewards_bp = Blueprint("rewards", __name__)


@rewards_bp.route("/recompensas")
def rewards():
    reward_list = Reward.query.filter_by(active=True).all()
    wishlist = WishlistItem.query.filter_by(status="wishlist").order_by(WishlistItem.order).all()
    absolute = progress_service.get_active_absolute()

    return render_template(
        "rewards.html", rewards=reward_list, wishlist=wishlist, absolute=absolute
    )


@rewards_bp.route("/recompensas/wishlist/<int:item_id>/ativar", methods=["POST"])
def activate(item_id):
    activate_wishlist_item(item_id)
    return redirect(url_for("rewards.rewards"))
