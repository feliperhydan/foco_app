"""
Testes automatizados do recurso de Início-automático (auto_start_focus, auto_start_break e post_cycle_messages_enabled).
"""
import unittest

from app import create_app
from app.extensions import db
from app.services import config_service
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class AutoStartTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        config_service.get_current_configuration()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_default_auto_start_is_disabled(self):
        cfg = config_service.get_current_configuration()
        self.assertFalse(cfg.auto_start_focus)
        self.assertFalse(cfg.auto_start_break)
        self.assertTrue(cfg.post_cycle_messages_enabled)

    def test_update_auto_start_switches(self):
        res = self.client.post("/configuracoes", data={
            "focus_minutes": "35",
            "short_break_minutes": "5",
            "long_break_minutes": "20",
            "cycles_per_session": "4",
            "daily_minimum_goal": "6",
            "daily_ideal_goal": "8",
            "weekly_goal": "36",
            "water_bottle_ml": "750",
            "water_goal_ml": "3500",
            "theme": "dark",
            "auto_start_focus": "1",
            "auto_start_break": "1",
            "post_cycle_messages_enabled": "1",
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        updated_cfg = config_service.get_current_configuration()
        self.assertTrue(updated_cfg.auto_start_focus)
        self.assertTrue(updated_cfg.auto_start_break)
        self.assertTrue(updated_cfg.post_cycle_messages_enabled)

    def test_disable_post_cycle_messages(self):
        res = self.client.post("/configuracoes", data={
            "focus_minutes": "35",
            "short_break_minutes": "5",
            "long_break_minutes": "20",
            "cycles_per_session": "4",
            "daily_minimum_goal": "6",
            "daily_ideal_goal": "8",
            "weekly_goal": "36",
            "water_bottle_ml": "750",
            "water_goal_ml": "3500",
            "theme": "dark",
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        updated_cfg = config_service.get_current_configuration()
        self.assertFalse(updated_cfg.post_cycle_messages_enabled)
