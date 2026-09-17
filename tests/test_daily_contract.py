import copy
import unittest
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Configuration, Daily, Reward, Session, TodoItem, WishlistItem
from app.services import (
    config_service,
    cycles_service,
    daily_service,
    engine,
    temporal_service,
    todo_service,
    water_service,
)
from app.services.clock import reset, set_offset_days, today
from app.services.time_utils import utcnow_naive
from app.services.wishlist_service import activate_wishlist_item
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class DailyContractTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        reset()
        self._seed_base()

    def tearDown(self):
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
            weekly_goal=4,
            water_bottle_ml=750,
            water_goal_ml=3000,
        )
        db.session.add(cfg)
        db.session.add_all([
            Reward(title="Minimo historico", progress_type="daily_minimum", active=True),
            Reward(title="Ideal historico", progress_type="daily_ideal", active=True),
            Reward(title="Semanal historico", progress_type="weekly", active=True),
            Reward(title="Absoluto recompensa", progress_type="absolute", active=True),
            TodoItem(text="Item 1", done=False, order=1),
            TodoItem(text="Item 2", done=False, order=2),
        ])
        wish = WishlistItem(title="Projeto absoluto", description="", suggested_goal=20, status="wishlist")
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

    def _advance_and_start_next_day(self, days=1):
        set_offset_days(days)
        next_day = today()
        cycles_service.start_focus_cycle()
        return next_day

    def test_simple_day_contract_and_raw_fields(self):
        day_a = today()
        self._complete_focus("Estudo")
        self._complete_focus(None)
        self._complete_focus("Pesquisa")
        self._complete_focus("Estudo")
        self._complete_rest("short")
        self._complete_rest("long")
        water_service.log_bottle()
        todo_service.toggle_item(1)

        self._advance_and_start_next_day()
        daily = Daily.query.filter_by(date=day_a).first().as_dict()

        self.assertEqual(daily["date"], day_a.isoformat())
        self.assertTrue(daily["session_started"])
        self.assertIsNotNone(daily["consolidated_at"])
        self.assertEqual(len(daily["cycle_contexts"]), 1)

        context = daily["cycle_contexts"][0]
        self.assertEqual(context["configuration"]["focus_minutes"], 35)
        self.assertEqual(context["configuration"]["short_break_minutes"], 5)
        self.assertEqual(context["configuration"]["long_break_minutes"], 20)
        self.assertEqual(context["configuration"]["daily_minimum_goal"], 2)
        self.assertEqual(context["configuration"]["daily_ideal_goal"], 3)
        self.assertEqual(context["configuration"]["weekly_goal"], 4)
        self.assertEqual(context["focus"]["cycles_completed"], 4)
        self.assertEqual(context["focus"]["minutes_completed"], 140)
        self.assertEqual(context["rest_short"], {"cycles_completed": 1, "minutes_completed": 5})
        self.assertEqual(context["rest_long"], {"cycles_completed": 1, "minutes_completed": 20})
        self.assertEqual(context["extraordinary"], {"cycles": 1, "minutes": 35})
        self.assertEqual(context["focus"]["titles"], [
            {"text": "Estudo", "cycle_count": 2},
            {"text": None, "cycle_count": 1},
            {"text": "Pesquisa", "cycle_count": 1},
        ])
        self.assertEqual(sum(t["cycle_count"] for t in context["focus"]["titles"]), 4)
        self.assertEqual(daily["todo"], {"items_total": 2, "items_completed": 1})
        self.assertEqual(daily["water"]["contexts"], [{
            "context_id": 1,
            "bottle_capacity_ml": 750,
            "daily_goal_ml": 3000,
            "bottles_consumed": 1,
            "water_consumed_ml": 750,
        }])
        self.assertEqual(daily["rewards"]["daily_minimum"], {
            "title": "Minimo historico",
            "cycles_computed": 4,
            "goal": 2,
            "goal_completed": True,
        })
        self.assertEqual(daily["rewards"]["daily_ideal"], {
            "title": "Ideal historico",
            "cycles_computed": 4,
            "goal": 3,
            "goal_completed": True,
        })
        self.assertEqual(daily["rewards"]["weekly"], {
            "title": "Semanal historico",
            "cycles_computed": 4,
            "goal": 4,
            "goal_completed": True,
        })
        self.assertEqual(daily["rewards"]["absolute"]["start"], {"current_cycles": 0, "goal_cycles": 20})
        self.assertEqual(daily["rewards"]["absolute"]["end"], {"current_cycles": 4, "goal_cycles": 20})
        self.assertEqual(daily["rewards"]["absolute"]["cycles_computed"], 4)

    def test_three_configuration_contexts_do_not_mix_cycles(self):
        day_a = today()
        self._complete_focus("A")
        self._complete_rest("short")

        config_service.update_configuration(focus_minutes=45, short_break_minutes=7, long_break_minutes=25)
        self._complete_focus("B")
        self._complete_rest("long")

        config_service.update_configuration(focus_minutes=50, short_break_minutes=8, long_break_minutes=30)
        self._complete_focus("C")
        self._complete_focus("C")

        self._advance_and_start_next_day()
        contexts = Daily.query.filter_by(date=day_a).first().as_dict()["cycle_contexts"]

        self.assertEqual([c["configuration"]["focus_minutes"] for c in contexts], [35, 45, 50])
        self.assertEqual([c["focus"]["cycles_completed"] for c in contexts], [1, 1, 2])
        self.assertEqual([c["focus"]["minutes_completed"] for c in contexts], [35, 45, 100])
        self.assertEqual(contexts[0]["rest_short"], {"cycles_completed": 1, "minutes_completed": 5})
        self.assertEqual(contexts[1]["rest_long"], {"cycles_completed": 1, "minutes_completed": 25})
        self.assertEqual(contexts[2]["focus"]["titles"], [{"text": "C", "cycle_count": 2}])

    def test_todo_snapshot_is_final_for_day_and_immutable(self):
        day_a = today()
        todo_service.create_item("Item 3")
        todo_service.toggle_item(1)
        self._complete_focus("A")
        self._advance_and_start_next_day()
        frozen = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        todo_service.toggle_item(2)
        todo_service.delete_item(3)
        temporal_service.reconcile_temporal_state()

        self.assertEqual(frozen["todo"], {"items_total": 3, "items_completed": 1})
        self.assertEqual(Daily.query.filter_by(date=day_a).first().as_dict(), frozen)

    def test_water_contexts_follow_configuration_snapshots(self):
        day_a = today()
        self._complete_focus("A")
        water_service.log_bottle()

        config_service.update_configuration(water_bottle_ml=500, water_goal_ml=2500)
        water_service.log_bottle()

        self._advance_and_start_next_day()
        water = Daily.query.filter_by(date=day_a).first().as_dict()["water"]

        self.assertEqual(water["contexts"], [
            {
                "context_id": 1,
                "bottle_capacity_ml": 750,
                "daily_goal_ml": 3000,
                "bottles_consumed": 1,
                "water_consumed_ml": 750,
            },
            {
                "context_id": 2,
                "bottle_capacity_ml": 500,
                "daily_goal_ml": 2500,
                "bottles_consumed": 1,
                "water_consumed_ml": 500,
            },
        ])

    def test_rewards_absolute_and_immutability_after_operational_changes(self):
        day_a = today()
        for title in ["A1", "A2", "A3", "A4"]:
            self._complete_focus(title)
        self._advance_and_start_next_day()
        frozen = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        config_service.update_configuration(focus_minutes=60, daily_minimum_goal=9)
        for reward in Reward.query.all():
            reward.title = "Titulo novo"
        self.absolute.title = "Absoluto alterado"
        self.absolute.current_count = 19
        todo_service.toggle_item(2)
        self._complete_focus("Novo dia")
        temporal_service.reconcile_temporal_state()
        db.session.commit()

        current = Daily.query.filter_by(date=day_a).first().as_dict()
        self.assertEqual(current, frozen)
        self.assertEqual(current["rewards"]["daily_minimum"]["title"], "Minimo historico")
        self.assertEqual(current["rewards"]["daily_ideal"]["title"], "Ideal historico")
        self.assertEqual(current["rewards"]["weekly"]["title"], "Semanal historico")
        self.assertEqual(current["rewards"]["absolute"]["title"], "Projeto absoluto")
        self.assertNotEqual(
            current["rewards"]["absolute"]["start"],
            current["rewards"]["absolute"]["end"],
        )

    def test_day_rollover_idle_days_and_repeated_reconciliation_are_idempotent(self):
        day_a = today()
        self._complete_focus("A")
        self._complete_focus(None)

        set_offset_days(2)
        day_c = today()
        cycles_service.start_focus_cycle()

        daily_a = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())
        self.assertEqual(Daily.query.count(), 2)
        self.assertIsNone(Daily.query.filter_by(date=day_a + timedelta(days=1)).first())
        self.assertIsNotNone(Daily.query.filter_by(date=day_c).first())
        self.assertEqual(
            [(s.date, s.status) for s in Session.query.order_by(Session.date, Session.id).all()],
            [(day_a, "ended"), (day_c, "active")],
        )

        temporal_service.reconcile_temporal_state()
        temporal_service.reconcile_temporal_state()
        self.assertEqual(Daily.query.count(), 2)
        self.assertEqual(Daily.query.filter_by(date=day_a).first().as_dict(), daily_a)

        contexts = daily_a["cycle_contexts"]
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["focus"]["cycles_completed"], 2)
        self.assertEqual(sum(t["cycle_count"] for t in contexts[0]["focus"]["titles"]), 2)


if __name__ == "__main__":
    unittest.main()
