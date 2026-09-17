"""Agregacao historica Month.

Month usa meses de calendário real: do primeiro dia ao último dia do mês.
A fonte de verdade e sempre Daily; este service nunca consulta configuracao,
wishlist, to-do, AbsoluteProgress ou outros estados operacionais para reconstruir meses.
"""
from __future__ import annotations

import calendar
import copy
import json
from collections import OrderedDict
from datetime import date as date_

from app.extensions import db
from app.models import Daily, Month, MonthDaily
from app.services.clock import now
from app.services.clock import today as current_day


def month_bounds(d: date_) -> tuple[date_, date_]:
    """Retorna o primeiro e o último dia do mês correspondente à data d."""
    start = date_(d.year, d.month, 1)
    last_day = calendar.monthrange(d.year, d.month)[1]
    end = date_(d.year, d.month, last_day)
    return start, end


def _empty_totals() -> dict:
    return {
        "focus": {"cycles_completed": 0, "minutes_completed": 0},
        "rest_short": {"cycles_completed": 0, "minutes_completed": 0},
        "rest_long": {"cycles_completed": 0, "minutes_completed": 0},
        "extraordinary": {"cycles": 0, "minutes": 0},
    }


def _empty_water() -> dict:
    return {
        "total_bottles_consumed": 0,
        "total_water_consumed_ml": 0,
        "contexts": [],
    }


def _empty_todo() -> dict:
    return {"items_total": 0, "items_completed": 0, "days": []}


def _empty_reward(progress_type: str) -> dict:
    return {
        "completed_count": 0,
        "cycles_computed": 0,
        "titles": [],
        "days": [],
    }


def _empty_rewards() -> dict:
    return {
        "daily_minimum": _empty_reward("daily_minimum"),
        "daily_ideal": _empty_reward("daily_ideal"),
        "weekly": _empty_reward("weekly"),
        "absolute": {
            "completed_count": 0,
            "cycles_computed": 0,
            "titles": [],
            "days": [],
        },
    }


def _empty_absolute() -> dict:
    return {
        "absolute_progress_id": None,
        "title": None,
        "goal_cycles": None,
        "start": {"current_cycles": 0, "goal_cycles": 0},
        "end": {"current_cycles": 0, "goal_cycles": 0},
        "cycles_computed": 0,
        "goal_completed": False,
        "days": [],
    }


def _stable_key(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _add_cycles(target: dict, source: dict) -> None:
    target["cycles_completed"] += source.get("cycles_completed", 0)
    target["minutes_completed"] += source.get("minutes_completed", 0)


def _add_extra(target: dict, source: dict) -> None:
    target["cycles"] += source.get("cycles", 0)
    target["minutes"] += source.get("minutes", 0)


def _daily_rows(start_date: date_, end_date: date_) -> list[Daily]:
    return (
        Daily.query.filter(Daily.date >= start_date, Daily.date <= end_date)
        .order_by(Daily.date.asc())
        .all()
    )


def _refresh_open_dailies(start_date: date_, end_date: date_) -> None:
    from app.services import daily_service

    for daily in _daily_rows(start_date, min(end_date, current_day())):
        if daily.consolidated_at is None:
            daily_service.consolidate_daily(daily.date, commit=False)


def _get_or_create_month(start_date: date_, end_date: date_) -> Month:
    month = Month.query.filter_by(start_date=start_date, end_date=end_date).first()
    if month is None:
        month = Month(
            start_date=start_date,
            end_date=end_date,
            status="active",
            days=[],
            totals=_empty_totals(),
            contexts=[],
            titles=[],
            water=_empty_water(),
            todo=_empty_todo(),
            rewards=_empty_rewards(),
            absolute=_empty_absolute(),
        )
        db.session.add(month)
        db.session.flush()
    return month


def ensure_month_for_date(d: date_, commit: bool = True) -> Month:
    start_date, end_date = month_bounds(d)
    month = _get_or_create_month(start_date, end_date)
    if commit:
        db.session.commit()
    return month


def ensure_empty_month_for_date(d: date_, commit: bool = True) -> Month:
    """Cria um Month vazio explicitamente, sem criar Daily ficticios."""
    return rebuild_month_for_date(d, final=False, commit=commit)


def _aggregate_contexts(daily_rows: list[Daily]) -> tuple[list[dict], dict, list[dict]]:
    totals = _empty_totals()
    contexts: OrderedDict[str, dict] = OrderedDict()
    titles: OrderedDict[str, dict] = OrderedDict()

    for daily in daily_rows:
        day = daily.date.isoformat()
        for daily_context in daily.cycle_contexts or []:
            configuration = daily_context.get("configuration") or {}
            key = _stable_key(configuration)
            if key not in contexts:
                contexts[key] = {
                    "context_id": len(contexts) + 1,
                    "configuration": copy.deepcopy(configuration),
                    "days": [],
                    "focus": {"cycles_completed": 0, "minutes_completed": 0},
                    "rest_short": {"cycles_completed": 0, "minutes_completed": 0},
                    "rest_long": {"cycles_completed": 0, "minutes_completed": 0},
                    "extraordinary": {"cycles": 0, "minutes": 0},
                }

            context = contexts[key]
            if day not in context["days"]:
                context["days"].append(day)

            focus = daily_context.get("focus") or {}
            rest_short = daily_context.get("rest_short") or {}
            rest_long = daily_context.get("rest_long") or {}
            extraordinary = daily_context.get("extraordinary") or {}

            _add_cycles(context["focus"], focus)
            _add_cycles(totals["focus"], focus)
            _add_cycles(context["rest_short"], rest_short)
            _add_cycles(totals["rest_short"], rest_short)
            _add_cycles(context["rest_long"], rest_long)
            _add_cycles(totals["rest_long"], rest_long)
            _add_extra(context["extraordinary"], extraordinary)
            _add_extra(totals["extraordinary"], extraordinary)

            for title_entry in focus.get("titles") or []:
                text = title_entry.get("text")
                count = title_entry.get("cycle_count", 0)
                title_key = "__NULL__" if text is None else f"text:{text}"
                if title_key not in titles:
                    titles[title_key] = {"text": text, "cycle_count": 0, "days": []}
                titles[title_key]["cycle_count"] += count

                day_entry = next(
                    (item for item in titles[title_key]["days"] if item["date"] == day),
                    None,
                )
                if day_entry is None:
                    titles[title_key]["days"].append({"date": day, "cycle_count": count})
                else:
                    day_entry["cycle_count"] += count

    return list(contexts.values()), totals, list(titles.values())


def _aggregate_water(daily_rows: list[Daily]) -> dict:
    water = _empty_water()
    contexts: OrderedDict[str, dict] = OrderedDict()
    for daily in daily_rows:
        day = daily.date.isoformat()
        for daily_context in (daily.water or {}).get("contexts", []):
            key_payload = {
                "bottle_capacity_ml": daily_context.get("bottle_capacity_ml", 0),
                "daily_goal_ml": daily_context.get("daily_goal_ml", 0),
            }
            key = _stable_key(key_payload)
            if key not in contexts:
                contexts[key] = {
                    "context_id": len(contexts) + 1,
                    **key_payload,
                    "bottles_consumed": 0,
                    "water_consumed_ml": 0,
                    "days": [],
                }
            context = contexts[key]
            bottles = daily_context.get("bottles_consumed", 0)
            volume = daily_context.get("water_consumed_ml", 0)
            context["bottles_consumed"] += bottles
            context["water_consumed_ml"] += volume
            context["days"].append({
                "date": day,
                "bottles_consumed": bottles,
                "water_consumed_ml": volume,
            })
            water["total_bottles_consumed"] += bottles
            water["total_water_consumed_ml"] += volume
    water["contexts"] = list(contexts.values())
    return water


def _aggregate_todo(daily_rows: list[Daily]) -> dict:
    todo = _empty_todo()
    for daily in daily_rows:
        payload = daily.todo or {}
        day_entry = {
            "date": daily.date.isoformat(),
            "items_total": payload.get("items_total", 0),
            "items_completed": payload.get("items_completed", 0),
        }
        todo["items_total"] += day_entry["items_total"]
        todo["items_completed"] += day_entry["items_completed"]
        todo["days"].append(day_entry)
    return todo


def _add_reward_title(reward_payload: dict, title: str | None, day: str, completed: bool) -> None:
    title_key = "__NULL__" if title is None else f"title:{title}"
    entry = next(
        (candidate for candidate in reward_payload["titles"] if candidate.get("_key") == title_key),
        None,
    )
    if entry is None:
        entry = {"_key": title_key, "title": title, "completed_count": 0, "days": []}
        reward_payload["titles"].append(entry)
    if completed:
        entry["completed_count"] += 1
    entry["days"].append({"date": day, "goal_completed": completed})


def _clean_reward_titles(rewards: dict) -> dict:
    cleaned = copy.deepcopy(rewards)
    for payload in cleaned.values():
        if isinstance(payload, dict) and "titles" in payload:
            for title in payload["titles"]:
                title.pop("_key", None)
    return cleaned


def _aggregate_rewards(daily_rows: list[Daily]) -> tuple[dict, dict]:
    rewards = _empty_rewards()
    absolute = _empty_absolute()
    absolute_started = False

    for daily in daily_rows:
        day = daily.date.isoformat()
        daily_rewards = daily.rewards or {}
        for progress_type in ("daily_minimum", "daily_ideal", "weekly"):
            source = daily_rewards.get(progress_type) or {}
            target = rewards[progress_type]
            cycles = source.get("cycles_computed", 0)
            completed = bool(source.get("goal_completed", False))
            title = source.get("title")
            target["cycles_computed"] += cycles
            if completed:
                target["completed_count"] += 1
            target["days"].append({
                "date": day,
                "title": title,
                "cycles_computed": cycles,
                "goal_completed": completed,
            })
            _add_reward_title(target, title, day, completed)

        source_absolute = daily_rewards.get("absolute") or {}
        cycles = source_absolute.get("cycles_computed") or 0
        completed = bool(source_absolute.get("goal_completed", False))
        title = source_absolute.get("title")
        has_absolute_evidence = (
            source_absolute.get("absolute_progress_id") is not None
            or source_absolute.get("start") is not None
            or source_absolute.get("end") is not None
        )
        if not absolute_started and has_absolute_evidence:
            absolute["absolute_progress_id"] = source_absolute.get("absolute_progress_id")
            absolute["title"] = title
            absolute["goal_cycles"] = source_absolute.get("goal_cycles")
            absolute["start"] = source_absolute.get("start") or absolute["start"]
            absolute_started = True
        if has_absolute_evidence:
            absolute["end"] = source_absolute.get("end") or absolute["end"]
        absolute["cycles_computed"] += cycles
        absolute["goal_completed"] = absolute["goal_completed"] or completed
        rewards["absolute"]["cycles_computed"] += cycles
        if completed:
            rewards["absolute"]["completed_count"] += 1
        day_payload = {
            "date": day,
            "absolute_progress_id": source_absolute.get("absolute_progress_id"),
            "title": title,
            "goal_cycles": source_absolute.get("goal_cycles"),
            "start": source_absolute.get("start") or {"current_cycles": 0, "goal_cycles": 0},
            "end": source_absolute.get("end") or {"current_cycles": 0, "goal_cycles": 0},
            "cycles_computed": cycles,
            "goal_completed": completed,
        }
        absolute["days"].append(day_payload)
        rewards["absolute"]["days"].append(day_payload)
        _add_reward_title(rewards["absolute"], title, day, completed)

    return _clean_reward_titles(rewards), absolute


def _relink_daily(month: Month, daily_rows: list[Daily]) -> None:
    MonthDaily.query.filter_by(month_id=month.id).delete(synchronize_session=False)
    for daily in daily_rows:
        db.session.add(MonthDaily(month_id=month.id, daily_id=daily.id, date=daily.date))


def rebuild_month(start_date: date_, end_date: date_, final: bool = False, commit: bool = True) -> Month:
    month = _get_or_create_month(start_date, end_date)
    if month.consolidated_at is not None:
        if commit:
            db.session.commit()
        return month

    _refresh_open_dailies(start_date, end_date)
    daily_rows = _daily_rows(start_date, end_date)
    contexts, totals, titles = _aggregate_contexts(daily_rows)
    rewards, absolute = _aggregate_rewards(daily_rows)

    month.days = [
        {
            "date": daily.date.isoformat(),
            "daily_id": daily.id,
            "session_started": daily.session_started,
            "consolidated": daily.consolidated_at is not None,
        }
        for daily in daily_rows
    ]
    month.totals = totals
    month.contexts = contexts
    month.titles = titles
    month.water = _aggregate_water(daily_rows)
    month.todo = _aggregate_todo(daily_rows)
    month.rewards = rewards
    month.absolute = absolute
    if final:
        month.status = "consolidated"
        month.consolidated_at = now()
    else:
        month.status = "active"

    _relink_daily(month, daily_rows)
    db.session.flush()
    if commit:
        db.session.commit()
    return month


def rebuild_month_for_date(d: date_, final: bool = False, commit: bool = True) -> Month:
    start_date, end_date = month_bounds(d)
    return rebuild_month(start_date, end_date, final=final, commit=commit)


def consolidate_month_for_date(d: date_, commit: bool = True) -> Month:
    return rebuild_month_for_date(d, final=True, commit=commit)
