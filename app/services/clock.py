"""
Relógio do aplicativo.

Este módulo centraliza a noção de "agora" e "hoje" usada pelo
sistema. Em modo de debug, o relógio pode ser adiantado em dias sem
alterar o relógio real da máquina, o que permite testar metas diárias,
semanais e o calendário com rapidez.
"""
from datetime import datetime, timedelta

from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.models import DebugState
from app.services.time_utils import utcnow_naive


def _get_state() -> DebugState:
    try:
        state = DebugState.query.filter_by(name="clock").first()
    except OperationalError:
        db.session.rollback()
        db.create_all()
        state = DebugState.query.filter_by(name="clock").first()
    if state is None:
        state = DebugState(name="clock", clock_offset_days=0)
        db.session.add(state)
        db.session.commit()
    return state


def offset_days() -> int:
    return _get_state().clock_offset_days


def now() -> datetime:
    return utcnow_naive() + timedelta(days=offset_days())


def today():
    return now().date()


def advance_days(days: int) -> DebugState:
    state = _get_state()
    state.clock_offset_days += days
    db.session.commit()
    return state


def set_offset_days(days: int) -> DebugState:
    state = _get_state()
    state.clock_offset_days = days
    db.session.commit()
    return state


def reset() -> DebugState:
    return set_offset_days(0)
