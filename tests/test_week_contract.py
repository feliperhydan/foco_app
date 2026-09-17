import copy
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import Configuration, Daily, Reward, Session, TodoItem, Week, WishlistItem
from app.services import (
    config_service,
    cycles_service,
    daily_service,
    engine,
    temporal_service,
    todo_service,
    water_service,
    week_service,
)
from app.services.clock import reset, set_offset_days, today
from app.services.progress_service import week_bounds
from app.services.time_utils import utcnow_naive
from app.services.wishlist_service import activate_wishlist_item
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class WeekContractTest(unittest.TestCase):
    def setUp(self):
        # Patch utcnow_naive to return a fixed Monday (2026-08-24 10:00:00)
        # to ensure date-dependent calculations are stable regardless of actual run date.
        self.patcher = patch("app.services.clock.utcnow_naive", return_value=datetime(2026, 8, 24, 10, 0, 0))
        self.mock_utcnow = self.patcher.start()

        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        reset()
        self._seed_base()

    def tearDown(self):
        self.patcher.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _seed_base(self):
        cfg = Configuration(
            valid_from=utcnow_naive(),
            focus_minutes=35,
            short_break_minutes=5,
            long_break_minutes=20,
            cycles_per_session=4,
            daily_minimum_goal=2,
            daily_ideal_goal=3,
            weekly_goal=5,
            water_bottle_ml=750,
            water_goal_ml=3000,
        )
        db.session.add(cfg)
        db.session.add_all([
            Reward(title="Minimo semanal", progress_type="daily_minimum", active=True),
            Reward(title="Ideal semanal", progress_type="daily_ideal", active=True),
            Reward(title="Meta semanal", progress_type="weekly", active=True),
            Reward(title="Absoluto semanal", progress_type="absolute", active=True),
            TodoItem(text="Item 1", done=False, order=1),
            TodoItem(text="Item 2", done=False, order=2),
        ])
        wish = WishlistItem(title="Projeto semanal", description="", suggested_goal=50, status="wishlist")
        db.session.add(wish)
        db.session.commit()
        self.absolute = activate_wishlist_item(wish.id)

    def _complete_focus(self, title=None):
        cycle = cycles_service.start_focus_cycle()
        result = engine.complete_focus_cycle(cycle.id, title=title)
        self.assertTrue(result["ok"])
        return cycle

    def _complete_rest(self, kind):
        rest = cycles_service.start_rest_cycle(kind)
        completed = cycles_service.complete_rest_cycle(rest.id)
        self.assertIsNotNone(completed)
        return completed

    def _move_to_day_with_activity(self, offset):
        set_offset_days(offset)
        return today()

    def _close_current_day_by_moving_to(self, offset):
        set_offset_days(offset)
        cycles_service.start_focus_cycle()

    def _build_rich_day(self, offset, titles, water=True, todo_toggle_id=None):
        day = self._move_to_day_with_activity(offset)
        for title in titles:
            self._complete_focus(title)
        self._complete_rest("short")
        self._complete_rest("long")
        if water:
            water_service.log_bottle()
        if todo_toggle_id is not None:
            todo_service.toggle_item(todo_toggle_id)
        return day

    def test_simple_week_aggregates_daily_raw_data(self):
        day_a = self._build_rich_day(0, ["Estudo", None, "Pesquisa", "Estudo"], todo_toggle_id=1)
        self._close_current_day_by_moving_to(1)
        day_b = self._build_rich_day(1, ["Pesquisa"], water=False)
        self._close_current_day_by_moving_to(7)

        start_date, end_date = week_bounds(day_a)
        week = week_service.rebuild_week(start_date, end_date).as_dict()

        self.assertEqual(week["start_date"], start_date.isoformat())
        self.assertEqual(week["end_date"], end_date.isoformat())
        self.assertEqual(week["status"], "consolidated")
        self.assertEqual(week["totals"]["focus"], {"cycles_completed": 5, "minutes_completed": 175})
        self.assertEqual(week["totals"]["rest_short"], {"cycles_completed": 2, "minutes_completed": 10})
        self.assertEqual(week["totals"]["rest_long"], {"cycles_completed": 2, "minutes_completed": 40})
        self.assertEqual(week["totals"]["extraordinary"], {"cycles": 1, "minutes": 35})
        self.assertEqual({item["date"] for item in week["days"]}, {day_a.isoformat(), day_b.isoformat()})
        self.assertEqual(week["todo"]["items_total"], 4)
        self.assertEqual(week["todo"]["items_completed"], 1)
        self.assertNotIn("pct", str(week["todo"]).lower())
        self.assertEqual(week["water"]["total_bottles_consumed"], 1)
        self.assertEqual(week["water"]["total_water_consumed_ml"], 750)
        self.assertEqual(week["rewards"]["daily_minimum"]["completed_count"], 1)
        self.assertEqual(week["rewards"]["daily_ideal"]["completed_count"], 1)
        self.assertEqual(week["absolute"]["start"], {"current_cycles": 0, "goal_cycles": 50})
        self.assertEqual(week["absolute"]["end"], {"current_cycles": 5, "goal_cycles": 50})
        self.assertEqual(week["absolute"]["cycles_computed"], 5)

    def test_one_daily_week_and_daily_is_not_modified_by_week_rebuild(self):
        day_a = today()
        self._complete_focus("Unico")
        self._complete_rest("short")
        water_service.log_bottle()

        set_offset_days(7)
        cycles_service.start_focus_cycle()
        daily_before = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        week = week_service.rebuild_week_for_date(day_a).as_dict()
        daily_after = Daily.query.filter_by(date=day_a).first().as_dict()

        self.assertEqual(daily_after, daily_before)
        self.assertEqual(len(week["days"]), 1)
        self.assertEqual(week["totals"]["focus"], {"cycles_completed": 1, "minutes_completed": 35})
        self.assertEqual(week["totals"]["rest_short"], {"cycles_completed": 1, "minutes_completed": 5})
        self.assertEqual(week["titles"], [{"text": "Unico", "cycle_count": 1, "days": [{"date": day_a.isoformat(), "cycle_count": 1}]}])

    def test_empty_daily_and_empty_week_do_not_invent_activity(self):
        explicit_day = today()
        daily_service.ensure_daily_for_date(explicit_day, session_started=False)
        week = week_service.ensure_empty_week_for_date(explicit_day).as_dict()

        self.assertEqual(len(week["days"]), 1)
        self.assertFalse(week["days"][0]["session_started"])
        self.assertEqual(week["totals"]["focus"], {"cycles_completed": 0, "minutes_completed": 0})

        empty_week_day = explicit_day + timedelta(days=14)
        empty_week = week_service.ensure_empty_week_for_date(empty_week_day).as_dict()
        self.assertEqual(empty_week["days"], [])
        self.assertEqual(empty_week["totals"]["focus"], {"cycles_completed": 0, "minutes_completed": 0})
        self.assertEqual(Daily.query.filter(Daily.date >= empty_week_day).count(), 0)

    def test_configuration_contexts_titles_water_todo_and_rewards_are_aggregated(self):
        day_a = today()
        self._complete_focus("Estudo")
        self._complete_focus(None)
        water_service.log_bottle()

        config_service.update_configuration(focus_minutes=45, water_bottle_ml=500, water_goal_ml=2500)
        self._complete_focus("Pesquisa")
        self._complete_focus("Estudo")
        water_service.log_bottle()
        todo_service.toggle_item(1)

        self._close_current_day_by_moving_to(1)
        day_b = today()
        config_service.update_configuration(focus_minutes=50, short_break_minutes=8, long_break_minutes=30)
        self._complete_focus("Pesquisa")
        self._complete_focus(None)
        water_service.log_bottle()
        todo_service.toggle_item(2)

        self._close_current_day_by_moving_to(7)
        week = week_service.rebuild_week_for_date(day_a).as_dict()

        self.assertEqual([ctx["configuration"]["focus_minutes"] for ctx in week["contexts"]], [35, 45, 50])
        self.assertEqual([ctx["focus"]["cycles_completed"] for ctx in week["contexts"]], [2, 2, 2])
        self.assertEqual([ctx["focus"]["minutes_completed"] for ctx in week["contexts"]], [70, 90, 100])
        title_map = {entry["text"]: entry for entry in week["titles"]}
        self.assertEqual(title_map["Estudo"]["cycle_count"], 2)
        self.assertEqual(title_map["Pesquisa"]["cycle_count"], 2)
        self.assertEqual(title_map[None]["cycle_count"], 2)
        self.assertEqual(sum(entry["cycle_count"] for entry in week["titles"]), 6)
        self.assertEqual(
            sorted(day["date"] for day in title_map["Pesquisa"]["days"]),
            sorted([day_a.isoformat(), day_b.isoformat()]),
        )
        self.assertEqual(
            [(ctx["bottle_capacity_ml"], ctx["water_consumed_ml"]) for ctx in week["water"]["contexts"]],
            [(750, 750), (500, 1000)],
        )
        self.assertEqual(week["todo"]["items_total"], 4)
        self.assertEqual(week["todo"]["items_completed"], 2)
        self.assertEqual(week["rewards"]["daily_minimum"]["completed_count"], 2)
        self.assertEqual(week["rewards"]["daily_ideal"]["completed_count"], 1)
        self.assertEqual(week["rewards"]["weekly"]["completed_count"], 1)
        self.assertEqual(week["rewards"]["daily_minimum"]["titles"][0]["title"], "Minimo semanal")

    def test_week_rollover_multiple_idle_weeks_and_idempotence(self):
        day_a = today()
        self._complete_focus("A")
        start_a, end_a = week_bounds(day_a)

        set_offset_days(21)
        day_d = today()
        cycles_service.start_focus_cycle()

        week_a = Week.query.filter_by(start_date=start_a, end_date=end_a).first()
        self.assertIsNotNone(week_a)
        self.assertEqual(week_a.status, "consolidated")
        frozen = copy.deepcopy(week_a.as_dict())
        self.assertEqual(Week.query.count(), 2)

        temporal_service.reconcile_temporal_state()
        temporal_service.reconcile_temporal_state()
        self.assertEqual(Week.query.filter_by(start_date=start_a, end_date=end_a).first().as_dict(), frozen)
        self.assertEqual(Week.query.count(), 2)
        self.assertIsNone(Week.query.filter_by(start_date=start_a + timedelta(days=7)).first())
        self.assertIsNotNone(Week.query.filter_by(start_date=week_bounds(day_d)[0]).first())

    def test_current_week_can_be_rebuilt_progressively(self):
        day_a = today()
        self._complete_focus("A")
        week_a = week_service.rebuild_week_for_date(day_a).as_dict()
        self.assertEqual(week_a["status"], "active")
        self.assertEqual(week_a["totals"]["focus"], {"cycles_completed": 1, "minutes_completed": 35})
        self.assertIsNone(week_a["consolidated_at"])

        set_offset_days(1)
        day_b = today()
        self._complete_focus("B")
        self._complete_focus(None)
        week_b = week_service.rebuild_week_for_date(day_b).as_dict()

        self.assertEqual(week_b["status"], "active")
        self.assertEqual(week_b["totals"]["focus"], {"cycles_completed": 3, "minutes_completed": 105})
        self.assertEqual({entry["date"] for entry in week_b["days"]}, {day_a.isoformat(), day_b.isoformat()})
        self.assertEqual(sum(entry["cycle_count"] for entry in week_b["titles"]), 3)

    def test_consolidated_week_is_immutable_after_operational_changes(self):
        day_a = today()
        for title in ["A1", "A2", "A3", "A4", "A5"]:
            self._complete_focus(title)
        start_a, end_a = week_bounds(day_a)

        set_offset_days(7)
        cycles_service.start_focus_cycle()
        frozen = copy.deepcopy(Week.query.filter_by(start_date=start_a, end_date=end_a).first().as_dict())

        config_service.update_configuration(focus_minutes=90)
        for reward in Reward.query.all():
            reward.title = "Titulo atual"
        self.absolute.title = "Absoluto atual"
        self.absolute.current_count = 40
        todo_service.toggle_item(1)
        water_service.log_bottle()
        self._complete_focus("Semana nova")
        temporal_service.reconcile_temporal_state()
        db.session.commit()

        current = Week.query.filter_by(start_date=start_a, end_date=end_a).first().as_dict()
        self.assertEqual(current, frozen)
        self.assertEqual(current["absolute"]["end"], {"current_cycles": 5, "goal_cycles": 50})
        self.assertEqual(current["rewards"]["weekly"]["titles"][0]["title"], "Meta semanal")

    def test_week_can_be_reconstructed_from_daily_only(self):
        day_a = today()
        self._complete_focus("A")
        self._complete_focus("B")
        start_a, end_a = week_bounds(day_a)

        set_offset_days(7)
        cycles_service.start_focus_cycle()
        original = copy.deepcopy(Week.query.filter_by(start_date=start_a, end_date=end_a).first().as_dict())

        Week.query.filter_by(start_date=start_a, end_date=end_a).delete()
        db.session.commit()
        rebuilt = week_service.rebuild_week(start_a, end_a, final=True).as_dict()

        original_without_timestamp = {**original, "consolidated_at": None}
        rebuilt_without_timestamp = {**rebuilt, "consolidated_at": None}
        self.assertEqual(rebuilt_without_timestamp, original_without_timestamp)


if __name__ == "__main__":
    unittest.main()
