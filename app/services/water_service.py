from datetime import date as date_, datetime, time as time_

from app.extensions import db
from app.models import WaterLog
from app.services.config_service import get_current_configuration, get_configuration_at
from app.services.clock import now, today

"""Serviço de Hidratação (manual, seção 28)."""

def log_bottle() -> WaterLog:
    """Registra manualmente +1 garrafa. O volume é um snapshot da configuração vigente (nunca inferido)."""
    cfg = get_current_configuration()
    entry = WaterLog(date=today(), volume_ml=cfg.water_bottle_ml, configuration_id=cfg.id)
    db.session.add(entry)
    from app.services import daily_service
    daily_service.consolidate_daily(today(), commit=False)
    db.session.commit()
    return entry


def daily_total_ml(d: date_) -> int:
    rows = WaterLog.query.filter_by(date=d).all()
    return sum(r.volume_ml for r in rows)


def daily_summary(d: date_) -> dict:
    if d > today():
        cfg = get_current_configuration()
    elif d == today():
        cfg = get_configuration_at(now())
    else:
        cfg = get_configuration_at(datetime.combine(d, time_(23, 59, 59, 999999)))
    total_ml = daily_total_ml(d)
    return {
        "total_ml": total_ml,
        "total_l": round(total_ml / 1000, 2),
        "goal_ml": cfg.water_goal_ml,
        "goal_l": round(cfg.water_goal_ml / 1000, 2),
        "bottle_ml": cfg.water_bottle_ml,
        "bottles_logged": total_ml // cfg.water_bottle_ml if cfg.water_bottle_ml else 0,
        "bottles_to_goal": round(cfg.water_goal_ml / cfg.water_bottle_ml, 2) if cfg.water_bottle_ml else 0,
        "pct": min(100, round(100 * total_ml / cfg.water_goal_ml)) if cfg.water_goal_ml else 0,
    }
