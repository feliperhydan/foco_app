"""
Serviço de Estatísticas (manual, seção 19–24).

Regra geral: nada aqui é armazenado como agregado — tudo é somado /
contado a partir de FocusCycle e Session no momento da consulta
(seção 19, 41). Ciclos e minutos são sempre calculados e comparados
SEPARADAMENTE (seção 17 e 22 do manual/briefing), e toda estatística
de período carrega o contexto de configuração vigente naquele
período, para nunca comparar "8/8 vs 8/9" sem permitir descobrir por
quê (seção 16 do briefing visual, seção 20–23 do manual).
"""
from datetime import date as date_, timedelta
from sqlalchemy import func

from app.extensions import db
from app.models import FocusCycle, Session, Configuration, ExtraordinaryProgress, RewardAchievement
from app.services.progress_service import week_bounds


def cycles_count(start: date_, end: date_) -> int:
    return (
        FocusCycle.query.filter(
            FocusCycle.status == "completed",
            func.date(FocusCycle.completed_at) >= start.isoformat(),
            func.date(FocusCycle.completed_at) <= end.isoformat(),
        ).count()
    )


def minutes_sum(start: date_, end: date_) -> int:
    total = (
        db.session.query(func.sum(FocusCycle.focus_duration_minutes))
        .filter(
            FocusCycle.status == "completed",
            func.date(FocusCycle.completed_at) >= start.isoformat(),
            func.date(FocusCycle.completed_at) <= end.isoformat(),
        )
        .scalar()
    )
    return int(total or 0)


def active_days_count(start: date_, end: date_) -> int:
    """Dia ativo = houve uma Session iniciada nele (manual, seção 24) — independe de quantos ciclos."""
    return (
        db.session.query(func.count(func.distinct(Session.date)))
        .filter(Session.date >= start, Session.date <= end)
        .scalar()
    ) or 0


def sessions_count(start: date_, end: date_) -> int:
    return Session.query.filter(Session.date >= start, Session.date <= end).count()


def extraordinary_totals(start: date_, end: date_) -> dict:
    rows = ExtraordinaryProgress.query.filter(
        ExtraordinaryProgress.date >= start, ExtraordinaryProgress.date <= end
    ).all()
    return {
        "cycles": sum(r.extra_cycles for r in rows),
        "minutes": sum(r.extra_minutes for r in rows),
    }


def rewards_achieved_count(start: date_, end: date_) -> int:
    return RewardAchievement.query.filter(
        RewardAchievement.achieved_date >= start, RewardAchievement.achieved_date <= end
    ).count()


def best_day(start: date_, end: date_) -> dict | None:
    row = (
        db.session.query(
            func.date(FocusCycle.completed_at).label("day"),
            func.count(FocusCycle.id).label("cycles"),
            func.sum(FocusCycle.focus_duration_minutes).label("minutes"),
        )
        .filter(
            FocusCycle.status == "completed",
            func.date(FocusCycle.completed_at) >= start.isoformat(),
            func.date(FocusCycle.completed_at) <= end.isoformat(),
        )
        .group_by(func.date(FocusCycle.completed_at))
        .order_by(func.count(FocusCycle.id).desc())
        .first()
    )
    if row is None:
        return None
    return {"date": row.day, "cycles": row.cycles, "minutes": int(row.minutes or 0)}


def configurations_in_period(start: date_, end: date_) -> list[Configuration]:
    """
    Todas as configurações vigentes em algum momento do período —
    usado para o "sobrenome" da estatística (manual, seção 20, 21;
    briefing visual, seção 16): "8/9 · 45 min/ciclo".
    """
    start_dt, end_dt = start.isoformat(), (end + timedelta(days=1)).isoformat()
    return (
        Configuration.query.filter(
            Configuration.valid_from < end_dt,
            db.or_(Configuration.valid_to.is_(None), Configuration.valid_to > start_dt),
        )
        .order_by(Configuration.valid_from.asc())
        .all()
    )


def _growth_pct(current: int, previous: int) -> float | None:
    if previous == 0:
        return None  # sem base de comparação — não inventar percentual
    return round(100 * (current - previous) / previous, 1)


def period_summary(start: date_, end: date_) -> dict:
    cycles = cycles_count(start, end)
    minutes = minutes_sum(start, end)
    return {
        "start": start, "end": end,
        "cycles": cycles,
        "minutes": minutes,
        "active_days": active_days_count(start, end),
        "sessions": sessions_count(start, end),
        "extraordinary": extraordinary_totals(start, end),
        "rewards_achieved": rewards_achieved_count(start, end),
        "best_day": best_day(start, end),
        "configurations": configurations_in_period(start, end),
    }


def weekly_stats(reference: date_ | None = None) -> dict:
    reference = reference or date_.today()
    start, end = week_bounds(reference)
    prev_start, prev_end = start - timedelta(days=7), end - timedelta(days=7)

    current = period_summary(start, end)
    previous = period_summary(prev_start, prev_end)

    current["cycles_growth_pct"] = _growth_pct(current["cycles"], previous["cycles"])
    current["minutes_growth_pct"] = _growth_pct(current["minutes"], previous["minutes"])
    current["previous"] = previous
    return current


def monthly_stats(year: int, month: int) -> dict:
    start = date_(year, month, 1)
    end = date_(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date_(year, month + 1, 1) - timedelta(days=1)

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    prev_start = date_(prev_year, prev_month, 1)
    prev_end = date_(prev_year + 1, 1, 1) - timedelta(days=1) if prev_month == 12 else date_(prev_year, prev_month + 1, 1) - timedelta(days=1)

    current = period_summary(start, end)
    previous = period_summary(prev_start, prev_end)

    current["cycles_growth_pct"] = _growth_pct(current["cycles"], previous["cycles"])
    current["minutes_growth_pct"] = _growth_pct(current["minutes"], previous["minutes"])
    current["previous"] = previous
    return current
