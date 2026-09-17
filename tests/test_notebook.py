from datetime import date, timedelta
import unittest

from app import create_app
from app.extensions import db
from app.services import clock, notebook_service
from app.models import NotebookEntry, NotebookSchedule, Protocol, PostCycleNote
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class TestNotebook(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_caderno_today_and_past_readonly(self):
        today = clock.today()
        past_date = today - timedelta(days=2)

        # 1. Hoje é editável
        res = self.client.get(f"/caderno?date={today.isoformat()}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"REGISTRO PESSOAL", res.data)
        self.assertNotIn(b"CADERNO ENCERRADO", res.data)

        # 2. Salvar Registro Pessoal de Hoje
        lines = [
            {"id": "l1", "type": "checkbox", "text": "assistir aula", "checked": True, "bold": False, "color": "green"},
            {"id": "l2", "type": "bullet", "text": "derivadas parciais", "checked": False, "bold": True, "color": "blue"},
        ]
        res_save = self.client.post("/api/notebook/save_registro", json={"date": today.isoformat(), "content": lines})
        self.assertEqual(res_save.status_code, 200)
        self.assertEqual(res_save.json["status"], "ok")

        entry_today = notebook_service.get_or_create_notebook(today)
        self.assertEqual(len(entry_today.registro_content), 2)
        self.assertEqual(entry_today.registro_content[0]["text"], "assistir aula")

        # 3. Dia passado fica congelado/somente leitura
        res_past = self.client.get(f"/caderno?date={past_date.isoformat()}")
        self.assertEqual(res_past.status_code, 200)
        self.assertIn(b"CADERNO ENCERRADO", res_past.data)

        # Tentar alterar dia passado não modifica o banco
        lines_past = [{"id": "p1", "type": "text", "text": "tentativa de alteracao"}]
        self.client.post("/api/notebook/save_registro", json={"date": past_date.isoformat(), "content": lines_past})
        entry_past = notebook_service.get_or_create_notebook(past_date)
        self.assertEqual(len(entry_past.registro_content), 0)

    def test_retrato_snapshot_and_user_fields(self):
        today = clock.today()

        # Retrato inicial (sem sessões): estado neutro sem zeros inventados
        retrato = notebook_service.get_retrato_snapshot(today)
        self.assertFalse(retrato["has_activity"])

        # Criar sessão e ciclo de foco + descanso + água
        from app.models import Session, FocusCycle, RestCycle, Configuration, WaterLog
        cfg = Configuration(focus_minutes=25, short_break_minutes=5, long_break_minutes=15, water_bottle_ml=750, water_goal_ml=3000)
        db.session.add(cfg)
        db.session.commit()

        s = Session(date=today, status="active")
        db.session.add(s)
        db.session.commit()

        fc = FocusCycle(session_id=s.id, configuration_id=cfg.id, focus_duration_minutes=25, status="completed")
        rc = RestCycle(session_id=s.id, configuration_id=cfg.id, kind="short", duration_minutes=5, status="completed")
        wl = WaterLog(date=today, volume_ml=750, configuration_id=cfg.id)
        db.session.add_all([fc, rc, wl])
        db.session.commit()

        retrato_active = notebook_service.get_retrato_snapshot(today)
        self.assertTrue(retrato_active["has_activity"])
        self.assertEqual(retrato_active["cycles"], 1)
        self.assertEqual(retrato_active["focus_minutes_fmt"], "25 min")
        self.assertEqual(retrato_active["pausas_fmt"], "1 curtas · 0 longas")
        self.assertEqual(retrato_active["water_fmt"], "0,75 L")

        # Salvar campos do usuário (início, fim, cansaço)
        res = self.client.post("/api/notebook/save_retrato", json={
            "date": today.isoformat(),
            "inicio_estudos": "08:00",
            "fim_estudos": "18:00",
            "nivel_cansaco": 3
        })
        self.assertEqual(res.status_code, 200)

        entry = notebook_service.get_or_create_notebook(today)
        self.assertEqual(entry.inicio_estudos, "08:00")
        self.assertEqual(entry.fim_estudos, "18:00")
        self.assertEqual(entry.nivel_cansaco, 3)

    def test_programacao_por_data(self):
        today = clock.today()
        future_date = today + timedelta(days=3)

        # 1. Agendar demanda para data futura
        res_add = self.client.post("/api/notebook/programacao/add", json={
            "target_date": future_date.isoformat(),
            "text": "Revisar capitulo 4 para a prova"
        })
        self.assertEqual(res_add.status_code, 200)
        self.assertEqual(res_add.json["status"], "ok")

        items = notebook_service.get_programacao_items(future_date)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "Revisar capitulo 4 para a prova")

        # 2. Testar dismiss e copy na data alvo
        res_dismiss = self.client.post("/api/notebook/programacao/dismiss", json={"date": future_date.isoformat()})
        self.assertEqual(res_dismiss.status_code, 200)
        entry_future = notebook_service.get_or_create_notebook(future_date)
        self.assertTrue(entry_future.programacao_dismissed)

        res_copy = self.client.post("/api/notebook/programacao/copy", json={"date": future_date.isoformat()})
        self.assertEqual(res_copy.status_code, 200)
        self.assertGreaterEqual(len(res_copy.json["registro_content"]), 1)

    def test_protocolos_cotidianos(self):
        protocols = notebook_service.get_protocols()
        self.assertGreaterEqual(len(protocols), 5)
        self.assertTrue(any(p["title"] == "Revisão Matinal" for p in protocols))

        # Adicionar protocolo personalizado
        res = self.client.post("/api/notebook/protocols/add", json={
            "title": "Protocolo Noturno",
            "objective": "Desconectar telas antes de dormir",
            "activities": ["Apagar luzes fortes", "Ler 10 paginas do livro"],
            "avg_duration_minutes": 15,
            "recommended_time": "22:00 - 22:30"
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json["status"], "ok")
        proto_id = res.json["protocol"]["id"]

        # 2. Atualizar protocolo existente
        res_update = self.client.post("/api/notebook/protocols/update", json={
            "id": proto_id,
            "title": "Protocolo Noturno Atualizado",
            "objective": "Desconectar telas e meditar",
            "activities": ["Apagar luzes", "Meditação 5min", "Ler 10 paginas"],
            "avg_duration_minutes": 20,
            "recommended_time": "21:45 - 22:15"
        })
        self.assertEqual(res_update.status_code, 200)
        self.assertEqual(res_update.json["protocol"]["title"], "Protocolo Noturno Atualizado")

        # Copiar atividades do protocolo para o registro pessoal
        today = clock.today()
        res_copy = self.client.post("/api/notebook/protocols/copy", json={
            "date": today.isoformat(),
            "protocol_id": proto_id
        })
        self.assertEqual(res_copy.status_code, 200)
        lines = res_copy.json["registro_content"]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["type"], "checkbox")
        self.assertEqual(lines[0]["text"], "Apagar luzes")
        self.assertFalse(lines[0]["checked"])

        # 3. Testar limite de 6 protocolos
        current_count = len(notebook_service.get_protocols())
        for i in range(current_count, 6):
            notebook_service.create_protocol(f"P{i}", f"Obj{i}", ["Act"], 10, "10:00")
        
        self.assertEqual(len(notebook_service.get_protocols()), 6)

        # Tentativa de criar 7º protocolo deve retornar erro 400
        res_overflow = self.client.post("/api/notebook/protocols/add", json={
            "title": "Protocolo Extra",
            "objective": "Exceder limite",
            "activities": ["Teste"],
            "avg_duration_minutes": 10,
            "recommended_time": "10:00"
        })
        self.assertEqual(res_overflow.status_code, 400)
        self.assertIn("Limite", res_overflow.json["message"])

        # 4. Excluir um protocolo
        res_delete = self.client.post("/api/notebook/protocols/delete", json={"id": proto_id})
        self.assertEqual(res_delete.status_code, 200)
        self.assertEqual(len(notebook_service.get_protocols()), 5)

    def test_pos_ciclos_notes(self):
        today = clock.today()

        # Adicionar notas em ordem de criação invertida para testar ordenação por prioridade:
        # 1. ideia, 2. tarefa, 3. duvida, 4. lembrete, 5. lembrete #2
        categories_to_add = ["ideia", "tarefa", "duvida", "lembrete", "lembrete"]
        for idx, cat in enumerate(categories_to_add, start=1):
            res = self.client.post("/api/notebook/pos_ciclos/add", json={
                "date": today.isoformat(),
                "content": f"Nota {cat} {idx}",
                "category": cat,
                "cycle_number": idx
            })
            self.assertEqual(res.status_code, 200)

        notes = notebook_service.get_post_cycle_notes(today)
        self.assertEqual(len(notes), 5)
        # Ordem esperada por prioridade e depois por id asc:
        # lembrete (id 4), lembrete (id 5), duvida (id 3), tarefa (id 2), ideia (id 1)
        ordered_categories = [n["category"] for n in notes]
        self.assertEqual(ordered_categories, ["lembrete", "lembrete", "duvida", "tarefa", "ideia"])
        self.assertEqual(notes[0]["content"], "Nota lembrete 4")
        self.assertEqual(notes[1]["content"], "Nota lembrete 5")

        # Toggle note
        first_note_id = notes[0]["id"]
        res_toggle = self.client.post("/api/notebook/pos_ciclos/toggle", json={"note_id": first_note_id})
        self.assertEqual(res_toggle.status_code, 200)
        self.assertTrue(res_toggle.json["note"]["resolved"])

        # Delete note
        res_delete = self.client.post("/api/notebook/pos_ciclos/delete", json={"note_id": first_note_id})
        self.assertEqual(res_delete.status_code, 200)
        self.assertEqual(res_delete.json["status"], "ok")

        notes_after_delete = notebook_service.get_post_cycle_notes(today)
        self.assertEqual(len(notes_after_delete), 4)
        self.assertFalse(any(n["id"] == first_note_id for n in notes_after_delete))
