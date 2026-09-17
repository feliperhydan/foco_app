"""
Reconciliação temporal.

Responsável por fechar o que ficou pendente quando o tempo avança
sem que o usuário tenha explicitamente "encerrado o dia" — sessões
`active` de um dia que já passou, e o `Daily` correspondente, que só
pode ser consolidado (imutável) depois que não há mais sessão ativa
nele (ver `daily_service.consolidate_daily`).

Idempotente: chamar duas vezes seguidas não duplica nem altera nada
além da primeira passada — cada `Daily` só é tocado enquanto
`consolidated_at is None`.
"""
from __future__ import annotations

from app.extensions import db
from app.models import Daily, Session
from app.services import clock, daily_service


def _end_stale_active_sessions() -> None:
    today = clock.today()
    stale = Session.query.filter(Session.status == "active", Session.date < today).all()
    for session_ in stale:
        session_.status = "ended"
        session_.ended_at = session_.ended_at or clock.now()
    if stale:
        db.session.flush()


def reconcile_temporal_state(commit: bool = True) -> list[Daily]:
    """
    Varre todo `Daily` ainda aberto (`consolidated_at IS NULL`) com
    data anterior a hoje e tenta consolidá-lo. Não cria `Daily` novo
    para dias que nunca tiveram nenhuma sessão — só age sobre o que
    já existe.
    """
    today = clock.today()
    _end_stale_active_sessions()

    open_dailies = (
        Daily.query.filter(Daily.consolidated_at.is_(None), Daily.date < today)
        .order_by(Daily.date.asc())
        .all()
    )
    touched = []
    for daily in open_dailies:
        touched.append(daily_service.consolidate_daily(daily.date, commit=False))

    if commit:
        db.session.commit()
    return touched
