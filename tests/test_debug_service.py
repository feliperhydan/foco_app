import unittest

from app import create_app
from app.extensions import db
from app.models import Configuration, Daily, DebugState, FocusCycle, Reward, RewardAchievement, Session
from app.services import stats_service
from app.services.clock import reset, today
from app.services.debug_service import clear_generated_test_data, generate_test_data
from app.services.time_utils import utcnow_naive
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class DebugServiceTest(unittest.TestCase):
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
        db.session.add(
            Configuration(
                valid_from=utcnow_naive(),
                focus_minutes=35,
                short_break_minutes=5,
                long_break_minutes=20,
                cycles_per_session=4,
                daily_minimum_goal=1,
                daily_ideal_goal=2,
                weekly_goal=4,
                water_bottle_ml=750,
                water_goal_ml=3000,
            )
        )
        db.session.add_all(
            [
                Reward(title="Minimo", progress_type="daily_minimum", active=True),
                Reward(title="Ideal", progress_type="daily_ideal", active=True),
                Reward(title="Semanal", progress_type="weekly", active=True),
                Reward(title="Absoluto", progress_type="absolute", active=True),
            ]
        )
        db.session.commit()

    def test_generate_test_data_populates_real_stat_sources(self):
        result = generate_test_data(days=6, cycles_per_day=3, water_per_day=1)

        self.assertEqual(result["requested_days"], 6)
        self.assertEqual(result["days"], 90)
        self.assertEqual(Session.query.count(), result["days"])
        self.assertEqual(Daily.query.count(), result["days"])
        self.assertGreater(FocusCycle.query.filter_by(status="completed").count(), 0)
        self.assertGreater(RewardAchievement.query.count(), 0)
        self.assertGreater(
            Configuration.query.filter(Configuration.valid_to.isnot(None)).count(),
            0,
        )

        first_month = stats_service.monthly_stats(result["start_day"].year, result["start_day"].month)
        current_month = stats_service.monthly_stats(today().year, today().month)
        self.assertGreater(first_month["cycles"], 0)
        self.assertGreater(current_month["cycles"], 0)
        self.assertNotEqual(first_month["cycles"], current_month["cycles"])

        current_week = stats_service.weekly_stats(today())
        self.assertGreater(current_week["cycles"], 0)

    def test_clear_generated_test_data_removes_last_fake_batch(self):
        generate_test_data(days=4, cycles_per_day=2, water_per_day=1)
        self.assertIsNotNone(DebugState.query.filter_by(name="clock").first().test_data_start_date)

        result = clear_generated_test_data()

        self.assertTrue(result["cleared"])
        self.assertEqual(Session.query.count(), 0)
        self.assertEqual(Daily.query.count(), 0)
        self.assertEqual(FocusCycle.query.count(), 0)
        self.assertEqual(RewardAchievement.query.count(), 0)
        self.assertIsNone(DebugState.query.filter_by(name="clock").first().test_data_start_date)
