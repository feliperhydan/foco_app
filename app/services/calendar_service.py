"""
Serviço de Calendário de Atividade (manual, seção 23).

Uma única fonte de atividade (FocusCycle concluídos, agrupados por
dia) com duas interpretações — ciclos ou minutos — nunca dois
calendários independentes.
"""
from datetime import date as date_, timedelta
from sqlalchemy import func

from app.extensions import db
from app.models import FocusCycle
from app.services.clock import today


def daily_activity(start: date_, end: date_) -> dict[date_, dict]:
    """
    Retorna {data: {"cycles": N, "minutes": N}} para o intervalo
    [start, end], derivado diretamente de FocusCycle.completed_at —
    dias sem nenhum ciclo simplesmente não aparecem no dict (o
    chamador decide como tratar ausência: intensidade 0).
    """
    rows = (
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
        .all()
    )
    return {
        date_.fromisoformat(r.day): {"cycles": r.cycles, "minutes": int(r.minutes or 0)}
        for r in rows
    }


def heatmap_grid(weeks: int = 18, mode: str = "cycles", end: date_ | None = None) -> list[list[dict]]:
    """
    Monta uma grade [semana][dia da semana] pronta para renderizar,
    com um nível de intensidade 0–4 calculado por quantil simples
    sobre os valores observados no período.
    """
    end = end or today()
    start = end - timedelta(weeks=weeks, days=end.weekday())
    activity = daily_activity(start, end)

    values = [v[mode] for v in activity.values() if v[mode] > 0]
    values.sort()

    def level(v: int) -> int:
        if v <= 0 or not values:
            return 0
        # quartis simples sobre os dias com atividade
        idx = int(len(values) * 0.99)
        vmax = values[min(idx, len(values) - 1)] or 1
        ratio = v / vmax
        if ratio <= 0.25:
            return 1
        if ratio <= 0.5:
            return 2
        if ratio <= 0.75:
            return 3
        return 4

    grid = []
    cur = start
    for _ in range(weeks):
        col = []
        for _d in range(7):
            act = activity.get(cur, {"cycles": 0, "minutes": 0})
            val = act[mode]
            col.append({"date": cur.isoformat(), "value": val, "level": level(val)})
            cur += timedelta(days=1)
        grid.append(col)
    return grid
