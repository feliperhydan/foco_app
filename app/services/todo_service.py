"""Servico da to-do list lateral."""

from sqlalchemy import func
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.models import TodoItem, TodoListState
from app.services.clock import today


MAX_ITEMS = 15
MAX_TEXT_LENGTH = 140
STATE_NAME = "default"


def _clean_text(text: str | None) -> str:
    return (text or "").strip()[:MAX_TEXT_LENGTH]


def _ensure_today_completion_state(commit: bool = True) -> None:
    """
    Garante que os checks persistidos pertencem ao dia atual.

    Os itens sao persistentes entre dias, mas `done` e exclusivamente
    diario. Quando a data do app muda, apenas os checks sao zerados.
    """
    current_day = today()
    try:
        state = TodoListState.query.filter_by(name=STATE_NAME).first()
    except OperationalError:
        db.session.rollback()
        db.create_all()
        state = TodoListState.query.filter_by(name=STATE_NAME).first()

    if state is None:
        state = TodoListState(name=STATE_NAME, last_completed_date=current_day)
        db.session.add(state)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return

    if state.last_completed_date == current_day:
        return

    TodoItem.query.update({"done": False}, synchronize_session=False)
    state.last_completed_date = current_day
    if commit:
        db.session.commit()
    else:
        db.session.flush()


def ensure_today_completion_state(commit: bool = True) -> None:
    """Garante que os checks da to-do pertencem ao dia operacional atual."""
    _ensure_today_completion_state(commit=commit)


def list_items() -> list[TodoItem]:
    """Todos os itens, ordenados por `order` ascendente."""
    _ensure_today_completion_state()
    return TodoItem.query.order_by(TodoItem.order.asc(), TodoItem.id.asc()).all()


def can_add_more() -> bool:
    """True se list_items() tiver menos que MAX_ITEMS."""
    _ensure_today_completion_state()
    return TodoItem.query.count() < MAX_ITEMS


def create_item(text: str = "") -> TodoItem | None:
    """
    Cria um novo item ao final da lista. Retorna None se o limite ja
    tiver sido atingido.
    """
    _ensure_today_completion_state()
    if not can_add_more():
        return None

    next_order = (db.session.query(func.max(TodoItem.order)).scalar() or 0) + 1
    item = TodoItem(text=_clean_text(text), done=False, order=next_order)
    db.session.add(item)
    from app.services import daily_service
    daily_service.refresh_todo_snapshot_for_today(commit=False)
    db.session.commit()
    return item


def update_item_text(item_id: int, text: str) -> TodoItem | None:
    """Atualiza o texto de um item. Trunca em 140 caracteres. Retorna None se nao existir."""
    _ensure_today_completion_state()
    item = db.session.get(TodoItem, item_id)
    if item is None:
        return None

    item.text = _clean_text(text)
    from app.services import daily_service
    daily_service.refresh_todo_snapshot_for_today(commit=False)
    db.session.commit()
    return item


def toggle_item(item_id: int) -> TodoItem | None:
    """Alterna done <-> not done. Retorna None se nao existir."""
    _ensure_today_completion_state()
    item = db.session.get(TodoItem, item_id)
    if item is None:
        return None

    item.done = not item.done
    from app.services import daily_service
    daily_service.refresh_todo_snapshot_for_today(commit=False)
    db.session.commit()
    return item


def delete_item(item_id: int) -> bool:
    """Remove um item individual. Idempotente: retorna True mesmo se ja nao existir."""
    _ensure_today_completion_state()
    item = db.session.get(TodoItem, item_id)
    if item is None:
        return True

    db.session.delete(item)
    from app.services import daily_service
    daily_service.refresh_todo_snapshot_for_today(commit=False)
    db.session.commit()
    return True
