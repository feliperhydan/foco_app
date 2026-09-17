"""
Serviço de debug.

Centraliza ações de teste que ajudam a validar o site sem depender do
tempo real: avançar o relógio do app, resetar o relógio, simular a
conclusão de ciclos e gerar histórico fictício para estatísticas.
"""
from datetime import date as date_, datetime, timedelta, time as time_

from app.extensions import db
from app.models import (
    AbsoluteProgress,
    AbsoluteProgressDailyLog,
    Configuration,
    Daily,
    DebugState,
    Session,
    FocusCycle,
    Reward,
    RewardAchievement,
    WaterLog,
    DailyMinimumProgress,
    DailyIdealProgress,
    ExtraordinaryProgress,
    Month,
    Week,
    WeeklyProgress,
)
from app.services.config_service import get_current_configuration
from app.services.clock import advance_days as advance_clock_days, reset as reset_clock, today
from app.services import cycles_service, daily_service, engine, progress_service, rewards_service
from app.services.progress_service import week_bounds
from app.services import week_service, month_service


def advance_time(days: int = 1):
    state = advance_clock_days(days)
    return {"offset_days": state.clock_offset_days, "today": today()}


def reset_time():
    state = reset_clock()
    return {"offset_days": state.clock_offset_days, "today": today()}


def simulate_cycles(count: int = 1, title: str = "Debug cycle") -> dict:
    count = max(1, min(50, count))
    title = (title or "Debug cycle").strip()[:280]

    last_result = None
    for _ in range(count):
        cycle = cycles_service.start_focus_cycle(title=title)
        last_result = engine.complete_focus_cycle(cycle.id, title=title)

    return {"count": count, "today": today(), "last_result": last_result}


def complete_day_goal(target: str = "ideal") -> dict:
    """
    Gera o número de ciclos necessário para fechar a meta diária
    selecionada no dia atual.
    """
    current_day = today()
    cfg = get_current_configuration()
    if target == "minimum":
        snapshot = progress_service.get_daily_minimum_snapshot(current_day)
        goal = cfg.daily_minimum_goal
    else:
        snapshot = progress_service.get_daily_ideal_snapshot(current_day)
        goal = cfg.daily_ideal_goal

    needed = max(0, goal - snapshot.current_count)
    if needed == 0:
        return {
            "target": target,
            "goal": goal,
            "current": snapshot.current_count,
            "needed": 0,
            "today": current_day,
            "result": None,
        }

    result = simulate_cycles(count=needed, title=f"Debug {target} goal")
    return {
        "target": target,
        "goal": goal,
        "current": snapshot.current_count,
        "needed": needed,
        "today": current_day,
        "result": result,
    }


def jump_to_next_week() -> dict:
    """
    Avança o relógio do app até a próxima segunda-feira.
    """
    current_day = today()
    days = 7 - current_day.weekday()
    state = advance_clock_days(days)
    return {"offset_days": state.clock_offset_days, "today": today(), "days_advanced": days}


def _create_historical_session(day, cycles_count: int, title_prefix: str) -> None:
    cfg = get_current_configuration()
    session = Session(
        date=day,
        started_at=datetime.combine(day, time_(9, 0)),
        ended_at=datetime.combine(day, time_(18, 0)),
        status="ended",
    )
    db.session.add(session)
    db.session.flush()

    for index in range(cycles_count):
        completed_at = datetime.combine(day, time_(9, 0)) + timedelta(minutes=(index + 1) * (cfg.focus_minutes + 10))
        started_at = completed_at - timedelta(minutes=cfg.focus_minutes)
        cycle = FocusCycle(
            session_id=session.id,
            configuration_id=cfg.id,
            started_at=started_at,
            completed_at=completed_at,
            focus_duration_minutes=cfg.focus_minutes,
            title=f"{title_prefix} {index + 1}"[:280],
            status="completed",
        )
        db.session.add(cycle)
        db.session.flush()
        progress_service.apply_cycle_completion(cycle)


def _ensure_active_reward(progress_type: str, title: str) -> None:
    """
    Garante ao menos uma recompensa ativa por tipo quando o banco ainda
    não tem dados suficientes para registrar conquistas.
    """
    existing = Reward.query.filter_by(progress_type=progress_type, active=True).first()
    if existing is not None:
        return
    db.session.add(Reward(title=title, progress_type=progress_type, active=True))


def _ensure_active_absolute(goal_cycles: int) -> AbsoluteProgress:
    absolute = progress_service.get_active_absolute()
    if absolute is not None:
        return absolute
    absolute = AbsoluteProgress(
        title="Objetivo fictício",
        description="Criado automaticamente pelo painel de debug.",
        goal_cycles=max(1, goal_cycles),
        current_count=0,
        status="active",
    )
    db.session.add(absolute)
    db.session.flush()
    return absolute


def _debug_state() -> DebugState | None:
    return DebugState.query.filter_by(name="clock").first()


def _mark_generated_range(start_day: date_, end_day: date_) -> None:
    state = _debug_state()
    if state is None:
        state = DebugState(name="clock", clock_offset_days=0)
        db.session.add(state)
        db.session.flush()
    state.test_data_start_date = start_day
    state.test_data_end_date = end_day
    state.test_data_generated_at = datetime.combine(end_day, time_(23, 59, 59))


def _generated_range() -> tuple[date_, date_] | None:
    state = _debug_state()
    if state is None or state.test_data_start_date is None or state.test_data_end_date is None:
        return None
    return state.test_data_start_date, state.test_data_end_date


def _build_historical_configuration(
    base_cfg: Configuration,
    valid_from: datetime,
    valid_to: datetime,
    *,
    focus_delta: int = 0,
    minimum_delta: int = 0,
    ideal_delta: int = 0,
    weekly_delta: int = 0,
    water_delta: int = 0,
) -> Configuration:
    daily_minimum_goal = max(1, base_cfg.daily_minimum_goal + minimum_delta)
    daily_ideal_goal = max(daily_minimum_goal + 1, base_cfg.daily_ideal_goal + ideal_delta)
    weekly_goal = max(daily_ideal_goal * 3, base_cfg.weekly_goal + weekly_delta)
    water_bottle_ml = max(250, base_cfg.water_bottle_ml + water_delta)
    water_goal_ml = max(water_bottle_ml, base_cfg.water_goal_ml + (water_delta * 4))

    cfg = Configuration(
        valid_from=valid_from,
        valid_to=valid_to,
        focus_minutes=max(15, base_cfg.focus_minutes + focus_delta),
        short_break_minutes=base_cfg.short_break_minutes,
        long_break_minutes=base_cfg.long_break_minutes,
        cycles_per_session=base_cfg.cycles_per_session,
        daily_minimum_goal=daily_minimum_goal,
        daily_ideal_goal=daily_ideal_goal,
        weekly_goal=weekly_goal,
        water_bottle_ml=water_bottle_ml,
        water_goal_ml=water_goal_ml,
        theme=base_cfg.theme,
        primary_color=base_cfg.primary_color,
        debug_tools_enabled=base_cfg.debug_tools_enabled,
    )
    db.session.add(cfg)
    db.session.flush()
    return cfg


def _complete_fictional_cycle(cycle: FocusCycle) -> dict:
    """
    Reaplica o fluxo real de conclusão para um ciclo histórico.
    """
    progress_result = progress_service.apply_cycle_completion(cycle)

    achieved = []
    d = cycle.completed_at.date()
    if progress_result["daily_minimum_just_completed"]:
        achieved += rewards_service.check_and_register_for_progress("daily_minimum", d)
    if progress_result["daily_ideal_just_completed"]:
        achieved += rewards_service.check_and_register_for_progress("daily_ideal", d)
    if progress_result["weekly_just_completed"]:
        weekly = progress_result["weekly"]
        achieved += rewards_service.check_and_register_for_progress(
            "weekly", d, start_date=weekly.week_start, end_date=weekly.week_end
        )
    if progress_result["absolute_just_completed"]:
        absolute = progress_result["absolute"]
        achieved += rewards_service.check_and_register_for_progress(
            "absolute", d, absolute_progress_id=absolute.id
        )
    return {"progress_result": progress_result, "achieved": achieved}


def generate_test_data(days: int = 7, cycles_per_day: int = 3, water_per_day: int = 2) -> dict:
    """
    Gera dados históricos artificiais em três faixas sem sobreposição:
    duas faixas antigas com perfis diferentes e, por fim, os últimos
    30 dias incluindo o dia atual. Isso mantém o histórico antigo
    disponível e também preenche o período recente usado na interface.
    """
    days = max(1, min(30, days))
    cycles_per_day = max(1, min(12, cycles_per_day))
    water_per_day = max(0, min(12, water_per_day))

    today_day = today()
    recent_end = today_day
    recent_start = recent_end - timedelta(days=29)
    middle_end = recent_start - timedelta(days=1)
    middle_start = middle_end - timedelta(days=29)
    older_end = middle_start - timedelta(days=1)
    older_start = older_end - timedelta(days=29)

    start_day = older_start
    end_day = recent_end
    base_cfg = get_current_configuration()

    _ensure_active_reward("daily_minimum", "Meta média fictícia")
    _ensure_active_reward("daily_ideal", "Meta ideal fictícia")
    _ensure_active_reward("weekly", "Meta semanal fictícia")
    _ensure_active_reward("absolute", "Objetivo absoluto fictício")
    generated_span_days = (end_day - start_day).days + 1
    absolute = _ensure_active_absolute(goal_cycles=max(16, generated_span_days * cycles_per_day // 3))

    older_valid_from = datetime.combine(older_start, time_(0, 0))
    older_valid_to = datetime.combine(middle_start, time_(0, 0))
    middle_valid_from = datetime.combine(middle_start, time_(0, 0))
    middle_valid_to = datetime.combine(recent_start, time_(0, 0))
    recent_valid_from = datetime.combine(recent_start, time_(0, 0))
    recent_valid_to = datetime.combine(recent_end + timedelta(days=1), time_(0, 0))

    older_cfg = _build_historical_configuration(
        base_cfg,
        older_valid_from,
        older_valid_to,
        focus_delta=-6,
        minimum_delta=-1,
        ideal_delta=-1,
        weekly_delta=-4,
        water_delta=-100,
    )
    middle_cfg = _build_historical_configuration(
        base_cfg,
        middle_valid_from,
        middle_valid_to,
        focus_delta=0,
        minimum_delta=0,
        ideal_delta=0,
        weekly_delta=0,
        water_delta=0,
    )
    recent_cfg = _build_historical_configuration(
        base_cfg,
        recent_valid_from,
        recent_valid_to,
        focus_delta=4,
        minimum_delta=1,
        ideal_delta=2,
        weekly_delta=5,
        water_delta=120,
    )

    historical_cfgs: list[tuple[date_, date_, Configuration, int]] = [
        (older_start, middle_start - timedelta(days=1), older_cfg, 0),
        (middle_start, recent_start - timedelta(days=1), middle_cfg, 1),
        (recent_start, recent_end, recent_cfg, 2),
    ]

    generated_days = []
    for offset in range((end_day - start_day).days + 1):
        day = start_day + timedelta(days=offset)
        cfg = base_cfg
        month_index = 0
        for start_range, end_range, candidate, candidate_month_index in historical_cfgs:
            if start_range <= day <= end_range:
                cfg = candidate
                month_index = candidate_month_index
                break

        # Cada faixa ganha um perfil diferente para os gráficos ficarem contrastantes.
        cycle_boost = (-1, 0, 2)[month_index]
        water_boost = (-1, 0, 1)[month_index]
        day_cycles = max(1, cycles_per_day + cycle_boost + (offset % 3) - 1)
        if month_index == 0 and offset % 4 == 1:
            day_cycles = max(day_cycles, cfg.daily_minimum_goal)
        if month_index == 1 and offset % 5 == 2:
            day_cycles = max(day_cycles, cfg.daily_minimum_goal)
        if month_index == 2 and offset % 5 in (1, 2):
            day_cycles = max(day_cycles, cfg.daily_ideal_goal + 1)
        day_cycles = min(12, day_cycles)
        day_water_logs = max(0, min(12, water_per_day + water_boost))

        session = Session(
            date=day,
            started_at=datetime.combine(day, time_(8, 30)),
            ended_at=datetime.combine(day, time_(18, 0)),
            status="ended",
        )
        db.session.add(session)
        db.session.flush()

        for index in range(day_cycles):
            completed_at = datetime.combine(day, time_(9, 0)) + timedelta(
                minutes=(index + 1) * (cfg.focus_minutes + 10)
            )
            started_at = completed_at - timedelta(minutes=cfg.focus_minutes)
            cycle = FocusCycle(
                session_id=session.id,
                configuration_id=cfg.id,
                started_at=started_at,
                completed_at=completed_at,
                focus_duration_minutes=cfg.focus_minutes,
                title=f"Debug {day.isoformat()} #{index + 1}"[:280],
                status="completed",
            )
            db.session.add(cycle)
            db.session.flush()
            _complete_fictional_cycle(cycle)

        for index in range(day_water_logs):
            logged_at = datetime.combine(day, time_(12, 0)) + timedelta(minutes=index * 15)
            db.session.add(
                WaterLog(
                    date=day,
                    logged_at=logged_at,
                    volume_ml=cfg.water_bottle_ml,
                    configuration_id=cfg.id,
                )
            )

        db.session.flush()
        daily_service.consolidate_daily(day, commit=False, force=True)
        generated_days.append(day)

    seen_weeks = set()
    seen_months = set()
    for day in generated_days:
        week_start, _ = week_bounds(day)
        if week_start not in seen_weeks:
            week_service.consolidate_week_for_date(day, commit=False)
            seen_weeks.add(week_start)
        month_key = (day.year, day.month)
        if month_key not in seen_months:
            month_service.consolidate_month_for_date(day, commit=False)
            seen_months.add(month_key)

    _mark_generated_range(start_day, end_day)
    db.session.commit()
    return {
        "requested_days": days,
        "days": len(generated_days),
        "cycles_per_day": cycles_per_day,
        "water_per_day": water_per_day,
        "start_day": start_day,
        "end_day": end_day,
        "absolute_goal_cycles": absolute.goal_cycles,
        "generated_days": len(generated_days),
        "generated_weeks": len(seen_weeks),
        "generated_months": len(seen_months),
    }


def clear_generated_test_data() -> dict:
    """
    Remove apenas o ultimo lote de dados ficticios gerados pelo painel.
    """
    generated_range = _generated_range()
    if generated_range is None:
        return {"cleared": False, "reason": "no_generated_data"}

    start_day, end_day = generated_range
    start_dt = datetime.combine(start_day, time_(0, 0))
    end_dt = datetime.combine(end_day, time_(23, 59, 59))
    reward_titles = {
        "Meta média fictícia",
        "Meta ideal fictícia",
        "Meta semanal fictícia",
        "Objetivo absoluto fictício",
    }

    summary = {
        "start_day": start_day,
        "end_day": end_day,
        "sessions": Session.query.filter(Session.date >= start_day, Session.date <= end_day).delete(synchronize_session=False),
        "focus_cycles": FocusCycle.query.filter(
            FocusCycle.completed_at.isnot(None),
            FocusCycle.completed_at >= start_dt,
            FocusCycle.completed_at <= end_dt,
        ).delete(synchronize_session=False),
        "water_logs": WaterLog.query.filter(WaterLog.date >= start_day, WaterLog.date <= end_day).delete(synchronize_session=False),
        "daily_minimum": DailyMinimumProgress.query.filter(DailyMinimumProgress.date >= start_day, DailyMinimumProgress.date <= end_day).delete(synchronize_session=False),
        "daily_ideal": DailyIdealProgress.query.filter(DailyIdealProgress.date >= start_day, DailyIdealProgress.date <= end_day).delete(synchronize_session=False),
        "weekly": WeeklyProgress.query.filter(WeeklyProgress.week_start >= start_day, WeeklyProgress.week_end <= end_day).delete(synchronize_session=False),
        "extraordinary": ExtraordinaryProgress.query.filter(ExtraordinaryProgress.date >= start_day, ExtraordinaryProgress.date <= end_day).delete(synchronize_session=False),
        "reward_achievements": RewardAchievement.query.filter(RewardAchievement.achieved_date >= start_day, RewardAchievement.achieved_date <= end_day).delete(synchronize_session=False),
        "absolute_logs": AbsoluteProgressDailyLog.query.filter(AbsoluteProgressDailyLog.date >= start_day, AbsoluteProgressDailyLog.date <= end_day).delete(synchronize_session=False),
        "daily": Daily.query.filter(Daily.date >= start_day, Daily.date <= end_day).delete(synchronize_session=False),
        "rewards": Reward.query.filter(Reward.title.in_(reward_titles)).delete(synchronize_session=False),
        "absolutes": AbsoluteProgress.query.filter(
            AbsoluteProgress.title == "Objetivo fictício",
            AbsoluteProgress.description == "Criado automaticamente pelo painel de debug.",
        ).delete(synchronize_session=False),
        "configurations": Configuration.query.filter(
            Configuration.valid_from >= start_dt,
            Configuration.valid_from <= end_dt,
            Configuration.valid_to.isnot(None),
        ).delete(synchronize_session=False),
    }

    impacted_weeks = Week.query.filter(Week.start_date <= end_day, Week.end_date >= start_day).all()
    impacted_months = Month.query.filter(Month.start_date <= end_day, Month.end_date >= start_day).all()

    db.session.flush()

    cleared_weeks = 0
    rebuilt_weeks = 0
    for week in impacted_weeks:
        if week.daily_links and all(start_day <= link.date <= end_day for link in week.daily_links):
            db.session.delete(week)
            cleared_weeks += 1
        elif week.daily_links:
            week_service.rebuild_week(week.start_date, week.end_date, final=week.status == "consolidated", commit=False)
            rebuilt_weeks += 1

    cleared_months = 0
    rebuilt_months = 0
    for month in impacted_months:
        if month.daily_links and all(start_day <= link.date <= end_day for link in month.daily_links):
            db.session.delete(month)
            cleared_months += 1
        elif month.daily_links:
            month_service.rebuild_month(month.start_date, month.end_date, final=month.status == "consolidated", commit=False)
            rebuilt_months += 1

    current_cfg = get_current_configuration()

    for weekly in WeeklyProgress.query.all():
        weekly.current_count = FocusCycle.query.filter(
            FocusCycle.status == "completed",
            FocusCycle.completed_at >= datetime.combine(weekly.week_start, time_(0, 0)),
            FocusCycle.completed_at <= datetime.combine(weekly.week_end, time_(23, 59, 59))
        ).count()
        if weekly.current_count >= weekly.goal:
            weekly.status = "completed"
        else:
            weekly.status = "pending"
            weekly.completed_at = None

        if weekly.configuration is None:
            valid_cfg = Configuration.query.filter(
                Configuration.valid_from <= datetime.combine(weekly.week_end, time_(23, 59, 59))
            ).order_by(Configuration.valid_from.desc()).first() or current_cfg
            weekly.configuration_id = valid_cfg.id

    for daily_min in DailyMinimumProgress.query.all():
        if daily_min.configuration is None:
            valid_cfg = Configuration.query.filter(
                Configuration.valid_from <= datetime.combine(daily_min.date, time_(23, 59, 59))
            ).order_by(Configuration.valid_from.desc()).first() or current_cfg
            daily_min.configuration_id = valid_cfg.id

    for daily_ideal in DailyIdealProgress.query.all():
        if daily_ideal.configuration is None:
            valid_cfg = Configuration.query.filter(
                Configuration.valid_from <= datetime.combine(daily_ideal.date, time_(23, 59, 59))
            ).order_by(Configuration.valid_from.desc()).first() or current_cfg
            daily_ideal.configuration_id = valid_cfg.id

    for extraordinary in ExtraordinaryProgress.query.all():
        if extraordinary.configuration is None:
            valid_cfg = Configuration.query.filter(
                Configuration.valid_from <= datetime.combine(extraordinary.date, time_(23, 59, 59))
            ).order_by(Configuration.valid_from.desc()).first() or current_cfg
            extraordinary.configuration_id = valid_cfg.id

    state = _debug_state()
    if state is not None:
        state.test_data_start_date = None
        state.test_data_end_date = None
        state.test_data_generated_at = None

    db.session.commit()
    return {
        "cleared": True,
        "range": {"start_day": start_day, "end_day": end_day},
        "deleted": summary,
        "weeks": {"deleted": cleared_weeks, "rebuilt": rebuilt_weeks},
        "months": {"deleted": cleared_months, "rebuilt": rebuilt_months},
    }


def clear_database_data() -> dict:
    """
    Remove todos os registros do banco preservando a estrutura das tabelas.

    A exclusão é feita na ordem reversa da metadata para respeitar
    dependências entre chaves estrangeiras.
    """
    deleted_tables = []
    for table in reversed(db.metadata.sorted_tables):
        db.session.execute(table.delete())
        deleted_tables.append(table.name)

    db.session.commit()
    return {"deleted_tables": deleted_tables}


def reset_cycle_progress() -> dict:
    """
    Reinicia o progresso operacional relacionado aos ciclos, sem apagar
    o histórico de FocusCycle.

    O reset afeta o dia atual e a semana atual, que são os estados
    exibidos nas barras principais do app.
    """
    current_day = today()
    week_start, week_end = progress_service.week_bounds(current_day)

    touched = {
        "daily_minimum": False,
        "daily_ideal": False,
        "weekly": False,
        "extraordinary_deleted": 0,
        "absolute_reset": False,
    }

    daily_min = DailyMinimumProgress.query.filter_by(date=current_day).first()
    if daily_min is not None:
        daily_min.current_count = 0
        daily_min.status = "pending"
        daily_min.completed_at = None
        touched["daily_minimum"] = True

    daily_ideal = DailyIdealProgress.query.filter_by(date=current_day).first()
    if daily_ideal is not None:
        daily_ideal.current_count = 0
        daily_ideal.status = "pending"
        daily_ideal.completed_at = None
        touched["daily_ideal"] = True

    weekly = WeeklyProgress.query.filter_by(week_start=week_start, week_end=week_end).first()
    if weekly is not None:
        weekly.current_count = 0
        weekly.status = "pending"
        weekly.completed_at = None
        touched["weekly"] = True

    touched["extraordinary_deleted"] = ExtraordinaryProgress.query.filter_by(date=current_day).delete()

    absolute = progress_service.get_active_absolute()
    if absolute is not None:
        absolute.current_count = 0
        absolute.status = "active"
        absolute.completed_at = None
        touched["absolute_reset"] = True

    db.session.commit()
    return {"today": current_day, **touched}


def complete_session() -> dict:
    """
    Completa a sessão ativa do dia atual seguindo o mesmo fluxo do usuário.

    Primeiro garante que existam os ciclos necessários para atingir a
    configuração vigente de "ciclos por sessão" e só então encerra a
    sessão, consolidando o Daily pelo mesmo caminho do fluxo natural.
    """
    current_day = today()
    cfg = get_current_configuration()
    target_cycles = max(1, cfg.cycles_per_session)

    session = cycles_service.get_or_create_active_session()
    completed_cycles_before = FocusCycle.query.filter_by(
        session_id=session.id, status="completed"
    ).count()

    remaining_cycles = max(0, target_cycles - completed_cycles_before)
    last_result = None
    for _ in range(remaining_cycles):
        cycle = cycles_service.start_focus_cycle(title="Debug sessão")
        last_result = engine.complete_focus_cycle(cycle.id, title="Debug sessão")

    cycles_service.end_session(session)
    completed_cycles_after = FocusCycle.query.filter_by(
        session_id=session.id, status="completed"
    ).count()
    return {
        "ok": True,
        "today": current_day,
        "session_id": session.id,
        "cycles_per_session": target_cycles,
        "completed_cycles_before": completed_cycles_before,
        "completed_cycles_after": completed_cycles_after,
        "remaining_cycles": remaining_cycles,
        "session_ended": True,
        "last_result": last_result,
        "post_cycle_message": (
            last_result["post_cycle_message"]
            if last_result and last_result.get("post_cycle_message")
            else "Sessão encerrada."
        ),
    }
