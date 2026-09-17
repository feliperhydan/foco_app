"""
Serviço de Sessões e Ciclos (manual, seção 3.1, 4, 5, 27).

Este módulo cuida só do CICLO DE VIDA do registro (started → completed
/ abandoned) — não atualiza progresso. A atualização de progresso é
responsabilidade de `progress_service.apply_cycle_completion`,
chamada pelo motor de conclusão (`engine.py`). Isso mantém a regra do
manual seção 17: "não duplicar essa lógica em diferentes
componentes" — só existe um caminho para progresso ser atualizado.
"""
from datetime import datetime

from app.extensions import db
from app.models import Session, FocusCycle, RestCycle
from app.services.config_service import get_current_configuration
from app.services.clock import now, today


def get_or_create_active_session() -> Session:
    """
    Retorna a sessão ativa de hoje, se existir, ou cria uma nova.

    Uma sessão fica "ativa" até ser explicitamente encerrada
    (`end_session`) — múltiplas sessões no mesmo dia são esperadas
    (manual, seção 3.1: "Sessão A: 4 ciclos / Sessão B: 3 ciclos").
    """
    from app.services import temporal_service

    temporal_service.reconcile_temporal_state()

    session_ = (
        Session.query.filter_by(date=today())
        .order_by(Session.id.asc())
        .first()
    )
    if session_ is None:
        from app.services import daily_service, week_service, month_service

        session_ = Session(date=today(), started_at=now(), status="active")
        db.session.add(session_)
        db.session.flush()
        daily_service.ensure_daily_for_date(session_.date, session_started=False, commit=False)
        week_service.ensure_week_for_date(session_.date, commit=False)
        month_service.ensure_month_for_date(session_.date, commit=False)
        db.session.commit()
    else:
        from app.services import daily_service, week_service, month_service

        if session_.status != "active":
            session_.status = "active"
            session_.ended_at = None
            db.session.flush()
        daily_service.ensure_daily_for_date(session_.date, session_started=False, commit=False)
        week_service.ensure_week_for_date(session_.date, commit=False)
        month_service.ensure_month_for_date(session_.date, commit=False)
        db.session.commit()
    return session_


def end_session(session_: Session) -> Session:
    from app.services import daily_service

    if session_.status == "active":
        session_.status = "ended"
        session_.ended_at = now()
        db.session.flush()
        daily_service.consolidate_daily(session_.date, commit=False)
        db.session.commit()
    else:
        daily_service.consolidate_daily(session_.date)
    return session_


def start_focus_cycle(title: str | None = None, discount_pct: int | None = None) -> FocusCycle:
    """
    Inicia um novo FocusCycle com a duração da Configuration vigente (snapshot).

    Se `discount_pct` for fornecido (30, 40 ou 50), a duração efetiva é
    calculada como round(base * (1 - pct/100)) e gravada em
    `focus_duration_minutes`. O `discount_pct` é salvo separadamente,
    somente para exibição — não interfere em nenhuma lógica de progresso.
    """
    cfg = get_current_configuration()
    session_ = get_or_create_active_session()

    base_minutes = cfg.focus_minutes
    if discount_pct:
        effective_minutes = round(base_minutes * (1 - discount_pct / 100))
    else:
        effective_minutes = base_minutes

    cycle = FocusCycle(
        session_id=session_.id,
        configuration_id=cfg.id,
        started_at=now(),
        focus_duration_minutes=effective_minutes,  # snapshot imutável (já com desconto)
        discount_pct=discount_pct,                 # só para exibição visual
        status="started",
        title=title,
    )
    db.session.add(cycle)
    db.session.commit()
    return cycle


def abandon_focus_cycle(cycle_id: int) -> FocusCycle | None:
    """
    Abandona um ciclo em andamento. Idempotente: se o ciclo já estiver
    completed/abandoned, não faz nada (manual, seção 18).
    """
    cycle = db.session.get(FocusCycle, cycle_id)
    if cycle is None:
        return None
    if cycle.status == "started":
        cycle.status = "abandoned"
        db.session.commit()
    return cycle


def start_rest_cycle(kind: str) -> RestCycle:
    """kind: 'short' | 'long'"""
    cfg = get_current_configuration()
    session_ = get_or_create_active_session()

    duration = cfg.short_break_minutes if kind == "short" else cfg.long_break_minutes
    rest = RestCycle(
        session_id=session_.id,
        configuration_id=cfg.id,
        kind=kind,
        duration_minutes=duration,  # snapshot imutável
        started_at=now(),
        status="started",
    )
    db.session.add(rest)
    db.session.commit()
    return rest


def complete_rest_cycle(rest_id: int) -> RestCycle | None:
    rest = db.session.get(RestCycle, rest_id)
    if rest is None:
        return None
    if rest.status == "started":
        rest.status = "completed"
        rest.ended_at = now()
        from app.services import daily_service
        daily_service.consolidate_daily(today(), commit=False)
        db.session.commit()
    return rest


def abandon_rest_cycle(rest_id: int) -> RestCycle | None:
    rest = db.session.get(RestCycle, rest_id)
    if rest is None:
        return None
    if rest.status == "started":
        rest.status = "abandoned"
        db.session.commit()
    return rest
