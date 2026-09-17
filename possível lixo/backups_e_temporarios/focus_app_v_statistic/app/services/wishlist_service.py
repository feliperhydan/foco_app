"""Serviço de Wishlist (manual, seção 14)."""
from datetime import datetime

from app.extensions import db
from app.models import WishlistItem, AbsoluteProgress
from app.services.clock import now


def activate_wishlist_item(item_id: int) -> AbsoluteProgress | None:
    """
    Ativa um item da wishlist: cria um AbsoluteProgress novo e marca o
    item como 'activated'. A wishlist NUNCA é progresso por si só —
    isso só acontece na ativação (seção 14).
    """
    item = db.session.get(WishlistItem, item_id)
    if item is None or item.status != "wishlist":
        return None

    progress = AbsoluteProgress(
        title=item.title,
        description=item.description,
        goal_cycles=item.suggested_goal,
        current_count=0,
        started_at=now(),
        status="active",
        wishlist_item_id=item.id,
    )
    db.session.add(progress)
    item.status = "activated"
    db.session.commit()
    return progress
