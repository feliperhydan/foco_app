"""
Serviço de Progresso (manual, seção 8–13).

Contém:
  - funções de leitura "somente snapshot" (não gravam nada), usadas
    pela Home para exibir o estado do dia sem criar linhas
    prematuramente no banco;
  - funções `get_or_create_*`, usadas SÓ pelo motor de conclusão
    (engine.py) no momento em que um ciclo é de fato contabilizado;
  - `apply_cycle_completion`, chamada uma única vez pelo motor de
    conclusão — é o único lugar do sistema que incrementa contadores
    de progresso (manual, seção 17: fluxo centralizado).
"""
from dataclasses import dataclass
from datetime import date as date_, timedelta

from app.extensions import db
from app.models import (
    DailyMinimumProgress, DailyIdealProgress, ExtraordinaryProgress,
    WeeklyProgress, AbsoluteProgress, AbsoluteProgressDailyLog,
)
from app.services.config_service import get_current_configuration


def week_bounds(d: date_) -> tuple[date_, date_]:
    """Semana de segunda a domingo contendo a data `d`."""
    start = d - timedelta(days=d.weekday())
    end = start + timedelta(days=6)
    return start, end


# --- leitura sem efeito colateral (para exibição) ------------------------

@dataclass
class ProgressSnapshot:
    goal: int
    current_count: int
    status: str
    configuration_focus_minutes: int
    exists: bool  # False = a linha ainda não existe no banco (dia/semana sem atividade)

    @property
    def pct(self) -> int:
        if self.goal <= 0:
            return 0
        return min(100, round(100 * self.current_count / self.goal))


def get_daily_minimum_snapshot(d: date_) -> ProgressSnapshot:
    row = DailyMinimumProgress.query.filter_by(date=d).first()
    if row:
        focus_minutes = row.configuration.focus_minutes if row.configuration else get_current_configuration().focus_minutes
        return ProgressSnapshot(row.goal, row.current_count, row.status, focus_minutes, True)
    cfg = get_current_configuration()
    return ProgressSnapshot(cfg.daily_minimum_goal, 0, "pending", cfg.focus_minutes, False)


def get_daily_ideal_snapshot(d: date_) -> ProgressSnapshot:
    row = DailyIdealProgress.query.filter_by(date=d).first()
    if row:
        focus_minutes = row.configuration.focus_minutes if row.configuration else get_current_configuration().focus_minutes
        return ProgressSnapshot(row.goal, row.current_count, row.status, focus_minutes, True)
    cfg = get_current_configuration()
    return ProgressSnapshot(cfg.daily_ideal_goal, 0, "pending", cfg.focus_minutes, False)


def get_extraordinary_snapshot(d: date_) -> ExtraordinaryProgress | None:
    """None = ainda não desbloqueado. A AUSÊNCIA da linha é o estado 'oculto'."""
    return ExtraordinaryProgress.query.filter_by(date=d).first()


def get_weekly_snapshot(d: date_) -> ProgressSnapshot:
    start, end = week_bounds(d)
    row = WeeklyProgress.query.filter_by(week_start=start, week_end=end).first()
    if row:
        focus_minutes = row.configuration.focus_minutes if row.configuration else get_current_configuration().focus_minutes
        return ProgressSnapshot(row.goal, row.current_count, row.status, focus_minutes, True)
    cfg = get_current_configuration()
    return ProgressSnapshot(cfg.weekly_goal, 0, "pending", cfg.focus_minutes, False)


def get_active_absolute() -> AbsoluteProgress | None:
    return (
        AbsoluteProgress.query.filter_by(status="active")
        .order_by(AbsoluteProgress.started_at.asc())
        .first()
    )


# --- get_or_create (só usadas pelo motor de conclusão) --------------------

def _get_or_create_daily_minimum(d: date_, cfg) -> DailyMinimumProgress:
    row = DailyMinimumProgress.query.filter_by(date=d).first()
    if row is None:
        row = DailyMinimumProgress(date=d, goal=cfg.daily_minimum_goal, current_count=0, configuration_id=cfg.id)
        db.session.add(row)
        db.session.flush()
    return row


def _get_or_create_daily_ideal(d: date_, cfg) -> DailyIdealProgress:
    row = DailyIdealProgress.query.filter_by(date=d).first()
    if row is None:
        row = DailyIdealProgress(date=d, goal=cfg.daily_ideal_goal, current_count=0, configuration_id=cfg.id)
        db.session.add(row)
        db.session.flush()
    return row


def _get_or_create_weekly(d: date_, cfg) -> WeeklyProgress:
    start, end = week_bounds(d)
    row = WeeklyProgress.query.filter_by(week_start=start, week_end=end).first()
    if row is None:
        row = WeeklyProgress(week_start=start, week_end=end, goal=cfg.weekly_goal, current_count=0, configuration_id=cfg.id)
        db.session.add(row)
        db.session.flush()
    return row


# --- motor de progresso ----------------------------------------------------

def apply_cycle_completion(cycle) -> dict:
    """
    Aplica os efeitos de UM FocusCycle recém-concluído sobre todas as
    entidades de progresso (manual, seção 6 e 17). Chamada exatamente
    uma vez por ciclo, pelo motor de conclusão em `engine.py`, dentro
    da mesma transação que marca o ciclo como 'completed'.

    Retorna um resumo usado pela tela pós-ciclo (seção 19 do briefing
    visual) para saber o que mudou: mínimo bateu? ideal bateu?
    extraordinário nasceu agora ou só cresceu? etc.
    """
    cfg = cycle.configuration  # config vigente NO MOMENTO em que o ciclo foi iniciado
    d = cycle.completed_at.date()

    result = {
        "daily_minimum_just_completed": False,
        "daily_ideal_just_completed": False,
        "extraordinary_just_unlocked": False,
        "weekly_just_completed": False,
        "absolute_just_completed": False,
        "extraordinary_cycles": 0,
    }

    # 1) mínimo
    daily_min = _get_or_create_daily_minimum(d, cfg)
    daily_min.current_count += 1
    if daily_min.status == "pending" and daily_min.current_count >= daily_min.goal:
        daily_min.status = "completed"
        daily_min.completed_at = cycle.completed_at
        result["daily_minimum_just_completed"] = True

    # 2) ideal
    daily_ideal = _get_or_create_daily_ideal(d, cfg)
    was_ideal_completed_before = daily_ideal.status == "completed"
    daily_ideal.current_count += 1
    if daily_ideal.status == "pending" and daily_ideal.current_count >= daily_ideal.goal:
        daily_ideal.status = "completed"
        daily_ideal.completed_at = cycle.completed_at
        result["daily_ideal_just_completed"] = True
    db.session.flush()

    # 3) extraordinário — só existe a partir do instante em que o ideal
    #    já estava completo ANTES deste ciclo (ou seja: este é o
    #    primeiro ciclo *além* da meta ideal, não o ciclo que a fechou)
    if was_ideal_completed_before or (
        daily_ideal.status == "completed" and daily_ideal.current_count > daily_ideal.goal
    ):
        extra = ExtraordinaryProgress.query.filter_by(date=d).first()
        just_unlocked = extra is None
        if extra is None:
            extra = ExtraordinaryProgress(
                date=d, daily_ideal_id=daily_ideal.id, configuration_id=cfg.id,
                extra_cycles=0, extra_minutes=0,
            )
            db.session.add(extra)
        extra.extra_cycles += 1
        extra.extra_minutes += cycle.focus_duration_minutes
        result["extraordinary_just_unlocked"] = just_unlocked
        result["extraordinary_cycles"] = extra.extra_cycles

    # 4) semanal
    weekly = _get_or_create_weekly(d, cfg)
    weekly.current_count += 1
    if weekly.status == "pending" and weekly.current_count >= weekly.goal:
        weekly.status = "completed"
        weekly.completed_at = cycle.completed_at
        result["weekly_just_completed"] = True

    # 5) objetivo absoluto ativo (no máximo um por vez, por regra de produto)
    absolute = get_active_absolute()
    if absolute is not None:
        # --- AbsoluteProgressDailyLog: registra start/end por dia ---
        log = AbsoluteProgressDailyLog.query.filter_by(
            date=d, absolute_progress_id=absolute.id
        ).first()
        if log is None:
            # Primeiro incremento do dia: congela start_count antes de alterar
            log = AbsoluteProgressDailyLog(
                date=d,
                absolute_progress_id=absolute.id,
                start_count=absolute.current_count,
                end_count=absolute.current_count,
            )
            db.session.add(log)
            db.session.flush()

        absolute.current_count += 1
        if absolute.current_count >= absolute.goal_cycles:
            absolute.current_count = absolute.goal_cycles  # nunca passa da meta (seção 13)
            absolute.status = "completed"
            absolute.completed_at = cycle.completed_at
            result["absolute_just_completed"] = True

        # Atualiza end_count com o valor pós-incremento
        log.end_count = absolute.current_count
        db.session.flush()

    result["daily_minimum"] = daily_min
    result["daily_ideal"] = daily_ideal
    result["weekly"] = weekly
    result["absolute"] = absolute

    return result
