"""
Serviço de Sessões e Ciclos (manual, seção 3.1, 4, 5, 27).

Este módulo cuida só do CICLO DE VIDA do registro (started → completed
/ abandoned) — não atualiza progresso. A atualização de progresso é
responsabilidade de `progress_service.apply_cycle_completion`,
chamada pelo motor de conclusão (`engine.py`). Isso mantém a regra do
manual seção 17: "não duplicar essa lógica em diferentes
componentes" — só existe um caminho para progresso ser atualizado.

Todas as datas/horas usadas aqui vêm do relógio virtual
(`app.services.clock`), nunca de `datetime.utcnow()`/`date.today()`
diretamente — é isso que permite avançar o tempo em testes sem mexer
no relógio real do sistema (ver `clock.py`).
"""
from __future__ import annotations

from app.extensions import db
from app.models import Session, FocusCycle, RestCycle
from app.services import clock, daily_service
from app.services.config_service import get_current_configuration


def get_or_create_active_session() -> Session:
    """
    Retorna a sessão de hoje, reabrindo-a se necessário.

    Existe no máximo uma linha `Session` por dia — encerrar uma
    sessão (`end_session`) não cria uma nova ao retomar o trabalho no
    mesmo dia, apenas reabre a mesma linha (`status` volta a
    `active`). Isso mantém `Daily.session` como um snapshot único por
    dia, não uma lista de sessões.
    """
    today = clock.today()
    session_ = (
        Session.query.filter_by(date=today)
        .order_by(Session.id.desc())
        .first()
    )
    if session_ is None:
        session_ = Session(date=today, started_at=clock.now(), status="active")
        db.session.add(session_)
        db.session.flush()
        daily_service.ensure_daily_for_date(today, session_started=False, commit=False)
        db.session.commit()
    elif session_.status != "active":
        session_.status = "active"
        session_.ended_at = None
        db.session.commit()
    return session_


def end_session(session_: Session) -> Session:
    if session_.status == "active":
        session_.status = "ended"
        session_.ended_at = clock.now()
        db.session.commit()
    return session_


def end_all_active_sessions_before_today() -> None:
    """
    Encerra qualquer sessão ainda 'active' de um dia anterior ao dia
    corrente do relógio virtual, e consolida o `Daily` correspondente
    na mesma passada — é isso que fecha "o dia anterior" no instante
    em que o usuário começa a trabalhar num dia novo, sem depender de
    uma reconciliação explícita depois.
    """
    today = clock.today()
    stale = Session.query.filter(Session.status == "active", Session.date < today).all()
    touched_dates = set()
    for session_ in stale:
        session_.status = "ended"
        session_.ended_at = session_.ended_at or clock.now()
        touched_dates.add(session_.date)
    if stale:
        db.session.flush()
        for d in touched_dates:
            daily_service.consolidate_daily(d, commit=False)
        db.session.commit()


def start_focus_cycle(title: str | None = None) -> FocusCycle:
    """Inicia um novo FocusCycle com a duração da Configuration vigente (snapshot)."""
    end_all_active_sessions_before_today()
    cfg = get_current_configuration()
    session_ = get_or_create_active_session()

    cycle = FocusCycle(
        session_id=session_.id,
        configuration_id=cfg.id,
        started_at=clock.now(),
        focus_duration_minutes=cfg.focus_minutes,  # snapshot imutável
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
    cycle = FocusCycle.query.get(cycle_id)
    if cycle is None:
        return None
    if cycle.status == "started":
        cycle.status = "abandoned"
        db.session.commit()
    return cycle


def start_rest_cycle(kind: str) -> RestCycle:
    """kind: 'short' | 'long'"""
    end_all_active_sessions_before_today()
    cfg = get_current_configuration()
    session_ = get_or_create_active_session()

    duration = cfg.short_break_minutes if kind == "short" else cfg.long_break_minutes
    rest = RestCycle(
        session_id=session_.id,
        configuration_id=cfg.id,
        kind=kind,
        duration_minutes=duration,  # snapshot imutável
        started_at=clock.now(),
        status="started",
    )
    db.session.add(rest)
    db.session.commit()
    return rest


def complete_rest_cycle(rest_id: int) -> RestCycle | None:
    rest = RestCycle.query.get(rest_id)
    if rest is None:
        return None
    if rest.status == "started":
        rest.status = "completed"
        rest.ended_at = clock.now()
        daily_service.consolidate_daily(rest.ended_at.date(), commit=False)
        db.session.commit()
    return rest


def abandon_rest_cycle(rest_id: int) -> RestCycle | None:
    rest = RestCycle.query.get(rest_id)
    if rest is None:
        return None
    if rest.status == "started":
        rest.status = "abandoned"
        db.session.commit()
    return rest
