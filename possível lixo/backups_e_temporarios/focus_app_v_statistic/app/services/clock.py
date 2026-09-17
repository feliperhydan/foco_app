"""
Relógio virtual do aplicativo.

Todo o código de produto deve ler "que dia é hoje" e "que horas são
agora" através deste módulo — nunca via `datetime.utcnow()` ou
`date.today()` diretamente — porque isso é o que permite avançar o
tempo em testes (`set_offset_days`) sem mexer no relógio real do
sistema operacional. O deslocamento é persistido em `DebugState`
(linha única, `name="clock"`), então ele sobrevive entre chamadas
dentro do mesmo processo/teste.
"""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import DebugState


def _get_state() -> DebugState:
    state = DebugState.query.filter_by(name="clock").first()
    if state is None:
        state = DebugState(name="clock", clock_offset_days=0)
        db.session.add(state)
        db.session.commit()
    return state


def today() -> date:
    return date.today() + timedelta(days=_get_state().clock_offset_days)


def now() -> datetime:
    return datetime.utcnow() + timedelta(days=_get_state().clock_offset_days)


def set_offset_days(days: int) -> None:
    """Define o deslocamento absoluto (não cumulativo) em dias a partir de hoje."""
    state = _get_state()
    state.clock_offset_days = days
    db.session.commit()


def reset() -> None:
    set_offset_days(0)
