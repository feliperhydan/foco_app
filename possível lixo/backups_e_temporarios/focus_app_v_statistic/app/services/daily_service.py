"""Consolidacao historica Daily.

Daily e o registro bruto e autocontido de um dia. Este service le os
registros operacionais atuais e persiste snapshots historicos sem criar
interpretacoes estatisticas.
"""
from __future__ import annotations

import copy
from collections import OrderedDict, defaultdict
from datetime import date as date_, datetime, time as time_

from sqlalchemy import func

from app.extensions import db
from app.models import (
    AbsoluteProgress,
    AbsoluteProgressDailyLog,
    Configuration,
    Daily,
    DailyIdealProgress,
    DailyMinimumProgress,
    FocusCycle,
    RestCycle,
    Reward,
    RewardAchievement,
    Session,
    TodoItem,
    WaterLog,
    WeeklyProgress,
)
from app.services.clock import now, today
from app.services.progress_service import week_bounds


def _empty_water() -> dict:
    return {"goal_ml": 0, "total_ml": 0, "bottles": 0, "bottle_ml": 0, "contexts": []}


def _empty_todo() -> dict:
    return {"items_total": 0, "items_completed": 0}


def _empty_rewards() -> dict:
    return {
        "daily_minimum": {"title": None, "cycles_computed": 0, "goal": 0, "goal_completed": False},
        "daily_ideal": {"title": None, "cycles_computed": 0, "goal": 0, "goal_completed": False},
        "weekly": {"title": None, "cycles_computed": 0, "goal": 0, "goal_completed": False},
        "absolute": {
            "absolute_progress_id": None,
            "title": None,
            "goal_cycles": None,
            "start": None,
            "end": None,
            "cycles_computed": None,
            "goal_completed": False,
        },
    }


def _configuration_snapshot(cfg: Configuration) -> dict:
    return {
        "focus_minutes": cfg.focus_minutes,
        "short_break_minutes": cfg.short_break_minutes,
        "long_break_minutes": cfg.long_break_minutes,
        "cycles_per_session": cfg.cycles_per_session,
        "daily_minimum_goal": cfg.daily_minimum_goal,
        "daily_ideal_goal": cfg.daily_ideal_goal,
        "weekly_goal": cfg.weekly_goal,
    }


def _get_or_create_daily(d: date_, commit: bool = True) -> Daily:
    daily = Daily.query.filter_by(date=d).first()
    if daily is None:
        daily = Daily(
            date=d,
            session_started=False,
            cycle_contexts=[],
            focus_timeline=[],
            session={},
            water=_empty_water(),
            todo=_empty_todo(),
            rewards=_empty_rewards(),
        )
        db.session.add(daily)
        db.session.flush()
        _ensure_absolute_start(daily)
        if commit:
            db.session.commit()
    return daily


def ensure_daily_for_date(d: date_, session_started: bool = False, commit: bool = True) -> Daily:
    """
    Garante a existencia de um Daily. Permite representar dias sem sessao.

    Quando chamado no inicio da primeira sessao, tambem preserva o
    estado inicial do objetivo absoluto para o dia.
    """
    daily = _get_or_create_daily(d, commit=False)
    if session_started and not daily.session_started:
        daily.session_started = True
    _ensure_absolute_start(daily)
    if d == today() and daily.consolidated_at is None:
        from app.services import todo_service

        todo_service.ensure_today_completion_state(commit=False)
        daily.todo = {
            "items_total": TodoItem.query.count(),
            "items_completed": TodoItem.query.filter_by(done=True).count(),
        }
    if commit:
        db.session.commit()
    return daily


def _active_or_recent_absolute_for_day(d: date_) -> AbsoluteProgress | None:
    active = (
        AbsoluteProgress.query.filter_by(status="active")
        .order_by(AbsoluteProgress.started_at.asc())
        .first()
    )
    if active is not None:
        return active
    return (
        AbsoluteProgress.query.filter(
            AbsoluteProgress.completed_at.isnot(None),
            func.date(AbsoluteProgress.completed_at) == d.isoformat(),
        )
        .order_by(AbsoluteProgress.completed_at.desc())
        .first()
    )


def _absolute_state(current_cycles: int, goal_cycles: int) -> dict:
    return {"current_cycles": current_cycles, "goal_cycles": goal_cycles}


def _absolute_start_from_current(absolute: AbsoluteProgress | None) -> dict | None:
    if absolute is None:
        return None
    return _absolute_state(absolute.current_count, absolute.goal_cycles)


def _absolute_identity_from_log(log: AbsoluteProgressDailyLog | None) -> AbsoluteProgress | None:
    return log.absolute_progress if log is not None else None


def _direct_absolute_log_for_day(d: date_) -> AbsoluteProgressDailyLog | None:
    return (
        AbsoluteProgressDailyLog.query.filter_by(date=d)
        .order_by(AbsoluteProgressDailyLog.id.asc())
        .first()
    )


def _absolute_from_snapshot(snapshot: dict) -> AbsoluteProgress | None:
    progress_id = snapshot.get("absolute_progress_id")
    if progress_id is None:
        return None
    return db.session.get(AbsoluteProgress, progress_id)


def _absolute_for_day(d: date_, previous_snapshot: dict | None = None) -> AbsoluteProgress | None:
    """
    Resolve a identidade historica do AbsoluteProgress para `d`.

    Dias historicos usam evidencia historica (log direto/snapshot). O
    estado vivo so e aceito para o dia corrente, ainda progressivo.
    """
    previous_snapshot = previous_snapshot or {}
    direct = _direct_absolute_log_for_day(d)
    if direct is not None:
        return _absolute_identity_from_log(direct)

    from_snapshot = _absolute_from_snapshot(previous_snapshot)
    if from_snapshot is not None:
        return from_snapshot

    if d == today():
        return _active_or_recent_absolute_for_day(d)

    return None


def _ensure_absolute_start(daily: Daily) -> None:
    rewards = copy.deepcopy(daily.rewards) if daily.rewards else _empty_rewards()
    for progress_type in ("daily_minimum", "daily_ideal", "weekly"):
        reward_payload = rewards.get(progress_type) or _empty_rewards()[progress_type]
        if reward_payload.get("title") is None:
            reward_payload["title"] = _active_reward_title(progress_type)
        rewards[progress_type] = reward_payload

    absolute_reward = rewards.get("absolute") or _empty_rewards()["absolute"]
    start = absolute_reward.get("start") or {}
    has_identity = absolute_reward.get("absolute_progress_id") is not None
    if has_identity and start:
        rewards["absolute"] = absolute_reward
        daily.rewards = rewards
        return

    absolute = _absolute_for_day(daily.date, absolute_reward)
    absolute_reward["title"] = absolute.title if absolute else None
    absolute_reward["absolute_progress_id"] = absolute.id if absolute else None
    absolute_reward["goal_cycles"] = absolute.goal_cycles if absolute else None
    absolute_reward["start"] = _absolute_start_from_current(absolute)
    absolute_reward.setdefault("end", _absolute_start_from_current(absolute))
    absolute_reward.setdefault("cycles_computed", None if absolute is None else 0)
    absolute_reward.setdefault("goal_completed", False)
    rewards["absolute"] = absolute_reward
    daily.rewards = rewards


def _completed_focus_cycles(d: date_) -> list[FocusCycle]:
    return (
        FocusCycle.query.join(Session)
        .filter(Session.date == d, FocusCycle.status == "completed")
        .order_by(FocusCycle.completed_at.asc(), FocusCycle.id.asc())
        .all()
    )


def _completed_rest_cycles(d: date_) -> list[RestCycle]:
    return (
        RestCycle.query.join(Session)
        .filter(Session.date == d, RestCycle.status == "completed")
        .order_by(RestCycle.ended_at.asc(), RestCycle.id.asc())
        .all()
    )


def _context_entry(context_id: int, cfg: Configuration) -> dict:
    return {
        "context_id": context_id,
        "configuration_id": cfg.id,
        "started_at": cfg.valid_from.isoformat() if cfg.valid_from else None,
        "ended_at": cfg.valid_to.isoformat() if cfg.valid_to else None,
        "configuration": _configuration_snapshot(cfg),
        "focus": {"cycles_completed": 0, "minutes_completed": 0, "titles": []},
        "rest_short": {"cycles_completed": 0, "minutes_completed": 0},
        "rest_long": {"cycles_completed": 0, "minutes_completed": 0},
        "extraordinary": {"cycles": 0, "minutes": 0},
    }


def _title_entries(cycles: list[FocusCycle]) -> list[dict]:
    counts: OrderedDict[str | None, int] = OrderedDict()
    for cycle in cycles:
        text = cycle.title if cycle.title is not None else None
        counts[text] = counts.get(text, 0) + 1
    return [{"text": text, "cycle_count": count} for text, count in counts.items()]


def _focus_timeline_entries(focus_cycles: list[FocusCycle]) -> list[dict]:
    """
    Cronologia individual de cada FocusCycle concluido.
    Um item por ciclo, em ordem cronologica de conclusao.
    Titulos null preservados como null.
    """
    return [
        {
            "completed_at": cycle.completed_at.isoformat() if cycle.completed_at else None,
            "title": cycle.title,
            "configuration_id": cycle.configuration_id,
        }
        for cycle in focus_cycles
    ]


def _cycle_contexts(d: date_) -> list[dict]:
    focus_cycles = _completed_focus_cycles(d)
    rest_cycles = _completed_rest_cycles(d)

    configs: OrderedDict[int, Configuration] = OrderedDict()
    for cycle in focus_cycles:
        configs.setdefault(cycle.configuration_id, cycle.configuration)
    for rest in rest_cycles:
        configs.setdefault(rest.configuration_id, rest.configuration)

    contexts_by_config = {
        cfg_id: _context_entry(index, cfg)
        for index, (cfg_id, cfg) in enumerate(configs.items(), start=1)
    }

    focus_by_config: dict[int, list[FocusCycle]] = defaultdict(list)
    for cycle in focus_cycles:
        focus_by_config[cycle.configuration_id].append(cycle)
        focus = contexts_by_config[cycle.configuration_id]["focus"]
        focus["cycles_completed"] += 1
        focus["minutes_completed"] += cycle.focus_duration_minutes

    for cfg_id, cycles in focus_by_config.items():
        contexts_by_config[cfg_id]["focus"]["titles"] = _title_entries(cycles)

    for rest in rest_cycles:
        key = "rest_short" if rest.kind == "short" else "rest_long"
        rest_payload = contexts_by_config[rest.configuration_id][key]
        rest_payload["cycles_completed"] += 1
        rest_payload["minutes_completed"] += rest.duration_minutes

    daily_ideal = DailyIdealProgress.query.filter_by(date=d).first()
    ideal_goal = daily_ideal.goal if daily_ideal else None
    if ideal_goal is not None:
        for index, cycle in enumerate(focus_cycles, start=1):
            if index <= ideal_goal:
                continue
            extra = contexts_by_config[cycle.configuration_id]["extraordinary"]
            extra["cycles"] += 1
            extra["minutes"] += cycle.focus_duration_minutes

    return list(contexts_by_config.values())


def _water(d: date_) -> dict:
    """
    Constroi o snapshot de agua para a data `d`.

    Mesmo quando o consumo e zero, preserva goal_ml e bottle_ml da
    configuracao vigente ao inicio do dia para evitar perda historica.
    """
    logs = (
        WaterLog.query.filter_by(date=d)
        .order_by(WaterLog.logged_at.asc(), WaterLog.id.asc())
        .all()
    )
    contexts: OrderedDict[int, dict] = OrderedDict()
    for log in logs:
        cfg = log.configuration
        if log.configuration_id not in contexts:
            contexts[log.configuration_id] = {
                "context_id": len(contexts) + 1,
                "bottle_capacity_ml": cfg.water_bottle_ml,
                "daily_goal_ml": cfg.water_goal_ml,
                "bottles_consumed": 0,
                "water_consumed_ml": 0,
            }
        context = contexts[log.configuration_id]
        context["bottles_consumed"] += 1
        context["water_consumed_ml"] += log.volume_ml

    total_ml = sum(c["water_consumed_ml"] for c in contexts.values())
    total_bottles = sum(c["bottles_consumed"] for c in contexts.values())

    # Configuracao vigente no dia `d` para preservar goal/capacity mesmo com consumo 0.
    # Para o dia vigente usa a configuracao atual (sem perder dado do momento presente).
    # Para dias historicos usa get_configuration_at com o fim do dia como referencia.
    from datetime import time as time_
    from app.services.config_service import get_configuration_at, get_current_configuration
    if d >= today():
        cfg_at_day = get_current_configuration()
    else:
        day_end_moment = datetime.combine(d, time_(23, 59, 59))
        cfg_at_day = get_configuration_at(day_end_moment)

    return {
        "goal_ml": cfg_at_day.water_goal_ml,
        "total_ml": total_ml,
        "bottles": total_bottles,
        "bottle_ml": cfg_at_day.water_bottle_ml,
        "contexts": list(contexts.values()),
    }


def _todo(d: date_) -> dict:
    if d != today():
        existing = Daily.query.filter_by(date=d).first()
        if existing and existing.todo:
            return existing.todo
        return _empty_todo()
    return {
        "items_total": TodoItem.query.count(),
        "items_completed": TodoItem.query.filter_by(done=True).count(),
    }


def refresh_todo_snapshot_for_today(commit: bool = True) -> Daily | None:
    """
    Atualiza o snapshot bruto de to-do no Daily ja existente do dia.

    A lista reseta seus checks por data; por isso o Daily precisa guardar
    esse snapshot enquanto o dia ainda esta vigente, antes de qualquer
    reset do dia seguinte.
    """
    current_day = today()
    daily = Daily.query.filter_by(date=current_day).first()
    if daily is None or daily.consolidated_at is not None:
        return daily

    daily.todo = {
        "items_total": TodoItem.query.count(),
        "items_completed": TodoItem.query.filter_by(done=True).count(),
    }
    db.session.flush()
    if commit:
        db.session.commit()
    return daily


def _active_reward_title(progress_type: str) -> str | None:
    reward = Reward.query.filter_by(progress_type=progress_type, active=True).first()
    return reward.title if reward else None


def _reward_title_for_day(progress_type: str, d: date_, fallback_title: str | None = None) -> str | None:
    """
    Resolve o titulo historico de uma recompensa para uma data.

    Prioridade:
    1. title_snapshot da RewardAchievement (conquista registrada naquele dia).
    2. fallback_title preservado do Daily anterior (titulo vigente ao criar o Daily).
    3. Titulo ativo atual da Reward — so usado se o Daily ainda nao foi consolidado.
    """
    achievement = (
        RewardAchievement.query.join(Reward)
        .filter(Reward.progress_type == progress_type, RewardAchievement.achieved_date == d)
        .order_by(RewardAchievement.id.asc())
        .first()
    )
    if achievement:
        return achievement.title_snapshot or achievement.reward.title
    # Fallback preservado: titulo que estava vigente quando o Daily foi criado/atualizado pela ultima vez
    if fallback_title is not None:
        return fallback_title
    return _active_reward_title(progress_type)


def _absolute_values_for_day(
    absolute: AbsoluteProgress | None,
    d: date_,
    goal_cycles: int | None = None,
) -> tuple[dict | None, dict | None]:
    """
    Retorna (start_dict, end_dict) para o progresso absoluto em uma data.

    Usa AbsoluteProgressDailyLog como fonte historica quando disponivel,
    nunca dependendo do current_count vivo de AbsoluteProgress.
    """
    if absolute is None:
        return None, None

    goal = goal_cycles if goal_cycles is not None else absolute.goal_cycles

    # 1. log existe para o dia
    log = AbsoluteProgressDailyLog.query.filter_by(
        date=d, absolute_progress_id=absolute.id
    ).first()
    if log is not None:
        return (
            _absolute_state(log.start_count, goal),
            _absolute_state(log.end_count, goal),
        )

    # 2. primeiro log posterior (indica o valor em que estava travado)
    next_log = (
        AbsoluteProgressDailyLog.query.filter(
            AbsoluteProgressDailyLog.absolute_progress_id == absolute.id,
            AbsoluteProgressDailyLog.date > d,
        )
        .order_by(AbsoluteProgressDailyLog.date.asc())
        .first()
    )

    # 3. ultimo log anterior
    prev_log = (
        AbsoluteProgressDailyLog.query.filter(
            AbsoluteProgressDailyLog.absolute_progress_id == absolute.id,
            AbsoluteProgressDailyLog.date < d,
        )
        .order_by(AbsoluteProgressDailyLog.date.desc())
        .first()
    )

    if next_log is not None and prev_log is not None:
        val = prev_log.end_count
        return _absolute_state(val, goal), _absolute_state(val, goal)

    if next_log is not None:
        val = next_log.start_count
        return _absolute_state(val, goal), _absolute_state(val, goal)

    if prev_log is not None:
        val = prev_log.end_count
        return _absolute_state(val, goal), _absolute_state(val, goal)

    # 4. fallback base: se o progresso comecou depois de d, era 0
    if absolute.started_at and absolute.started_at.date() > d:
        return (
            _absolute_state(0, goal),
            _absolute_state(0, goal),
        )

    # 5. Dia corrente aberto pode usar o estado vivo. Historico sem evidencia fica ausente.
    if d == today():
        val = absolute.current_count
        return _absolute_state(val, goal), _absolute_state(val, goal)

    return None, None


def _progress_reward(
    progress_type: str,
    d: date_,
    current: int,
    goal: int,
    completed: bool,
    fallback_title: str | None = None,
) -> dict:
    return {
        "title": _reward_title_for_day(progress_type, d, fallback_title=fallback_title),
        "cycles_computed": current,
        "goal": goal,
        "goal_completed": completed,
    }


def _rewards(d: date_, daily: Daily, focus_cycles_count: int) -> dict:
    rewards = copy.deepcopy(daily.rewards) if daily.rewards else _empty_rewards()

    daily_min = DailyMinimumProgress.query.filter_by(date=d).first()
    previous_minimum = rewards.get("daily_minimum") or {}
    rewards["daily_minimum"] = _progress_reward(
        "daily_minimum",
        d,
        daily_min.current_count if daily_min else 0,
        daily_min.goal if daily_min else 0,
        bool(daily_min and daily_min.status == "completed"),
        previous_minimum.get("title"),
    )

    daily_ideal = DailyIdealProgress.query.filter_by(date=d).first()
    previous_ideal = rewards.get("daily_ideal") or {}
    rewards["daily_ideal"] = _progress_reward(
        "daily_ideal",
        d,
        daily_ideal.current_count if daily_ideal else 0,
        daily_ideal.goal if daily_ideal else 0,
        bool(daily_ideal and daily_ideal.status == "completed"),
        previous_ideal.get("title"),
    )

    week_start, week_end = week_bounds(d)
    weekly = WeeklyProgress.query.filter_by(week_start=week_start, week_end=week_end).first()
    previous_weekly = rewards.get("weekly") or {}
    rewards["weekly"] = _progress_reward(
        "weekly",
        d,
        weekly.current_count if weekly else 0,
        weekly.goal if weekly else 0,
        bool(weekly and weekly.status == "completed"),
        previous_weekly.get("title"),
    )

    previous_absolute = rewards.get("absolute") or _empty_rewards()["absolute"]
    absolute = _absolute_for_day(d, previous_absolute)
    previous_absolute_id = previous_absolute.get("absolute_progress_id")
    resolved_absolute_id = absolute.id if absolute else None
    same_previous_absolute = (
        previous_absolute_id is not None
        and previous_absolute_id == resolved_absolute_id
    )
    snapshot_goal = previous_absolute.get("goal_cycles") if same_previous_absolute else None
    start, end = _absolute_values_for_day(absolute, d, goal_cycles=snapshot_goal)
    cycles_computed = (
        max(0, end["current_cycles"] - start["current_cycles"])
        if start is not None and end is not None
        else None
    )
    rewards["absolute"] = {
        "absolute_progress_id": (
            resolved_absolute_id
            if resolved_absolute_id is not None
            else previous_absolute_id
        ),
        "title": (
            previous_absolute.get("title")
            if same_previous_absolute and previous_absolute.get("title") is not None
            else (absolute.title if absolute else None)
        ),
        "goal_cycles": (
            snapshot_goal
            if snapshot_goal is not None
            else (absolute.goal_cycles if absolute else None)
        ),
        "start": start,
        "end": end,
        "cycles_computed": cycles_computed,
        "goal_completed": bool(
            absolute
            and absolute.completed_at is not None
            and absolute.completed_at.date() == d
        ),
    }
    return rewards


def _end_of_day_iso(d: date_) -> str:
    return datetime.combine(d, time_(23, 59, 59, 999999)).isoformat()


def _session_snapshot(d: date_, focus_cycles: list[FocusCycle], final: bool = False) -> dict | None:
    """
    Captura a sessao estatistica diaria.

    Para o Daily, sessao significa dia de estudo: existe somente quando
    pelo menos um FocusCycle foi concluido. Sessions operacionais ou
    mudancas de contexto nao criam sessoes estatisticas adicionais.
    """
    if not focus_cycles:
        return None
    first_cycle = min(
        focus_cycles,
        key=lambda cycle: (
            cycle.started_at or cycle.completed_at or datetime.combine(d, time_(0, 0)),
            cycle.id,
        ),
    )
    return {
        "started": True,
        "started_at": first_cycle.started_at.isoformat() if first_cycle.started_at else None,
        "ended_at": _end_of_day_iso(d) if final else None,
    }


def consolidate_daily(d: date_, commit: bool = True) -> Daily:
    """
    Consolida e persiste o Daily da data informada.

    Apenas grava o que aconteceu e o contexto historico necessario.
    Apos consolidated_at ser definido, o snapshot e imutavel.
    """
    daily = ensure_daily_for_date(d, session_started=False, commit=False)
    if daily.consolidated_at is not None:
        if commit:
            db.session.commit()
        return daily

    active_sessions = Session.query.filter_by(date=d, status="active").count()

    # Cronologia individual dos ciclos (congelada aqui)
    focus_cycles = _completed_focus_cycles(d)
    daily.session_started = len(focus_cycles) > 0
    daily.focus_timeline = _focus_timeline_entries(focus_cycles)

    # Snapshot da sessao diaria estatistica (congelado aqui)
    daily.session = _session_snapshot(d, focus_cycles, final=(active_sessions == 0 and d < today()))

    daily.cycle_contexts = _cycle_contexts(d)
    daily.water = _water(d)
    daily.todo = _todo(d)
    focus_cycles_count = sum(
        context["focus"]["cycles_completed"] for context in daily.cycle_contexts
    )
    daily.rewards = _rewards(d, daily, focus_cycles_count)
    if active_sessions == 0 and d < today():
        daily.consolidated_at = now()
    db.session.flush()
    if commit:
        db.session.commit()
    return daily
