"""
Camada de apresentação/análise sobre o histórico (Daily/Week/Month).

Este módulo NUNCA reconstrói histórico consultando tabelas
operacionais (FocusCycle, Session, etc.) diretamente — ele só lê
`Daily`, `Week` e `Month`, que já são a fonte de verdade consolidada
(ver `daily_service.py`, `week_service.py`, `month_service.py`).

Separação mantida deliberadamente (prompt de implementação, seção 19):

    DADOS (aqui: get_day/get_week/get_month)
      → MATEMÁTICA (aqui: pct_change, compare_*)
      → ANÁLISE (ainda não implementada — Fase 3: melhores/piores,
        sequências, padrões. Os pontos de extensão estão marcados
        abaixo com TODO(fase-3) para não precisar redesenhar nada
        quando essa camada for construída.)
      → APRESENTAÇÃO (routes/stats.py + templates/stats.html)
"""
from __future__ import annotations

from datetime import date as date_, timedelta

from app.models import Daily, Week, Month
from app.services import clock, daily_service, week_service, month_service
from app.services.progress_service import week_bounds
from app.services.month_service import month_bounds

# ---------------------------------------------------------------------------
# CAMADA 1 — DADOS BRUTOS
# ---------------------------------------------------------------------------


def get_day(d: date_) -> dict:
    """
    Dados brutos de um dia. Se `d` ainda não passou, atualiza o
    snapshot antes de ler (dia corrente = progressivo, nunca
    congelado — seção 17 do prompt). Para dias passados já
    consolidados, `consolidate_daily` is um no-op (retorna na hora).
    """
    if d <= clock.today():
        daily_service.consolidate_daily(d, commit=True, force=(d == clock.today()))
    row = Daily.query.filter_by(date=d).first()
    if row is None:
        return {"date": d.isoformat(), "empty": True, "session_started": False}
    data = row.as_dict()
    data["empty"] = not data["session_started"]
    return data


def get_week(d: date_) -> dict:
    """Dados agregados da semana que contém `d`, sempre via Week (nunca recomputado à mão)."""
    week = week_service.rebuild_week_for_date(d, final=False, commit=True)
    
    # Calculate analysis metrics for the week
    daily_vals = []
    minutes_by_date = {}
    w_dailies = Daily.query.filter(Daily.date >= week.start_date, Daily.date <= week.end_date).all()
    for daily in w_dailies:
        m = sum(c.get("focus", {}).get("minutes_completed", 0) for c in (daily.cycle_contexts or []))
        minutes_by_date[daily.date] = m
    for i in range(7):
        dt = week.start_date + timedelta(days=i)
        daily_vals.append(minutes_by_date.get(dt, 0.0))
        
    std_dev = get_std_dev(daily_vals)
    ideal_count = week.rewards.get("daily_ideal", {}).get("completed_count", 0)
    avg_minutes = sum(daily_vals) / 7.0

    return {
        "start_date": week.start_date.isoformat(),
        "end_date": week.end_date.isoformat(),
        "status": week.status,
        "days": week.days,
        "totals": week.totals,
        "contexts": week.contexts,
        "titles": week.titles,
        "water": week.water,
        "todo": week.todo,
        "rewards": week.rewards,
        "absolute": week.absolute,
        "analysis": {
            "std_dev": std_dev,
            "ideal_count": ideal_count,
            "avg_minutes": avg_minutes,
            "total_days": 7
        }
    }


def get_month(d: date_) -> dict:
    """Dados agregados do mês que contém `d`, sempre via Month."""
    month = month_service.rebuild_month_for_date(d, final=False, commit=True)
    num_days = (month.end_date - month.start_date).days + 1
    
    # Calculate analysis metrics for the month
    daily_vals = []
    minutes_by_date = {}
    m_dailies = Daily.query.filter(Daily.date >= month.start_date, Daily.date <= month.end_date).all()
    for daily in m_dailies:
        m = sum(c.get("focus", {}).get("minutes_completed", 0) for c in (daily.cycle_contexts or []))
        minutes_by_date[daily.date] = m
    for i in range(num_days):
        dt = month.start_date + timedelta(days=i)
        daily_vals.append(minutes_by_date.get(dt, 0.0))
        
    std_dev = get_std_dev(daily_vals)
    ideal_count = month.rewards.get("daily_ideal", {}).get("completed_count", 0)
    avg_minutes = sum(daily_vals) / float(num_days)

    return {
        "start_date": month.start_date.isoformat(),
        "end_date": month.end_date.isoformat(),
        "status": month.status,
        "days": month.days,
        "totals": month.totals,
        "contexts": month.contexts,
        "titles": month.titles,
        "water": month.water,
        "todo": month.todo,
        "rewards": month.rewards,
        "absolute": month.absolute,
        "analysis": {
            "std_dev": std_dev,
            "ideal_count": ideal_count,
            "avg_minutes": avg_minutes,
            "total_days": num_days
        }
    }


# ---------------------------------------------------------------------------
# navegação entre períodos (anterior / próximo)
# ---------------------------------------------------------------------------


def previous_day(d: date_) -> date_:
    return d - timedelta(days=1)


def next_day(d: date_) -> date_:
    return d + timedelta(days=1)


def previous_week_ref(d: date_) -> date_:
    start, _ = week_bounds(d)
    return start - timedelta(days=7)


def next_week_ref(d: date_) -> date_:
    start, _ = week_bounds(d)
    return start + timedelta(days=7)


def previous_month_ref(d: date_) -> date_:
    start, _ = month_bounds(d)
    return start - timedelta(days=1)


def next_month_ref(d: date_) -> date_:
    _, end = month_bounds(d)
    return end + timedelta(days=1)


# ---------------------------------------------------------------------------
# CAMADA 2 — MATEMÁTICA (recorte mínimo: comparação percentual)
# ---------------------------------------------------------------------------


def pct_change(a, b) -> float | None:
    """
    Variação percentual de `a` (mais antigo) para `b` (mais recente).
    None quando não há base de comparação (`a` é 0/None) — nunca
    inventar um percentual sem denominador real.
    """
    if not a:
        return None
    return round(100 * (b - a) / a, 1)


def _day_focus_totals(day: dict) -> tuple[int, int]:
    cycles = sum(c["focus"]["cycles_completed"] for c in day.get("cycle_contexts", []))
    minutes = sum(c["focus"]["minutes_completed"] for c in day.get("cycle_contexts", []))
    return cycles, minutes


def get_streak_on_date(d: date_) -> int:
    rows = (
        Daily.query.filter(
            Daily.date <= d,
            Daily.session_started == True
        )
        .order_by(Daily.date.desc())
        .all()
    )
    streak = 0
    curr = d
    for r in rows:
        if r.date == curr:
            streak += 1
            curr -= timedelta(days=1)
        else:
            break
    return streak


def get_best_streak() -> dict:
    rows = (
        Daily.query.filter(Daily.session_started == True)
        .order_by(Daily.date.asc())
        .all()
    )
    if not rows:
        return {"length": 0, "start": None, "end": None}

    best_len = 0
    best_start = None
    best_end = None

    curr_len = 0
    curr_start = None
    prev_date = None

    for r in rows:
        dt = r.date
        if prev_date is None:
            curr_len = 1
            curr_start = dt
        elif dt == prev_date + timedelta(days=1):
            curr_len += 1
        else:
            if curr_len > best_len:
                best_len = curr_len
                best_start = curr_start
                best_end = prev_date
            curr_len = 1
            curr_start = dt
        prev_date = dt

    if curr_len > best_len:
        best_len = curr_len
        best_start = curr_start
        best_end = prev_date

    return {
        "length": best_len,
        "start": best_start.strftime("%d/%m/%Y") if best_start else None,
        "end": best_end.strftime("%d/%m/%Y") if best_end else None,
    }


def compare_days(a_date: date_, b_date: date_) -> dict:
    """A = mais antigo, B = mais recente — nunca a ordem inversa (seção 7)."""
    a, b = get_day(a_date), get_day(b_date)
    a_cycles, a_minutes = _day_focus_totals(a)
    b_cycles, b_minutes = _day_focus_totals(b)

    a_active = get_streak_on_date(a_date)
    b_active = get_streak_on_date(b_date)
    a_sessions = 1 if a.get("session_started") else 0
    b_sessions = 1 if b.get("session_started") else 0

    a_extra_cycles = sum(c["extraordinary"]["cycles"] for c in a.get("cycle_contexts", []))
    b_extra_cycles = sum(c["extraordinary"]["cycles"] for c in b.get("cycle_contexts", []))
    a_extra_minutes = sum(c["extraordinary"]["minutes"] for c in a.get("cycle_contexts", []))
    b_extra_minutes = sum(c["extraordinary"]["minutes"] for c in b.get("cycle_contexts", []))

    return {
        "a": {"date": a_date.isoformat(), "raw": a},
        "b": {"date": b_date.isoformat(), "raw": b},
        "cycles": {"a": a_cycles, "b": b_cycles, "pct": pct_change(a_cycles, b_cycles)},
        "minutes": {"a": a_minutes, "b": b_minutes, "pct": pct_change(a_minutes, b_minutes)},
        "active_days": {"a": a_active, "b": b_active, "pct": pct_change(a_active, b_active)},
        "sessions": {"a": a_sessions, "b": b_sessions, "pct": pct_change(a_sessions, b_sessions)},
        "extraordinary": {
            "cycles": {"a": a_extra_cycles, "b": b_extra_cycles, "pct": pct_change(a_extra_cycles, b_extra_cycles)},
            "minutes": {"a": a_extra_minutes, "b": b_extra_minutes, "pct": pct_change(a_extra_minutes, b_extra_minutes)},
        },
        "best_streak": get_best_streak()
    }


def _period_focus_totals(period: dict) -> tuple[int, int]:
    focus = (period.get("totals") or {}).get("focus", {})
    return focus.get("cycles_completed", 0), focus.get("minutes_completed", 0)


def _period_active_days_and_sessions(period: dict) -> tuple[int, int]:
    days = period.get("days") or []
    active = sum(1 for d in days if d.get("session_started"))
    return active, active


def _period_extraordinary_totals(period: dict) -> tuple[int, int]:
    extra = (period.get("totals") or {}).get("extraordinary", {})
    return extra.get("cycles", 0), extra.get("minutes", 0)


def compare_weeks(a_ref: date_, b_ref: date_) -> dict:
    a, b = get_week(a_ref), get_week(b_ref)
    a_cycles, a_minutes = _period_focus_totals(a)
    b_cycles, b_minutes = _period_focus_totals(b)

    a_active, a_sessions = _period_active_days_and_sessions(a)
    b_active, b_sessions = _period_active_days_and_sessions(b)

    a_extra_cycles, a_extra_minutes = _period_extraordinary_totals(a)
    b_extra_cycles, b_extra_minutes = _period_extraordinary_totals(b)

    return {
        "a": {"label": f"{a['start_date']} — {a['end_date']}", "raw": a},
        "b": {"label": f"{b['start_date']} — {b['end_date']}", "raw": b},
        "cycles": {"a": a_cycles, "b": b_cycles, "pct": pct_change(a_cycles, b_cycles)},
        "minutes": {"a": a_minutes, "b": b_minutes, "pct": pct_change(a_minutes, b_minutes)},
        "active_days": {"a": a_active, "b": b_active, "pct": pct_change(a_active, b_active)},
        "sessions": {"a": a_sessions, "b": b_sessions, "pct": pct_change(a_sessions, b_sessions)},
        "extraordinary": {
            "cycles": {"a": a_extra_cycles, "b": b_extra_cycles, "pct": pct_change(a_extra_cycles, b_extra_cycles)},
            "minutes": {"a": a_extra_minutes, "b": b_extra_minutes, "pct": pct_change(a_extra_minutes, b_extra_minutes)},
        }
    }


def compare_months(a_ref: date_, b_ref: date_) -> dict:
    a, b = get_month(a_ref), get_month(b_ref)
    a_cycles, a_minutes = _period_focus_totals(a)
    b_cycles, b_minutes = _period_focus_totals(b)

    a_active, a_sessions = _period_active_days_and_sessions(a)
    b_active, b_sessions = _period_active_days_and_sessions(b)

    a_extra_cycles, a_extra_minutes = _period_extraordinary_totals(a)
    b_extra_cycles, b_extra_minutes = _period_extraordinary_totals(b)

    return {
        "a": {"label": f"{a['start_date']} — {a['end_date']}", "raw": a},
        "b": {"label": f"{b['start_date']} — {b['end_date']}", "raw": b},
        "cycles": {"a": a_cycles, "b": b_cycles, "pct": pct_change(a_cycles, b_cycles)},
        "minutes": {"a": a_minutes, "b": b_minutes, "pct": pct_change(a_minutes, b_minutes)},
        "active_days": {"a": a_active, "b": b_active, "pct": pct_change(a_active, b_active)},
        "sessions": {"a": a_sessions, "b": b_sessions, "pct": pct_change(a_sessions, b_sessions)},
        "extraordinary": {
            "cycles": {"a": a_extra_cycles, "b": b_extra_cycles, "pct": pct_change(a_extra_cycles, b_extra_cycles)},
            "minutes": {"a": a_extra_minutes, "b": b_extra_minutes, "pct": pct_change(a_extra_minutes, b_extra_minutes)},
        }
    }


# ---------------------------------------------------------------------------
# CAMADA 3 — ANÁLISE (Fase 3, implementada)
# ---------------------------------------------------------------------------

def get_std_dev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


def get_portuguese_month_name(month: int) -> str:
    return {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
    }[month]


def get_max_streak_for_condition(dailies: list[Daily], condition_fn) -> dict:
    best_len = 0
    best_start = None
    best_end = None

    curr_len = 0
    curr_start = None
    prev_date = None

    for r in dailies:
        dt = r.date
        is_match = condition_fn(r)
        
        if is_match:
            if curr_len == 0:
                curr_len = 1
                curr_start = dt
            elif prev_date and dt == prev_date + timedelta(days=1):
                curr_len += 1
            else:
                if curr_len >= 2 and curr_len > best_len:
                    best_len = curr_len
                    best_start = curr_start
                    best_end = prev_date
                curr_len = 1
                curr_start = dt
            prev_date = dt
        else:
            if curr_len >= 2 and curr_len > best_len:
                best_len = curr_len
                best_start = curr_start
                best_end = prev_date
            curr_len = 0
            curr_start = None

    if curr_len >= 2 and curr_len > best_len:
        best_len = curr_len
        best_start = curr_start
        best_end = prev_date

    if best_len < 2:
        return {"length": 0, "start": None, "end": None}

    return {
        "length": best_len,
        "start": best_start.strftime("%d/%m/%Y") if best_start else None,
        "end": best_end.strftime("%d/%m/%Y") if best_end else None,
    }


def get_current_streak_for_condition(d: date_, condition_fn) -> int:
    rows = Daily.query.filter(Daily.date <= d).order_by(Daily.date.desc()).all()
    streak = 0
    curr = d
    for r in rows:
        if r.date == curr:
            if condition_fn(r):
                streak += 1
                curr -= timedelta(days=1)
            else:
                break
        else:
            break
    return streak if streak >= 2 else 0


def get_global_analysis() -> dict:
    dailies = Daily.query.all()
    weeks = Week.query.all()
    months = Month.query.all()
    
    # 1. Best Day & Extraordinary Day
    best_day_rec = None
    best_day_minutes = -1
    best_day_cycles = 0
    best_day_start_time = None
    
    extra_day_rec = None
    extra_day_cycles = -1
    extra_day_minutes = 0
    
    for d in dailies:
        cycles = 0
        minutes = 0
        for c in (d.cycle_contexts or []):
            cycles += c.get("focus", {}).get("cycles_completed", 0)
            minutes += c.get("focus", {}).get("minutes_completed", 0)
        
        if minutes > best_day_minutes:
            best_day_minutes = minutes
            best_day_cycles = cycles
            best_day_rec = d
            best_day_start_time = d.session.get("started_at")[11:16] if d.session and d.session.get("started_at") else None
            
        if cycles > extra_day_cycles:
            extra_day_cycles = cycles
            extra_day_minutes = minutes
            extra_day_rec = d
            
    best_day_data = None
    if best_day_rec:
        best_day_data = {
            "date": best_day_rec.date,
            "date_str": best_day_rec.date.strftime("%d/%m/%Y"),
            "minutes": best_day_minutes,
            "cycles": best_day_cycles,
            "start_time": best_day_start_time
        }
        
    extra_day_data = None
    if extra_day_rec:
        extra_day_data = {
            "date": extra_day_rec.date,
            "date_str": extra_day_rec.date.strftime("%d/%m/%Y"),
            "cycles": extra_day_cycles,
            "minutes": extra_day_minutes
        }
        
    # 2. Best Week
    best_week_rec = None
    best_week_minutes = -1
    best_week_cycles = 0
    
    for w in weeks:
        w_minutes = w.totals.get("focus", {}).get("minutes_completed", 0)
        w_cycles = w.totals.get("focus", {}).get("cycles_completed", 0)
        if w_minutes > best_week_minutes:
            best_week_minutes = w_minutes
            best_week_cycles = w_cycles
            best_week_rec = w
            
    best_week_data = None
    if best_week_rec:
        best_week_data = {
            "start_date": best_week_rec.start_date,
            "end_date": best_week_rec.end_date,
            "label": f"{best_week_rec.start_date.strftime('%d/%m/%Y')} a {best_week_rec.end_date.strftime('%d/%m/%Y')}",
            "minutes": best_week_minutes,
            "cycles": best_week_cycles
        }
        
    # 3. Best Month
    best_month_rec = None
    best_month_minutes = -1
    best_month_cycles = 0
    
    for m in months:
        m_minutes = m.totals.get("focus", {}).get("minutes_completed", 0)
        m_cycles = m.totals.get("focus", {}).get("cycles_completed", 0)
        if m_minutes > best_month_minutes:
            best_month_minutes = m_minutes
            best_month_cycles = m_cycles
            best_month_rec = m
            
    best_month_data = None
    if best_month_rec:
        best_month_data = {
            "start_date": best_month_rec.start_date,
            "end_date": best_month_rec.end_date,
            "label": f"{get_portuguese_month_name(best_month_rec.start_date.month)}/{best_month_rec.start_date.year}",
            "minutes": best_month_minutes,
            "cycles": best_month_cycles
        }
        
    # 4. Consistency: Most Consistent Week & Month
    consistent_week_rec = None
    consistent_week_std = float("inf")
    consistent_week_avg = 0.0
    
    for w in weeks:
        w_minutes = w.totals.get("focus", {}).get("minutes_completed", 0)
        if w_minutes > 0:
            daily_vals = []
            minutes_by_date = {}
            w_dailies = Daily.query.filter(Daily.date >= w.start_date, Daily.date <= w.end_date).all()
            for d in w_dailies:
                m = sum(c.get("focus", {}).get("minutes_completed", 0) for c in (d.cycle_contexts or []))
                minutes_by_date[d.date] = m
            for i in range(7):
                dt = w.start_date + timedelta(days=i)
                daily_vals.append(minutes_by_date.get(dt, 0.0))
            std_dev = get_std_dev(daily_vals)
            if std_dev < consistent_week_std:
                consistent_week_std = std_dev
                consistent_week_rec = w
                consistent_week_avg = w_minutes / 7.0
                
    consistent_week_data = None
    if consistent_week_rec:
        consistent_week_data = {
            "start_date": consistent_week_rec.start_date,
            "end_date": consistent_week_rec.end_date,
            "label": f"{consistent_week_rec.start_date.strftime('%d/%m/%Y')} a {consistent_week_rec.end_date.strftime('%d/%m/%Y')}",
            "avg": consistent_week_avg,
            "std_dev": consistent_week_std
        }
        
    consistent_month_rec = None
    consistent_month_std = float("inf")
    consistent_month_avg = 0.0
    
    for m in months:
        m_minutes = m.totals.get("focus", {}).get("minutes_completed", 0)
        if m_minutes > 0:
            num_days = (m.end_date - m.start_date).days + 1
            daily_vals = []
            minutes_by_date = {}
            m_dailies = Daily.query.filter(Daily.date >= m.start_date, Daily.date <= m.end_date).all()
            for d in m_dailies:
                m_val = sum(c.get("focus", {}).get("minutes_completed", 0) for c in (d.cycle_contexts or []))
                minutes_by_date[d.date] = m_val
            for i in range(num_days):
                dt = m.start_date + timedelta(days=i)
                daily_vals.append(minutes_by_date.get(dt, 0.0))
            std_dev = get_std_dev(daily_vals)
            if std_dev < consistent_month_std:
                consistent_month_std = std_dev
                consistent_month_rec = m
                consistent_month_avg = m_minutes / float(num_days)
                
    consistent_month_data = None
    if consistent_month_rec:
        num_days = (consistent_month_rec.end_date - consistent_month_rec.start_date).days + 1
        consistent_month_data = {
            "start_date": consistent_month_rec.start_date,
            "end_date": consistent_month_rec.end_date,
            "label": f"{get_portuguese_month_name(consistent_month_rec.start_date.month)}/{consistent_month_rec.start_date.year}",
            "avg": consistent_month_avg,
            "std_dev": consistent_month_std
        }
        
    # 5. Ideal Week & Month
    best_ideal_week_rec = None
    best_ideal_week_count = -1
    
    for w in weeks:
        ideal_count = w.rewards.get("daily_ideal", {}).get("completed_count", 0)
        if ideal_count > best_ideal_week_count:
            best_ideal_week_count = ideal_count
            best_ideal_week_rec = w
            
    best_ideal_week_data = None
    if best_ideal_week_rec:
        best_ideal_week_data = {
            "start_date": best_ideal_week_rec.start_date,
            "end_date": best_ideal_week_rec.end_date,
            "label": f"{best_ideal_week_rec.start_date.strftime('%d/%m/%Y')} a {best_ideal_week_rec.end_date.strftime('%d/%m/%Y')}",
            "count": best_ideal_week_count,
            "total": 7
        }
        
    best_ideal_month_rec = None
    best_ideal_month_count = -1
    
    for m in months:
        ideal_count = m.rewards.get("daily_ideal", {}).get("completed_count", 0)
        if ideal_count > best_ideal_month_count:
            best_ideal_month_count = ideal_count
            best_ideal_month_rec = m
            
    best_ideal_month_data = None
    if best_ideal_month_rec:
        num_days = (best_ideal_month_rec.end_date - best_ideal_month_rec.start_date).days + 1
        best_ideal_month_data = {
            "start_date": best_ideal_month_rec.start_date,
            "end_date": best_ideal_month_rec.end_date,
            "label": f"{get_portuguese_month_name(best_ideal_month_rec.start_date.month)}/{best_ideal_month_rec.start_date.year}",
            "count": best_ideal_month_count,
            "total": num_days
        }
        
    # 6. Global Streaks
    sorted_dailies = sorted(dailies, key=lambda r: r.date)
    
    active_streak = get_max_streak_for_condition(sorted_dailies, lambda r: r.session_started)
    min_streak = get_max_streak_for_condition(sorted_dailies, lambda r: bool(r.rewards.get("daily_minimum", {}).get("goal_completed")))
    ideal_streak = get_max_streak_for_condition(sorted_dailies, lambda r: bool(r.rewards.get("daily_ideal", {}).get("goal_completed")))
    extra_streak = get_max_streak_for_condition(
        sorted_dailies, 
        lambda r: sum(c.get("extraordinary", {}).get("cycles", 0) for c in (r.cycle_contexts or [])) > 0
    )
    
    today_dt = clock.today()
    current_active = get_current_streak_for_condition(today_dt, lambda r: r.session_started)
    current_min = get_current_streak_for_condition(today_dt, lambda r: bool(r.rewards.get("daily_minimum", {}).get("goal_completed")))
    current_ideal = get_current_streak_for_condition(today_dt, lambda r: bool(r.rewards.get("daily_ideal", {}).get("goal_completed")))
    
    return {
        "best_day": best_day_data,
        "extraordinary_day": extra_day_data,
        "best_week": best_week_data,
        "best_month": best_month_data,
        "consistent_week": consistent_week_data,
        "consistent_month": consistent_month_data,
        "ideal_week": best_ideal_week_data,
        "ideal_month": best_ideal_month_data,
        "streaks": {
            "current_active": current_active,
            "current_minimum": current_min,
            "current_ideal": current_ideal,
            "best_active": active_streak,
            "best_minimum": min_streak,
            "best_ideal": ideal_streak,
            "best_extraordinary": extra_streak
        }
    }


def get_period_analysis(scale: str, ref_date: date_) -> dict | None:
    if scale == "day":
        return None
        
    if scale == "week":
        week = week_service.rebuild_week_for_date(ref_date, final=False, commit=True)
        # Calculate daily values
        daily_vals = []
        minutes_by_date = {}
        w_dailies = Daily.query.filter(Daily.date >= week.start_date, Daily.date <= week.end_date).all()
        for d in w_dailies:
            m = sum(c.get("focus", {}).get("minutes_completed", 0) for c in (d.cycle_contexts or []))
            minutes_by_date[d.date] = m
        for i in range(7):
            dt = week.start_date + timedelta(days=i)
            daily_vals.append(minutes_by_date.get(dt, 0.0))
            
        std_dev = get_std_dev(daily_vals)
        ideal_count = week.rewards.get("daily_ideal", {}).get("completed_count", 0)
        avg_minutes = sum(daily_vals) / 7.0
        
        return {
            "label": f"{week.start_date.strftime('%d/%m/%Y')} a {week.end_date.strftime('%d/%m/%Y')}",
            "std_dev": std_dev,
            "ideal_count": ideal_count,
            "total_days": 7,
            "avg_minutes": avg_minutes,
            "avg": avg_minutes
        }
        
    if scale == "month":
        month = month_service.rebuild_month_for_date(ref_date, final=False, commit=True)
        num_days = (month.end_date - month.start_date).days + 1
        daily_vals = []
        minutes_by_date = {}
        m_dailies = Daily.query.filter(Daily.date >= month.start_date, Daily.date <= month.end_date).all()
        for d in m_dailies:
            m_val = sum(c.get("focus", {}).get("minutes_completed", 0) for c in (d.cycle_contexts or []))
            minutes_by_date[d.date] = m_val
        for i in range(num_days):
            dt = month.start_date + timedelta(days=i)
            daily_vals.append(minutes_by_date.get(dt, 0.0))
            
        std_dev = get_std_dev(daily_vals)
        ideal_count = month.rewards.get("daily_ideal", {}).get("completed_count", 0)
        avg_minutes = sum(daily_vals) / float(num_days)
        
        return {
            "label": f"{get_portuguese_month_name(month.start_date.month)}/{month.start_date.year}",
            "std_dev": std_dev,
            "ideal_count": ideal_count,
            "total_days": num_days,
            "avg_minutes": avg_minutes,
            "avg": avg_minutes
        }


def calendar_heatmap(end: date_, weeks: int = 46, mode: str = "cycles") -> list[list[dict]]:
    """
    Grade [semana][dia da semana] para o heatmap do corpo da página.
    mode: 'cycles' | 'minutes' — decide qual métrica define o nível de intensidade.
    """
    from app.models import DailyIdealProgress

    start_w, end_w = week_bounds(end)
    start_date = start_w - timedelta(weeks=weeks - 1)

    # Query all Daily rows in range in one go
    daily_rows = Daily.query.filter(Daily.date >= start_date, Daily.date <= end_w).all()
    daily_map = {row.date: row for row in daily_rows}

    # Query DailyIdealProgress to know which days completed the ideal goal
    ideal_rows = DailyIdealProgress.query.filter(
        DailyIdealProgress.date >= start_date,
        DailyIdealProgress.date <= end_w,
        DailyIdealProgress.status == "completed"
    ).all()
    ideal_dates = {row.date for row in ideal_rows}

    total_days = weeks * 7
    all_dates = [start_date + timedelta(days=i) for i in range(total_days)]

    cells_data = {}
    values_for_level = []

    for dt in all_dates:
        if dt in daily_map:
            row = daily_map[dt]
            has_session = row.session_started
            if has_session:
                cycles = sum(c.get("focus", {}).get("cycles_completed", 0) for c in (row.cycle_contexts or []))
                minutes = sum(c.get("focus", {}).get("minutes_completed", 0) for c in (row.cycle_contexts or []))
                extraordinary = any(c.get("extraordinary", {}).get("cycles", 0) > 0 for c in (row.cycle_contexts or []))
            else:
                cycles = 0
                minutes = 0
                extraordinary = False
        else:
            has_session = False
            cycles = 0
            minutes = 0
            extraordinary = False

        cells_data[dt] = {
            "date": dt.isoformat(),
            "has_session": has_session,
            "cycles": cycles,
            "minutes": minutes,
            "extraordinary": extraordinary,
            "ideal_completed": dt in ideal_dates,
        }
        if has_session:
            val = cycles if mode == "cycles" else minutes
            values_for_level.append(val)

    max_val = max(values_for_level) if values_for_level else 0

    # Assign levels (1 to 4) when has_session is True, otherwise 0
    for dt, cell in cells_data.items():
        if cell["has_session"]:
            val = cell["cycles"] if mode == "cycles" else cell["minutes"]
            if max_val == 0:
                level = 1
            else:
                pct = val / max_val
                if pct <= 0.25:
                    level = 1
                elif pct <= 0.50:
                    level = 2
                elif pct <= 0.75:
                    level = 3
                else:
                    level = 4
            cell["level"] = level
        else:
            cell["level"] = 0

    # Group into weeks alinhado a segunda-feira
    grid = []
    for w in range(weeks):
        week_list = []
        for d in range(7):
            date_idx = w * 7 + d
            dt = all_dates[date_idx]
            week_list.append(cells_data[dt])
        grid.append(week_list)

    return grid

