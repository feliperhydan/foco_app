import unittest
from datetime import date, timedelta, datetime
from app import create_app
from app.extensions import db
from app.models import Daily, Week, Month, Configuration, Reward
from app.services import clock, history_service
from app.services.history_service import get_std_dev, get_streak_on_date, get_best_streak, pct_change
from config import Config

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

class TestAnalysisPage(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        clock.reset()
        self._seed_rewards()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _seed_rewards(self):
        db.session.add(Configuration(
            valid_from=date(2026, 8, 1),
            focus_minutes=25,
            short_break_minutes=5,
            long_break_minutes=15,
            cycles_per_session=4,
            daily_minimum_goal=2,
            daily_ideal_goal=4,
            weekly_goal=20,
            water_bottle_ml=500,
            water_goal_ml=2000
        ))
        db.session.add(Reward(title="Meta Mínima", progress_type="daily_minimum", active=True))
        db.session.add(Reward(title="Meta Ideal", progress_type="daily_ideal", active=True))
        db.session.commit()

    def _create_daily(self, date_val, minutes, cycles, session_started=True, minimum_completed=False, ideal_completed=False, extraordinary_cycles=0):
        # Create a daily record with custom focus minutes and cycles
        d = Daily(
            date=date_val,
            session_started=session_started,
            consolidated_at=datetime.utcnow(),
            cycle_contexts=[
                {
                    "context_id": 1,
                    "configuration": {
                        "focus_minutes": 25,
                        "daily_minimum_goal": 2,
                        "daily_ideal_goal": 4
                    },
                    "focus": {
                        "cycles_completed": cycles,
                        "minutes_completed": minutes,
                        "titles": []
                    },
                    "extraordinary": {
                        "cycles": extraordinary_cycles,
                        "minutes": extraordinary_cycles * 25
                    }
                }
            ],
            rewards={
                "daily_minimum": {"goal_completed": minimum_completed},
                "daily_ideal": {"goal_completed": ideal_completed}
            },
            session={"started_at": f"{date_val.isoformat()}T09:00:00"} if session_started else None
        )
        db.session.add(d)
        db.session.commit()
        return d

    def test_best_day_by_minutes(self):
        # Scenario 1: Best day is B (more minutes), even though A has more cycles
        # Day A: 3 cycles, 75 minutes
        # Day B: 2 cycles, 100 minutes (longer focus session)
        self._create_daily(date(2026, 8, 10), minutes=75, cycles=3)
        self._create_daily(date(2026, 8, 11), minutes=100, cycles=2)

        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["best_day"]["date"], date(2026, 8, 11))
        self.assertEqual(analysis["best_day"]["minutes"], 100)
        self.assertEqual(analysis["best_day"]["cycles"], 2)

    def test_extraordinary_day_by_cycles(self):
        # Scenario 2: Extraordinary day is A (more cycles), even though B has more minutes
        # Day A: 5 cycles, 100 minutes
        # Day B: 3 cycles, 120 minutes
        self._create_daily(date(2026, 8, 10), minutes=100, cycles=5)
        self._create_daily(date(2026, 8, 11), minutes=120, cycles=3)

        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["extraordinary_day"]["date"], date(2026, 8, 10))
        self.assertEqual(analysis["extraordinary_day"]["cycles"], 5)
        self.assertEqual(analysis["extraordinary_day"]["minutes"], 100)

    def test_best_week_by_minutes(self):
        # Scenario 3: Best week has the highest accumulated minutes
        w1 = Week(
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 9),
            totals={"focus": {"minutes_completed": 500, "cycles_completed": 15}}
        )
        w2 = Week(
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 16),
            totals={"focus": {"minutes_completed": 700, "cycles_completed": 20}}
        )
        db.session.add_all([w1, w2])
        db.session.commit()

        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["best_week"]["start_date"], date(2026, 8, 10))
        self.assertEqual(analysis["best_week"]["minutes"], 700)

    def test_consistency_of_weeks(self):
        # Scenario 4: Consistency of weeks (dispersion/std dev)
        # Week 1: 50 min every day (std_dev = 0)
        # Week 2: 350 min on Monday, 0 on other days (std_dev = ~120)
        w1 = Week(
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 9),
            totals={"focus": {"minutes_completed": 350, "cycles_completed": 10}}
        )
        w2 = Week(
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 16),
            totals={"focus": {"minutes_completed": 350, "cycles_completed": 10}}
        )
        db.session.add_all([w1, w2])
        db.session.commit()

        # Dailies for Week 1 (50 min each)
        for i in range(7):
            self._create_daily(date(2026, 8, 3) + timedelta(days=i), minutes=50, cycles=2)

        # Dailies for Week 2 (350 min on Monday, 0 elsewhere)
        self._create_daily(date(2026, 8, 10), minutes=350, cycles=10)
        for i in range(1, 7):
            self._create_daily(date(2026, 8, 10) + timedelta(days=i), minutes=0, cycles=0, session_started=False)

        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["consistent_week"]["start_date"], date(2026, 8, 3))
        self.assertAlmostEqual(analysis["consistent_week"]["std_dev"], 0.0, places=2)

    def test_consistency_of_months(self):
        # Scenario 5: Consistency of months (std dev over calendar days)
        m1 = Month(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            totals={"focus": {"minutes_completed": 310, "cycles_completed": 10}}
        )
        db.session.add(m1)
        db.session.commit()

        # Populate every day with 10 minutes
        for i in range(31):
            self._create_daily(date(2026, 8, 1) + timedelta(days=i), minutes=10, cycles=1)

        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["consistent_month"]["start_date"], date(2026, 8, 1))
        self.assertAlmostEqual(analysis["consistent_month"]["std_dev"], 0.0, places=2)

    def test_ideal_week_with_different_daily_goals(self):
        # Scenario 6: Ideal week checks daily context rewards (achieved daily ideal goal)
        w = Week(
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 9),
            rewards={"daily_ideal": {"completed_count": 5}}
        )
        db.session.add(w)
        db.session.commit()

        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["ideal_week"]["count"], 5)
        self.assertEqual(analysis["ideal_week"]["total"], 7)

    def test_days_without_activity(self):
        # Scenario 7 & 8: Days with no activity are counted as 0 minutes in standard deviation
        # and weekly daily average divides by 7 calendar days, not active days.
        w = Week(
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 9),
            totals={"focus": {"minutes_completed": 70, "cycles_completed": 2}}
        )
        db.session.add(w)
        db.session.commit()

        self._create_daily(date(2026, 8, 3), minutes=70, cycles=2)  # Active
        # Days 8/4 to 8/9 have no Daily rows (session_started=False, 0 min)

        period_an = history_service.get_period_analysis("week", date(2026, 8, 3))
        # Daily average should be 70 / 7 = 10 min/day
        self.assertAlmostEqual(period_an["avg_minutes"], 10.0, places=2)
        # Std dev of [70, 0, 0, 0, 0, 0, 0] is ~24.49
        self.assertAlmostEqual(period_an["std_dev"], 24.49, places=2)

    def test_streak_minimum_of_two_days(self):
        # Scenario 9: Streaks require at least 2 consecutive days.
        # Single active day should not be counted as a streak (returns 0 length)
        self._create_daily(date(2026, 8, 10), minutes=50, cycles=2)
        
        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["streaks"]["best_active"]["length"], 0)

        # Adding a second consecutive day makes it a streak of 2
        self._create_daily(date(2026, 8, 11), minutes=50, cycles=2)
        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["streaks"]["best_active"]["length"], 2)

    def test_current_and_best_streaks(self):
        # Scenarios 10, 11, 12, 13: Current streak, best active streak, best minimum, best ideal
        clock.set_offset_days(0) # Assume today is 2026-08-21
        today_dt = clock.today() # 2026-08-21
        
        # Best active streak: 2026-08-10 to 2026-08-13 (4 days)
        for i in range(4):
            self._create_daily(date(2026, 8, 10) + timedelta(days=i), minutes=50, cycles=2, minimum_completed=True)
            
        # Gaps on 8/14, 8/15
        
        # Current active streak ending today: 2026-08-19 to 2026-08-21 (3 days)
        for i in range(3):
            self._create_daily(today_dt - timedelta(days=2-i), minutes=60, cycles=3, minimum_completed=True, ideal_completed=True)

        analysis = history_service.get_global_analysis()
        self.assertEqual(analysis["streaks"]["best_active"]["length"], 4)
        self.assertEqual(analysis["streaks"]["best_active"]["start"], "10/08/2026")
        self.assertEqual(analysis["streaks"]["best_active"]["end"], "13/08/2026")
        
        self.assertEqual(analysis["streaks"]["current_active"], 3)
        self.assertEqual(analysis["streaks"]["current_minimum"], 3)
        self.assertEqual(analysis["streaks"]["current_ideal"], 3)
        
        self.assertEqual(analysis["streaks"]["best_minimum"]["length"], 4)
        self.assertEqual(analysis["streaks"]["best_ideal"]["length"], 3)

    def test_comparisons_and_percentage_signs(self):
        # Scenarios 14, 15, 16, 17: Comparison A->B, positive %, negative %, division by zero
        self.assertEqual(pct_change(100, 120), 20.0)    # +20.0%
        self.assertEqual(pct_change(100, 80), -20.0)    # -20.0%
        self.assertEqual(pct_change(100, 100), 0.0)      # 0.0%
        self.assertIsNone(pct_change(0, 50))            # Div by zero -> None

    def test_progressive_current_periods(self):
        # Scenarios 18, 19, 20: Progressive updates for today, current week, and current month
        # Reading a day/week/month that is today/current automatically triggers consolidation/rebuild.
        today_dt = clock.today()
        # This function consolidated the daily for today_dt before reading
        day_dict = history_service.get_day(today_dt)
        self.assertEqual(day_dict["date"], today_dt.isoformat())

        week_dict = history_service.get_week(today_dt)
        self.assertIsNotNone(week_dict)

        month_dict = history_service.get_month(today_dt)
        self.assertIsNotNone(month_dict)

if __name__ == "__main__":
    unittest.main()
