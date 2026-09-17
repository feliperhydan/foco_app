"""
Testes automatizados do módulo de Backup e Restauração (export_backup / import_backup).
"""
import io
import json
import unittest

from app import create_app
from app.extensions import db
from app.models import Configuration, TodoItem
from app.services import backup_service, config_service
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class BackupServiceTest(unittest.TestCase):
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

    def test_export_backup_structure(self):
        backup = backup_service.export_backup()
        self.assertEqual(backup["app"], "FOCO")
        self.assertEqual(backup["version"], 1)
        self.assertIn("data", backup)
        self.assertIn("configurations", backup["data"])
        self.assertGreaterEqual(len(backup["data"]["configurations"]), 1)

    def test_backup_export_import_roundtrip(self):
        todo = TodoItem(text="Testar backup", done=True, order=1)
        db.session.add(todo)
        db.session.commit()
        todo_id = todo.id

        backup_dict = backup_service.export_backup()
        self.assertGreaterEqual(len(backup_dict["data"]["todo_items"]), 1)

        TodoItem.query.delete()
        db.session.commit()
        self.assertEqual(TodoItem.query.count(), 0)

        ok, msg = backup_service.import_backup(backup_dict)
        self.assertTrue(ok)
        self.assertIn("com sucesso", msg)

        restored_todo = TodoItem.query.filter_by(id=todo_id).first()
        self.assertIsNotNone(restored_todo)
        self.assertEqual(restored_todo.text, "Testar backup")
        self.assertTrue(restored_todo.done)

    def test_backup_routes_download_and_restore(self):
        res = self.client.get("/configuracoes/backup/download")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "application/json")
        self.assertIn("attachment", res.headers["Content-Disposition"])

        backup_json = json.loads(res.data)
        self.assertEqual(backup_json["app"], "FOCO")

        file_bytes = json.dumps(backup_json).encode("utf-8")
        data = {
            "backup_file": (io.BytesIO(file_bytes), "test_backup.json")
        }
        res_post = self.client.post("/configuracoes/backup/restore", data=data, content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(res_post.status_code, 200)
        self.assertIn(b"Backup restaurado com sucesso", res_post.data)
