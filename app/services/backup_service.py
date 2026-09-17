"""
Serviço de Backup e Restauração de dados do FOCUS.

Exporta e importa todas as tabelas e registros estatísticos e operacionais
do banco de dados em um arquivo JSON completo e portátil.
"""
from datetime import date, datetime
import json

from app.extensions import db
from app.models import (
    DebugState, Configuration, Session, FocusCycle, RestCycle,
    DailyMinimumProgress, DailyIdealProgress, ExtraordinaryProgress, WeeklyProgress,
    AbsoluteProgress, AbsoluteProgressDailyLog, WishlistItem, TodoItem, TodoListState,
    Daily, Week, WeekDaily, Month, MonthDaily, Reward, RewardAchievement, WaterLog
)

TABLE_MAP = [
    ("debug_state", DebugState),
    ("configurations", Configuration),
    ("sessions", Session),
    ("focus_cycles", FocusCycle),
    ("rest_cycles", RestCycle),
    ("daily_minimum_progress", DailyMinimumProgress),
    ("daily_ideal_progress", DailyIdealProgress),
    ("extraordinary_progress", ExtraordinaryProgress),
    ("weekly_progress", WeeklyProgress),
    ("wishlist_items", WishlistItem),
    ("absolute_progress", AbsoluteProgress),
    ("absolute_progress_daily_logs", AbsoluteProgressDailyLog),
    ("todo_items", TodoItem),
    ("todo_list_state", TodoListState),
    ("daily", Daily),
    ("weeks", Week),
    ("week_daily", WeekDaily),
    ("months", Month),
    ("month_daily", MonthDaily),
    ("rewards", Reward),
    ("reward_achievements", RewardAchievement),
    ("water_logs", WaterLog),
]


def _serialize_value(val):
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return val


def _parse_value(val, col_type):
    if val is None:
        return None
    type_str = str(col_type).upper()
    if "DATE" in type_str and "DATETIME" not in type_str:
        if isinstance(val, str):
            return date.fromisoformat(val[:10])
    elif "DATETIME" in type_str or "TIMESTAMP" in type_str:
        if isinstance(val, str):
            return datetime.fromisoformat(val)
    return val


def export_backup() -> dict:
    data = {}
    for table_name, model_cls in TABLE_MAP:
        rows = model_cls.query.all()
        table_rows = []
        columns = [c.name for c in model_cls.__table__.columns]
        for row in rows:
            row_dict = {}
            for col in columns:
                row_dict[col] = _serialize_value(getattr(row, col))
            table_rows.append(row_dict)
        data[table_name] = table_rows

    return {
        "app": "FOCO",
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "data": data,
    }


def import_backup(backup_dict: dict) -> tuple[bool, str]:
    if not isinstance(backup_dict, dict):
        return False, "Arquivo de backup inválido (conteúdo não é um objeto JSON válido)."

    data = backup_dict.get("data")
    if not isinstance(data, dict):
        return False, "Estrutura de backup inválida (campo 'data' ausente)."

    try:
        # 1) Excluir todos os dados respeitando a ordem de FKs usando a metadata
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.flush()

        # 2) Re-inserir registros na ordem das dependências
        for table_name, model_cls in TABLE_MAP:
            rows = data.get(table_name, [])
            columns = model_cls.__table__.columns
            col_types = {c.name: c.type for c in columns}

            for row_data in rows:
                if not isinstance(row_data, dict):
                    continue
                kwargs = {}
                for col_name, col_type in col_types.items():
                    if col_name in row_data:
                        kwargs[col_name] = _parse_value(row_data[col_name], col_type)
                obj = model_cls(**kwargs)
                db.session.add(obj)

            db.session.flush()

        db.session.commit()
        return True, "Backup restaurado com sucesso! Todos os dados foram atualizados."
    except Exception as err:
        db.session.rollback()
        return False, f"Falha ao restaurar backup: {str(err)}"
