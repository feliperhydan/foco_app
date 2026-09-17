"""Reconcilia estado temporal do aplicativo.

O relogio operacional vem de app.services.clock. O banco continua sendo
a fonte da verdade historica.
"""
from __future__ import annotations

from datetime import datetime, time as time_, date as date_

from app.extensions import db
from app.models import Daily, Session, Week, Month
from app.services import daily_service, week_service, month_service
from app.services.clock import today
from app.services.progress_service import week_bounds
from app.services.month_service import month_bounds


def _end_of_day(d):
    return datetime.combine(d, time_(23, 59, 59, 999999))


def reconcile_temporal_state(current_day=None, commit: bool = True) -> list[Session]:
    """
    Encerra e consolida sessoes abertas de dias anteriores.

    Idempotente: uma sessao ja encerrada nao e alterada e um Daily ja
    consolidado e retornado pelo daily_service sem recalculo.
    """
    current_day = current_day or today()
    pending_sessions = (
        Session.query.filter(Session.status == "active", Session.date < current_day)
        .order_by(Session.date.asc(), Session.id.asc())
        .all()
    )

    for session_ in pending_sessions:
        started_cycles = (
            session_.focus_cycles
            if session_.focus_cycles is not None
            else []
        )
        for cycle in started_cycles:
            if cycle.status == "started":
                cycle.status = "abandoned"
        session_.status = "ended"
        session_.ended_at = _end_of_day(session_.date)
        db.session.flush()
        daily_service.consolidate_daily(session_.date, commit=False, force=True)

    current_week_start, _ = week_bounds(current_day)
    periods = set()
    for daily_date, in (
        db.session.query(Daily.date)
        .filter(Daily.date < current_week_start)
        .order_by(Daily.date.asc())
        .all()
    ):
        periods.add(week_bounds(daily_date))
    for start_date, end_date in (
        db.session.query(Week.start_date, Week.end_date)
        .filter(Week.end_date < current_week_start)
        .order_by(Week.start_date.asc())
        .all()
    ):
        periods.add((start_date, end_date))

    for start_date, end_date in sorted(periods):
        week_service.rebuild_week(start_date, end_date, final=True, commit=False)

    current_month_start = date_(current_day.year, current_day.month, 1)
    month_periods = set()
    for daily_date, in (
        db.session.query(Daily.date)
        .filter(Daily.date < current_month_start)
        .order_by(Daily.date.asc())
        .all()
    ):
        month_periods.add(month_bounds(daily_date))
    for start_date, end_date in (
        db.session.query(Month.start_date, Month.end_date)
        .filter(Month.end_date < current_month_start)
        .order_by(Month.start_date.asc())
        .all()
    ):
        month_periods.add((start_date, end_date))

    for start_date, end_date in sorted(month_periods):
        month_service.rebuild_month(start_date, end_date, final=True, commit=False)

    if commit and (pending_sessions or periods or month_periods):
        db.session.commit()
    return pending_sessions
