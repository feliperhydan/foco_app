import copy
import unittest
from datetime import datetime, timedelta, date

from app import create_app
from app.extensions import db
from app.models import Configuration, Daily, Reward, Session, TodoItem, Week, Month, MonthDaily, WishlistItem
from app.services import (
    config_service,
    cycles_service,
    daily_service,
    engine,
    temporal_service,
    todo_service,
    water_service,
    week_service,
    month_service,
)
from app.services.clock import reset, set_offset_days, today
from app.services.progress_service import week_bounds
from app.services.month_service import month_bounds
from app.services.time_utils import utcnow_naive
from app.services.wishlist_service import activate_wishlist_item
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class MonthContractTest(unittest.TestCase):
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
            weekly_goal=5,
            water_bottle_ml=750,
            water_goal_ml=3000,
        )
        db.session.add(cfg)
        db.session.add_all([
            Reward(title="Minimo diario", progress_type="daily_minimum", active=True),
            Reward(title="Ideal diario", progress_type="daily_ideal", active=True),
            Reward(title="Meta semanal", progress_type="weekly", active=True),
            Reward(title="Absoluto", progress_type="absolute", active=True),
            TodoItem(text="Item 1", done=False, order=1),
            TodoItem(text="Item 2", done=False, order=2),
        ])
        wish = WishlistItem(title="Projeto absoluto", description="", suggested_goal=50, status="wishlist")
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

    def test_month_bounds(self):
        d1 = date(2026, 2, 15)
        start, end = month_bounds(d1)
        self.assertEqual(start, date(2026, 2, 1))
        self.assertEqual(end, date(2026, 2, 28))  # não bissexto

        d2 = date(2028, 2, 15)
        start, end = month_bounds(d2)
        self.assertEqual(start, date(2028, 2, 1))
        self.assertEqual(end, date(2028, 2, 29))  # bissexto

        d3 = date(2026, 8, 17)
        start, end = month_bounds(d3)
        self.assertEqual(start, date(2026, 8, 1))
        self.assertEqual(end, date(2026, 8, 31))

    def test_month_with_one_daily(self):
        day_a = today()
        self._complete_focus("Solo")
        self._complete_rest("short")
        water_service.log_bottle()

        # Avança 32 dias para forçar a consolidação do mês de day_a
        self._close_current_day_by_moving_to(32)

        start_date, end_date = month_bounds(day_a)
        month = Month.query.filter_by(start_date=start_date, end_date=end_date).first()
        self.assertIsNotNone(month)
        self.assertEqual(month.status, "consolidated")
        self.assertEqual(len(month.daily_links), 1)
        self.assertEqual(month.daily_links[0].date, day_a)

        payload = month.as_dict()
        self.assertEqual(payload["totals"]["focus"], {"cycles_completed": 1, "minutes_completed": 35})
        self.assertEqual(payload["totals"]["rest_short"], {"cycles_completed": 1, "minutes_completed": 5})
        self.assertEqual(payload["water"]["total_bottles_consumed"], 1)

    def test_month_with_multiple_dailies(self):
        day_a = self._build_rich_day(0, ["Foco 1", "Foco 2"])
        self._close_current_day_by_moving_to(1)
        day_b = self._build_rich_day(1, ["Foco 3"], water=False)
        self._close_current_day_by_moving_to(32)

        start_date, end_date = month_bounds(day_a)
        month = month_service.rebuild_month(start_date, end_date).as_dict()

        self.assertEqual(month["totals"]["focus"], {"cycles_completed": 3, "minutes_completed": 105})
        self.assertEqual(month["water"]["total_bottles_consumed"], 1)
        self.assertEqual(len(month["days"]), 2)
        dates = {item["date"] for item in month["days"]}
        self.assertEqual(dates, {day_a.isoformat(), day_b.isoformat()})

    def test_days_without_activity_do_not_generate_fictitious_dailies(self):
        day_a = today()
        self._complete_focus("Activity")
        # Avança 5 dias (mesmo mês) e não faz nada, depois avança 32 dias para virar o mês
        set_offset_days(5)
        self._close_current_day_by_moving_to(32)

        start_date, end_date = month_bounds(day_a)
        month = Month.query.filter_by(start_date=start_date, end_date=end_date).first().as_dict()

        self.assertEqual(len(month["days"]), 1)
        # Nenhum Daily intermediário deve ter sido criado
        self.assertEqual(Daily.query.count(), 2)  # day_a e day_a + 32 dias

    def test_multiple_configuration_contexts(self):
        day_a = today()
        self._complete_focus("Config A")
        water_service.log_bottle()

        # Atualiza a configuração (foco=45, garrafa=500)
        config_service.update_configuration(focus_minutes=45, water_bottle_ml=500, water_goal_ml=2000)
        self._complete_focus("Config B")
        water_service.log_bottle()

        self._close_current_day_by_moving_to(32)
        start_date, end_date = month_bounds(day_a)
        month = Month.query.filter_by(start_date=start_date, end_date=end_date).first().as_dict()

        # Deve possuir dois contextos de ciclo
        self.assertEqual(len(month["contexts"]), 2)
        ctx_a = month["contexts"][0]
        ctx_b = month["contexts"][1]
        self.assertEqual(ctx_a["configuration"]["focus_minutes"], 35)
        self.assertEqual(ctx_a["focus"]["cycles_completed"], 1)
        self.assertEqual(ctx_b["configuration"]["focus_minutes"], 45)
        self.assertEqual(ctx_b["focus"]["cycles_completed"], 1)

        # Deve possuir dois contextos de água
        self.assertEqual(len(month["water"]["contexts"]), 2)
        w_a = month["water"]["contexts"][0]
        w_b = month["water"]["contexts"][1]
        self.assertEqual(w_a["bottle_capacity_ml"], 750)
        self.assertEqual(w_a["water_consumed_ml"], 750)
        self.assertEqual(w_b["bottle_capacity_ml"], 500)
        self.assertEqual(w_b["water_consumed_ml"], 500)

    def test_titles_textual_and_null(self):
        day_a = today()
        self._complete_focus("Trabalho")
        self._complete_focus(None)
        self._complete_focus("Trabalho")

        self._close_current_day_by_moving_to(32)
        start_date, end_date = month_bounds(day_a)
        month = Month.query.filter_by(start_date=start_date, end_date=end_date).first().as_dict()

        title_map = {item["text"]: item for item in month["titles"]}
        self.assertEqual(title_map["Trabalho"]["cycle_count"], 2)
        self.assertEqual(title_map[None]["cycle_count"], 1)

    def test_rewards_and_absolute_progress(self):
        day_a = today()
        # Faz 3 focos para completar o mínimo (2) e o ideal (3)
        self._complete_focus("A")
        self._complete_focus("B")
        self._complete_focus("C")
        todo_service.toggle_item(1)

        self._close_current_day_by_moving_to(32)
        start_date, end_date = month_bounds(day_a)
        month = Month.query.filter_by(start_date=start_date, end_date=end_date).first().as_dict()

        self.assertEqual(month["todo"]["items_total"], 2)
        self.assertEqual(month["todo"]["items_completed"], 1)

        # Recompensas
        self.assertEqual(month["rewards"]["daily_minimum"]["completed_count"], 1)
        self.assertEqual(month["rewards"]["daily_ideal"]["completed_count"], 1)
        self.assertEqual(month["rewards"]["daily_minimum"]["titles"][0]["title"], "Minimo diario")

        # Progresso absoluto
        self.assertEqual(month["absolute"]["title"], "Projeto absoluto")
        self.assertEqual(month["absolute"]["start"]["current_cycles"], 0)
        self.assertEqual(month["absolute"]["end"]["current_cycles"], 3)
        self.assertEqual(month["absolute"]["cycles_computed"], 3)

    def test_current_month_progressive(self):
        day_a = today()
        self._complete_focus("A")

        # reconstrói o mês vigente (sem fechar/consolidadar)
        month = month_service.rebuild_month_for_date(day_a).as_dict()
        self.assertEqual(month["status"], "active")
        self.assertIsNone(month["consolidated_at"])
        self.assertEqual(month["totals"]["focus"]["cycles_completed"], 1)

        # realiza mais atividade no mesmo mês
        self._complete_focus("B")
        month = month_service.rebuild_month_for_date(day_a).as_dict()
        self.assertEqual(month["totals"]["focus"]["cycles_completed"], 2)

    def test_month_rollover_and_idle_months(self):
        day_a = today()
        self._complete_focus("A")
        start_a, end_a = month_bounds(day_a)

        # Salta 3 meses (90 dias) e inicia um ciclo de foco no novo mês
        self._close_current_day_by_moving_to(90)
        day_d = today()

        # O primeiro mês deve ter sido consolidado
        month_a = Month.query.filter_by(start_date=start_a, end_date=end_a).first()
        self.assertIsNotNone(month_a)
        self.assertEqual(month_a.status, "consolidated")
        self.assertIsNotNone(month_a.consolidated_at)

        # Nenhum Month deve ter sido criado para os meses intermediários ociosos
        self.assertEqual(Month.query.count(), 2)  # Mês A e Mês D
        start_d, end_d = month_bounds(day_d)
        self.assertIsNotNone(Month.query.filter_by(start_date=start_d, end_date=end_d).first())

    def test_rebuild_idempotence(self):
        day_a = today()
        self._complete_focus("A")
        start_date, end_date = month_bounds(day_a)

        # Reconstrói repetidamente
        month_service.rebuild_month(start_date, end_date)
        month_service.rebuild_month(start_date, end_date)
        month_service.rebuild_month(start_date, end_date)

        month = Month.query.filter_by(start_date=start_date, end_date=end_date).first()
        self.assertEqual(MonthDaily.query.filter_by(month_id=month.id).count(), 1)
        self.assertEqual(len(month.as_dict()["contexts"]), 1)

    def test_historical_immutability(self):
        day_a = today()
        self._complete_focus("A1")
        self._complete_focus("A2")
        self._complete_focus("A3")

        start_date, end_date = month_bounds(day_a)
        self._close_current_day_by_moving_to(32)

        # Congela o estado consolidado
        frozen = copy.deepcopy(Month.query.filter_by(start_date=start_date, end_date=end_date).first().as_dict())

        # Faz alterações operacionais atuais
        config_service.update_configuration(focus_minutes=90)
        for reward in Reward.query.all():
            reward.title = "Título Alterado"
        self.absolute.title = "Absoluto Alterado"
        todo_service.toggle_item(1)
        water_service.log_bottle()

        temporal_service.reconcile_temporal_state()
        db.session.commit()

        # O Month antigo deve permanecer intacto
        current = Month.query.filter_by(start_date=start_date, end_date=end_date).first().as_dict()
        self.assertEqual(current, frozen)
        self.assertEqual(current["absolute"]["title"], "Projeto absoluto")
        self.assertEqual(current["rewards"]["daily_minimum"]["titles"][0]["title"], "Minimo diario")

    def test_month_reconstructable_from_daily_only(self):
        day_a = today()
        self._complete_focus("A")
        start_date, end_date = month_bounds(day_a)

        self._close_current_day_by_moving_to(32)
        original = copy.deepcopy(Month.query.filter_by(start_date=start_date, end_date=end_date).first().as_dict())

        # Exclui o Month do banco
        Month.query.filter_by(start_date=start_date, end_date=end_date).delete()
        db.session.commit()

        # Reconstrói e compara
        rebuilt = month_service.rebuild_month(start_date, end_date, final=True).as_dict()
        original_no_time = {**original, "consolidated_at": None}
        rebuilt_no_time = {**rebuilt, "consolidated_at": None}
        self.assertEqual(rebuilt_no_time, original_no_time)

    def test_relation_with_week(self):
        day_a = today()
        self._complete_focus("A")

        start_w, end_w = week_bounds(day_a)
        start_m, end_m = month_bounds(day_a)

        # Reconstrói a Week
        week = week_service.rebuild_week(start_w, end_w, final=True).as_dict()
        # Reconstrói o Month
        month = month_service.rebuild_month(start_m, end_m, final=True).as_dict()

        # Modifica a Week e garante que o Month não mudou
        db.session.query(Week).filter_by(start_date=start_w).delete()
        db.session.commit()
        month_after_week_delete = Month.query.filter_by(start_date=start_m).first().as_dict()
        self.assertEqual(month_after_week_delete, month)

        # Modifica o Month e garante que a Week não é afetada ao reconstruir
        db.session.query(Month).filter_by(start_date=start_m).delete()
        db.session.commit()
        week_rebuilt = week_service.rebuild_week(start_w, end_w, final=True).as_dict()
        # Ambos continuam derivados dos mesmos Dailies
        self.assertEqual(week_rebuilt["totals"]["focus"], week["totals"]["focus"])


if __name__ == "__main__":
    unittest.main()
