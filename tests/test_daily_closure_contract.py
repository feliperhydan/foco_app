"""
Testes de contrato do Daily historico — fechamento definitivo.

Testa especificamente:
  A. Timeline individual dos ciclos (focus_timeline)
  B. AbsoluteProgressDailyLog (start/end historico confiavel)
  C. Titulo historico de recompensas (inclusive nao concluidas)
  D. Agua com consumo zero preserva goal/bottle
  E. Agua com mudanca de configuracao preserva historicos distintos
  F. Sessoes: snapshot minimo historico
  G. Imutabilidade geral apos consolidacao
  H. Idempotencia de consolidacao
  I. Viagem temporal (Daily A nao recebe dados de B/C)
"""
import copy
import unittest
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import (
    AbsoluteProgressDailyLog,
    Configuration,
    Daily,
    Reward,
    Session,
    TodoItem,
    WishlistItem,
)
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


class DailyContractClosureTest(unittest.TestCase):
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
            water_bottle_ml=500,
            water_goal_ml=4000,
        )
        db.session.add(cfg)
        db.session.add_all([
            Reward(title="Minimo", progress_type="daily_minimum", active=True),
            Reward(title="Ideal", progress_type="daily_ideal", active=True),
            Reward(title="Semanal", progress_type="weekly", active=True),
            Reward(title="Absoluto R", progress_type="absolute", active=True),
            TodoItem(text="Item 1", done=False, order=1),
            TodoItem(text="Item 2", done=False, order=2),
        ])
        wish = WishlistItem(title="Projeto", description="", suggested_goal=20, status="wishlist")
        db.session.add(wish)
        db.session.commit()
        self.absolute = activate_wishlist_item(wish.id)

    def _focus(self, title=None):
        cycle = cycles_service.start_focus_cycle()
        result = engine.complete_focus_cycle(cycle.id, title=title)
        self.assertTrue(result["ok"])
        return cycle

    def _advance(self, days=1):
        set_offset_days(days)
        return today()

    def _advance_and_trigger(self, days=1):
        day = self._advance(days)
        cycles_service.start_focus_cycle()
        return day

    # ------------------------------------------------------------------
    # A. Timeline individual dos ciclos
    # ------------------------------------------------------------------

    def test_A_focus_timeline_preserves_chronological_order_and_nulls(self):
        day_a = today()
        self._focus("Estudar")
        self._focus("Ler")
        self._focus(None)
        self._focus("Estudar")

        self._advance_and_trigger()
        d = Daily.query.filter_by(date=day_a).first().as_dict()

        timeline = d["focus_timeline"]
        self.assertEqual(len(timeline), 4)
        self.assertEqual(timeline[0]["title"], "Estudar")
        self.assertEqual(timeline[1]["title"], "Ler")
        self.assertIsNone(timeline[2]["title"])
        self.assertEqual(timeline[3]["title"], "Estudar")
        # completed_at devem ser strings ISO e conter configuration_id (GAP #2)
        for entry in timeline:
            self.assertIsNotNone(entry["completed_at"])
            self.assertIsNotNone(entry["configuration_id"])

        # Contexto de configuração deve conter configuration_id, started_at e ended_at (GAP #1)
        contexts = d["cycle_contexts"]
        self.assertGreaterEqual(len(contexts), 1)
        for context in contexts:
            self.assertIsNotNone(context["configuration_id"])
            self.assertIsNotNone(context["started_at"])
            # ended_at pode ser None para a configuração ainda ativa

    def test_A_timeline_immutable_after_consolidation(self):
        day_a = today()
        self._focus("Antes")
        self._advance_and_trigger()
        frozen = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        # Conclui mais ciclos no dia seguinte — nao devem contaminar o historico de day_a
        self._focus("Depois")
        temporal_service.reconcile_temporal_state()

        current = Daily.query.filter_by(date=day_a).first().as_dict()
        self.assertEqual(current["focus_timeline"], frozen["focus_timeline"])
        self.assertEqual(len(frozen["focus_timeline"]), 1)
        self.assertEqual(frozen["focus_timeline"][0]["title"], "Antes")

    # ------------------------------------------------------------------
    # B. AbsoluteProgressDailyLog
    # ------------------------------------------------------------------

    def test_B_absolute_daily_log_records_start_and_end_correctly(self):
        day_a = today()
        # Absoluto começa em 0; fazemos 8 ciclos
        for _ in range(8):
            self._focus("Ciclo")

        logs = AbsoluteProgressDailyLog.query.filter_by(
            date=day_a, absolute_progress_id=self.absolute.id
        ).all()
        self.assertEqual(len(logs), 1)
        log = logs[0]
        self.assertEqual(log.start_count, 0)
        self.assertEqual(log.end_count, 8)

    def test_B_absolute_log_preserved_after_live_state_change(self):
        day_a = today()
        for _ in range(8):
            self._focus("Ciclo")

        self._advance_and_trigger()
        frozen = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        # Altera current_count vivo — nao deve mudar o historico de day_a
        self.absolute.current_count = 999
        db.session.commit()
        temporal_service.reconcile_temporal_state()

        current = Daily.query.filter_by(date=day_a).first().as_dict()
        self.assertEqual(current["rewards"]["absolute"]["start"], frozen["rewards"]["absolute"]["start"])
        self.assertEqual(current["rewards"]["absolute"]["end"], frozen["rewards"]["absolute"]["end"])
        self.assertEqual(current["rewards"]["absolute"]["start"]["current_cycles"], 0)
        self.assertEqual(current["rewards"]["absolute"]["end"]["current_cycles"], 8)

    def test_B_absolute_log_idempotent_per_day(self):
        day_a = today()
        self._focus("X")
        self._focus("X")

        logs = AbsoluteProgressDailyLog.query.filter_by(
            date=day_a, absolute_progress_id=self.absolute.id
        ).all()
        # Deve existir apenas 1 log por (date, absolute_progress_id)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].start_count, 0)
        self.assertEqual(logs[0].end_count, 2)

    def test_B_absolute_identity_frozen_across_objective_swap_same_title_goal(self):
        title = self.absolute.title
        goal = self.absolute.goal_cycles
        day_a = today()
        self._focus("A1")
        self._advance_and_trigger()

        self.absolute.status = "completed"
        self.absolute.completed_at = utcnow_naive()
        second_wish = WishlistItem(
            title=title,
            description="",
            suggested_goal=goal,
            status="wishlist",
        )
        db.session.add(second_wish)
        db.session.commit()
        absolute_b = activate_wishlist_item(second_wish.id)

        day_b = today()
        self._focus("B1")
        self._advance_and_trigger(2)

        daily_a = Daily.query.filter_by(date=day_a).first().as_dict()
        daily_b = Daily.query.filter_by(date=day_b).first().as_dict()
        abs_a = daily_a["rewards"]["absolute"]
        abs_b = daily_b["rewards"]["absolute"]

        self.assertEqual(abs_a["absolute_progress_id"], self.absolute.id)
        self.assertEqual(abs_b["absolute_progress_id"], absolute_b.id)
        self.assertEqual(abs_a["title"], title)
        self.assertEqual(abs_b["title"], title)
        self.assertEqual(abs_a["goal_cycles"], goal)
        self.assertEqual(abs_b["goal_cycles"], goal)

        frozen_a = copy.deepcopy(daily_a)
        frozen_b = copy.deepcopy(daily_b)
        self.absolute.title = "Nome A alterado"
        self.absolute.goal_cycles = 999
        self.absolute.current_count = 777
        absolute_b.title = "Nome B alterado"
        absolute_b.goal_cycles = 888
        absolute_b.current_count = 666
        db.session.commit()
        temporal_service.reconcile_temporal_state()

        self.assertEqual(Daily.query.filter_by(date=day_a).first().as_dict(), frozen_a)
        self.assertEqual(Daily.query.filter_by(date=day_b).first().as_dict(), frozen_b)

    def test_B_absolute_absence_is_null_not_live_current_count(self):
        self.absolute.status = "completed"
        self.absolute.completed_at = datetime.combine(today() - timedelta(days=1), datetime.min.time())
        db.session.commit()

        day_a = today()
        self._focus("Sem absoluto")
        self._advance_and_trigger()

        frozen = Daily.query.filter_by(date=day_a).first().as_dict()
        absolute = frozen["rewards"]["absolute"]
        self.assertIsNone(absolute["absolute_progress_id"])
        self.assertIsNone(absolute["start"])
        self.assertIsNone(absolute["end"])
        self.assertIsNone(absolute["cycles_computed"])

        self.absolute.current_count = 123
        db.session.commit()
        temporal_service.reconcile_temporal_state()
        self.assertEqual(Daily.query.filter_by(date=day_a).first().as_dict(), frozen)

    # ------------------------------------------------------------------
    # C. Titulo historico de recompensas — nao concluidas
    # ------------------------------------------------------------------

    def test_C_reward_title_frozen_for_unconquered_reward(self):
        day_a = today()
        # Completa apenas 1 ciclo — meta minima e 2, nao atinge
        self._focus("Um")
        self._advance_and_trigger()
        frozen = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        # Renomeia todas as recompensas
        for r in Reward.query.all():
            r.title = "Titulo novo"
        db.session.commit()
        temporal_service.reconcile_temporal_state()

        current = Daily.query.filter_by(date=day_a).first().as_dict()
        self.assertEqual(current["rewards"]["daily_minimum"]["title"], "Minimo")
        self.assertEqual(current["rewards"]["daily_ideal"]["title"], "Ideal")
        self.assertEqual(current["rewards"]["weekly"]["title"], "Semanal")
        self.assertEqual(current, frozen)

    def test_C_reward_title_from_achievement_snapshot_when_conquered(self):
        day_a = today()
        # Meta minima = 2; completa 2 ciclos
        self._focus("A")
        self._focus("B")
        self._advance_and_trigger()
        frozen = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        # Renomeia recompensa pos-conquista
        for r in Reward.query.all():
            r.title = "Novo titulo"
        db.session.commit()
        temporal_service.reconcile_temporal_state()

        current = Daily.query.filter_by(date=day_a).first().as_dict()
        # Titulo deve continuar sendo o snapshot da conquista, nao o novo nome
        self.assertEqual(current["rewards"]["daily_minimum"]["title"], "Minimo")
        self.assertEqual(current, frozen)

    # ------------------------------------------------------------------
    # D. Agua com consumo zero preserva goal/bottle
    # ------------------------------------------------------------------

    def test_D_water_zero_consumption_preserves_goal_and_bottle(self):
        day_a = today()
        # Garante sessao mas nao bebe agua
        self._focus("Sem agua")
        self._advance_and_trigger()

        d = Daily.query.filter_by(date=day_a).first().as_dict()
        water = d["water"]
        self.assertEqual(water["total_ml"], 0)
        self.assertEqual(water["bottles"], 0)
        # Meta e capacidade devem ser preservadas mesmo sem consumo
        self.assertEqual(water["goal_ml"], 4000)
        self.assertEqual(water["bottle_ml"], 500)
        # contexts pode ser vazia pois nao houve WaterLog
        self.assertEqual(water["contexts"], [])

    def test_D_water_zero_each_day_has_own_goal(self):
        day_a = today()
        self._focus("Dia A")
        self._advance(1)
        # Muda configuracao no dia B
        config_service.update_configuration(water_goal_ml=2500, water_bottle_ml=300)
        day_b = today()
        self._focus("Dia B")
        self._advance_and_trigger(2)

        daily_a = Daily.query.filter_by(date=day_a).first().as_dict()
        daily_b = Daily.query.filter_by(date=day_b).first().as_dict()

        self.assertEqual(daily_a["water"]["goal_ml"], 4000)
        self.assertEqual(daily_a["water"]["bottle_ml"], 500)
        self.assertEqual(daily_b["water"]["goal_ml"], 2500)
        self.assertEqual(daily_b["water"]["bottle_ml"], 300)

    # ------------------------------------------------------------------
    # E. Agua com mudanca de configuracao no mesmo dia
    # ------------------------------------------------------------------

    def test_E_water_multi_config_contexts_preserved(self):
        day_a = today()
        self._focus("A")
        water_service.log_bottle()  # cfg1: 500ml

        config_service.update_configuration(water_bottle_ml=750, water_goal_ml=3000)
        water_service.log_bottle()  # cfg2: 750ml

        self._advance_and_trigger()
        water = Daily.query.filter_by(date=day_a).first().as_dict()["water"]

        self.assertEqual(water["total_ml"], 1250)
        self.assertEqual(len(water["contexts"]), 2)
        bottles = [c["bottle_capacity_ml"] for c in water["contexts"]]
        self.assertIn(500, bottles)
        self.assertIn(750, bottles)

    # ------------------------------------------------------------------
    # F. Sessoes: snapshot minimo historico
    # ------------------------------------------------------------------

    def test_F_session_snapshot_captures_single_daily_study_session(self):
        day_a = today()
        self._focus("A")
        self._advance_and_trigger()

        d = Daily.query.filter_by(date=day_a).first().as_dict()
        session_snap = d["session"]

        self.assertTrue(session_snap["started"])
        self.assertNotIn("sessions_count", session_snap)
        self.assertIsNotNone(session_snap["started_at"])
        self.assertTrue(session_snap["ended_at"].endswith("23:59:59.999999"))

    def test_F_session_snapshot_false_when_no_session(self):
        # Cria Daily sem sessao (so reconciliacao passando por um dia sem atividade)
        day_a = today()
        # Avanca para o dia B sem abrir sessao em A
        set_offset_days(2)
        cycles_service.start_focus_cycle()  # abre sessao em B; reconcilia A
        temporal_service.reconcile_temporal_state()

        daily_a = Daily.query.filter_by(date=day_a).first()
        # Pode nao ter sido criado (sem sessao = sem Daily)
        if daily_a is not None:
            snap = daily_a.as_dict()["session"]
            self.assertIsNone(snap)

    def test_F_started_abandoned_cycle_is_not_active_study_day(self):
        day_a = today()
        cycle = cycles_service.start_focus_cycle()
        cycles_service.abandon_focus_cycle(cycle.id)
        self._advance_and_trigger()

        daily = Daily.query.filter_by(date=day_a).first().as_dict()
        self.assertFalse(daily["session_started"])
        self.assertIsNone(daily["session"])
        self.assertEqual(daily["focus_timeline"], [])
        self.assertEqual(daily["cycle_contexts"], [])

    def test_F_end_session_and_multiple_contexts_do_not_create_multiple_daily_sessions(self):
        day_a = today()
        first = self._focus("A")
        cycles_service.end_session(db.session.get(Session, first.session_id))
        config_service.update_configuration(focus_minutes=45)
        self._focus("B")

        self.assertEqual(Session.query.filter_by(date=day_a).count(), 1)
        self._advance_and_trigger()

        daily = Daily.query.filter_by(date=day_a).first().as_dict()
        session_snap = daily["session"]
        self.assertTrue(daily["session_started"])
        self.assertTrue(session_snap["started"])
        self.assertNotIn("sessions_count", session_snap)
        self.assertEqual(len(daily["focus_timeline"]), 2)
        self.assertGreaterEqual(len(daily["cycle_contexts"]), 2)

    # ------------------------------------------------------------------
    # G. Imutabilidade geral apos consolidacao
    # ------------------------------------------------------------------

    def test_G_full_immutability_after_consolidation(self):
        day_a = today()
        self._focus("A1")
        self._focus("A2")
        water_service.log_bottle()
        todo_service.toggle_item(1)

        self._advance_and_trigger()
        frozen = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        # Altera tudo o que e possivel
        config_service.update_configuration(focus_minutes=60, daily_minimum_goal=9,
                                             water_goal_ml=999, water_bottle_ml=111)
        for r in Reward.query.all():
            r.title = "Titulo alterado"
        self.absolute.title = "Absoluto alterado"
        self.absolute.current_count = 500
        todo_service.toggle_item(2)
        todo_service.create_item("Novo item")
        self._focus("Novo ciclo")
        temporal_service.reconcile_temporal_state()
        db.session.commit()

        current = Daily.query.filter_by(date=day_a).first().as_dict()
        self.assertEqual(current, frozen)

    # ------------------------------------------------------------------
    # H. Idempotencia de consolidacao
    # ------------------------------------------------------------------

    def test_H_consolidation_is_idempotent(self):
        day_a = today()
        self._focus("X")
        self._advance_and_trigger()

        first = copy.deepcopy(Daily.query.filter_by(date=day_a).first().as_dict())

        daily_service.consolidate_daily(day_a)
        daily_service.consolidate_daily(day_a)
        daily_service.consolidate_daily(day_a)

        second = Daily.query.filter_by(date=day_a).first().as_dict()
        self.assertEqual(first, second)

        # Nenhum log duplicado
        logs = AbsoluteProgressDailyLog.query.filter_by(date=day_a).all()
        self.assertLessEqual(len(logs), 1)

    # ------------------------------------------------------------------
    # I. Viagem temporal
    # ------------------------------------------------------------------

    def test_I_time_travel_daily_A_not_contaminated_by_B_and_C(self):
        day_a = today()
        self._focus("DiaA")
        self._focus("DiaA2")

        # Pula direto para o dia C sem abrir sessao no B
        set_offset_days(2)
        day_c = today()
        cycles_service.start_focus_cycle()  # isso dispara reconciliacao de A
        temporal_service.reconcile_temporal_state()

        daily_a = Daily.query.filter_by(date=day_a).first()
        self.assertIsNotNone(daily_a)

        d = daily_a.as_dict()

        # Timeline de A deve conter exatamente 2 ciclos de A
        self.assertEqual(len(d["focus_timeline"]), 2)
        for entry in d["focus_timeline"]:
            self.assertEqual(entry["title"], "DiaA" if entry == d["focus_timeline"][0] else "DiaA2")

        # Dia B (intermediario) nao deve ter Daily criado
        from datetime import date
        day_b = day_a + timedelta(days=1)
        self.assertIsNone(Daily.query.filter_by(date=day_b).first())

        # AbsoluteLog de A nao deve conter dados de C
        logs = AbsoluteProgressDailyLog.query.filter_by(date=day_a).all()
        if logs:
            self.assertEqual(logs[0].start_count, 0)
            self.assertEqual(logs[0].end_count, 2)

        logs_c = AbsoluteProgressDailyLog.query.filter_by(date=day_c).all()
        # Ciclo de C ainda em aberto (started), entao pode nao ter log
        # O importante e que log de A nao foi contaminado
        if logs_c:
            self.assertGreaterEqual(logs_c[0].start_count, 2)

    def test_B_absolute_log_fallback_intermediate_day_no_activity(self):
        # Dia A: absoluto incrementado de 0 para 2
        day_a = today()
        self._focus("A1")
        self._focus("A2")

        # Dia B (offset=1): sem ciclos de absoluto — apenas abre sessao
        self._advance(1)
        day_b = today()
        cycles_service.get_or_create_active_session()

        # Dia C (offset=2): faz 1 ciclo, absoluto vai de 2 para 3
        # (completa o ciclo para que AbsoluteProgressDailyLog seja criado em C)
        self._advance(2)
        day_c = today()
        self._focus("C1")

        # Dispara a reconciliacao (consolida A e B; C fica ativo)
        self._advance_and_trigger(3)

        # Verifica Dia B: start=2 e end=2 (sem atividade, mas entre A e C)
        daily_b = Daily.query.filter_by(date=day_b).first()
        self.assertIsNotNone(daily_b, "Daily do dia B deve existir (tinha sessao ativa)")
        abs_b = daily_b.as_dict()["rewards"]["absolute"]
        self.assertEqual(abs_b["start"]["current_cycles"], 2)
        self.assertEqual(abs_b["end"]["current_cycles"], 2)
        self.assertEqual(abs_b["cycles_computed"], 0)



if __name__ == "__main__":
    unittest.main()
