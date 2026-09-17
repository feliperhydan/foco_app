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

from app.models import Daily
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
    consolidados, `consolidate_daily` é um no-op (retorna na hora).
    """
    if d <= clock.today():
        daily_service.consolidate_daily(d, commit=True)
    row = Daily.query.filter_by(date=d).first()
    if row is None:
        return {"date": d.isoformat(), "empty": True, "session_started": False}
    data = row.as_dict()
    data["empty"] = not data["session_started"]
    return data


def get_week(d: date_) -> dict:
    """Dados agregados da semana que contém `d`, sempre via Week (nunca recomputado à mão)."""
    week = week_service.rebuild_week_for_date(d, final=False, commit=True)
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
    }


def get_month(d: date_) -> dict:
    """Dados agregados do mês que contém `d`, sempre via Month."""
    month = month_service.rebuild_month_for_date(d, final=False, commit=True)
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


def compare_days(a_date: date_, b_date: date_) -> dict:
    """A = mais antigo, B = mais recente — nunca a ordem inversa (seção 7)."""
    a, b = get_day(a_date), get_day(b_date)
    a_cycles, a_minutes = _day_focus_totals(a)
    b_cycles, b_minutes = _day_focus_totals(b)
    return {
        "a": {"date": a_date.isoformat(), "raw": a},
        "b": {"date": b_date.isoformat(), "raw": b},
        "cycles": {"a": a_cycles, "b": b_cycles, "pct": pct_change(a_cycles, b_cycles)},
        "minutes": {"a": a_minutes, "b": b_minutes, "pct": pct_change(a_minutes, b_minutes)},
    }


def _period_focus_totals(period: dict) -> tuple[int, int]:
    focus = (period.get("totals") or {}).get("focus", {})
    return focus.get("cycles_completed", 0), focus.get("minutes_completed", 0)


def compare_weeks(a_ref: date_, b_ref: date_) -> dict:
    a, b = get_week(a_ref), get_week(b_ref)
    a_cycles, a_minutes = _period_focus_totals(a)
    b_cycles, b_minutes = _period_focus_totals(b)
    return {
        "a": {"label": f"{a['start_date']} — {a['end_date']}", "raw": a},
        "b": {"label": f"{b['start_date']} — {b['end_date']}", "raw": b},
        "cycles": {"a": a_cycles, "b": b_cycles, "pct": pct_change(a_cycles, b_cycles)},
        "minutes": {"a": a_minutes, "b": b_minutes, "pct": pct_change(a_minutes, b_minutes)},
    }


def compare_months(a_ref: date_, b_ref: date_) -> dict:
    a, b = get_month(a_ref), get_month(b_ref)
    a_cycles, a_minutes = _period_focus_totals(a)
    b_cycles, b_minutes = _period_focus_totals(b)
    return {
        "a": {"label": f"{a['start_date']} — {a['end_date']}", "raw": a},
        "b": {"label": f"{b['start_date']} — {b['end_date']}", "raw": b},
        "cycles": {"a": a_cycles, "b": b_cycles, "pct": pct_change(a_cycles, b_cycles)},
        "minutes": {"a": a_minutes, "b": b_minutes, "pct": pct_change(a_minutes, b_minutes)},
    }


# ---------------------------------------------------------------------------
# CAMADA 3 — ANÁLISE (Fase 3, ainda não implementada)
# ---------------------------------------------------------------------------
# TODO(fase-3): melhor_dia / dia_extraordinario / melhor_semana /
# semana_mais_consistente / semana_ideal / melhor_mes / mes_mais_consistente
# / sequências. Cada definição já está fixada no prompt de implementação
# (seção 4) — não inventar critério na hora de implementar. Consistência
# exige desvio padrão sobre os dias do período (seção 4); médias de
# período devem sempre dividir pelo número de dias do período, nunca só
# pelos dias ativos (seção 6) — nenhuma função deste módulo faz essa
# divisão ainda, de propósito, para essa regra não ser esquecida/violada
# por engano numa implementação apressada.
