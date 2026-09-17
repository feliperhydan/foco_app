from sqlalchemy import inspect, text

from app.extensions import db
from app.services.config_service import default_debug_tools_enabled


def ensure_compat_schema() -> None:
    """
    Garante colunas de compatibilidade em bancos SQLite já criados.

    O projeto evolui sem migrações formais, então algumas mudanças de
    schema precisam ser aplicadas manualmente para bancos antigos.
    """
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())

    if "configurations" in tables:
        columns = {column["name"] for column in inspector.get_columns("configurations")}
        if "debug_tools_enabled" not in columns:
            db.session.execute(
                text(
                    "ALTER TABLE configurations "
                    "ADD COLUMN debug_tools_enabled BOOLEAN NOT NULL DEFAULT 0"
                )
            )
            db.session.execute(
                text("UPDATE configurations SET debug_tools_enabled = :enabled"),
                {"enabled": 1 if default_debug_tools_enabled() else 0},
            )
            db.session.commit()
        if "auto_start_focus" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN auto_start_focus BOOLEAN NOT NULL DEFAULT 0"))
            db.session.commit()
        if "auto_start_break" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN auto_start_break BOOLEAN NOT NULL DEFAULT 0"))
            db.session.commit()
        if "post_cycle_messages_enabled" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN post_cycle_messages_enabled BOOLEAN NOT NULL DEFAULT 1"))
            db.session.commit()
        if "volume_system" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN volume_system INTEGER NOT NULL DEFAULT 100"))
            db.session.commit()
        if "volume_focus_end" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN volume_focus_end INTEGER NOT NULL DEFAULT 100"))
            db.session.commit()
        if "volume_rest_end" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN volume_rest_end INTEGER NOT NULL DEFAULT 100"))
            db.session.commit()
        if "sound_focus_end" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN sound_focus_end VARCHAR(255) NOT NULL DEFAULT '/static/sounds/fim_de_foco.mp3'"))
            db.session.commit()
        if "sound_conclude_btn" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN sound_conclude_btn VARCHAR(255) NOT NULL DEFAULT '/static/sounds/do_pos_conclusao.mp3'"))
            db.session.commit()
        if "sound_rest_end" not in columns:
            db.session.execute(text("ALTER TABLE configurations ADD COLUMN sound_rest_end VARCHAR(255) NOT NULL DEFAULT '/static/sounds/fim_de_descanso.mp3'"))
            db.session.commit()

    if "reward_achievements" in tables:
        columns = {column["name"] for column in inspector.get_columns("reward_achievements")}
        if "title_snapshot" not in columns:
            db.session.execute(text("ALTER TABLE reward_achievements ADD COLUMN title_snapshot VARCHAR(120)"))
            db.session.execute(text("""
                UPDATE reward_achievements
                SET title_snapshot = (
                    SELECT rewards.title
                    FROM rewards
                    WHERE rewards.id = reward_achievements.reward_id
                )
                WHERE title_snapshot IS NULL
            """))
            db.session.commit()

    if "daily" in tables:
        daily_columns = {column["name"] for column in inspector.get_columns("daily")}
        if "consolidated_at" not in daily_columns:
            db.session.execute(text("ALTER TABLE daily ADD COLUMN consolidated_at DATETIME"))
            db.session.commit()
        if "focus_timeline" not in daily_columns:
            db.session.execute(text("ALTER TABLE daily ADD COLUMN focus_timeline JSON"))
            db.session.commit()
        if "session" not in daily_columns:
            db.session.execute(text("ALTER TABLE daily ADD COLUMN session JSON"))
            db.session.commit()

    if "debug_state" in tables:
        debug_state_columns = {column["name"] for column in inspector.get_columns("debug_state")}
        if "test_data_start_date" not in debug_state_columns:
            db.session.execute(text("ALTER TABLE debug_state ADD COLUMN test_data_start_date DATE"))
            db.session.commit()
        if "test_data_end_date" not in debug_state_columns:
            db.session.execute(text("ALTER TABLE debug_state ADD COLUMN test_data_end_date DATE"))
            db.session.commit()
        if "test_data_generated_at" not in debug_state_columns:
            db.session.execute(text("ALTER TABLE debug_state ADD COLUMN test_data_generated_at DATETIME"))
            db.session.commit()

    if "focus_cycles" in tables:
        focus_columns = {column["name"] for column in inspector.get_columns("focus_cycles")}
        if "discount_pct" not in focus_columns:
            db.session.execute(text("ALTER TABLE focus_cycles ADD COLUMN discount_pct INTEGER"))
            db.session.commit()

    if "extraordinary_progress" in tables:
        extra_columns = {column["name"] for column in inspector.get_columns("extraordinary_progress")}
        if "next_discount_pct" not in extra_columns:
            db.session.execute(text("ALTER TABLE extraordinary_progress ADD COLUMN next_discount_pct INTEGER"))
            db.session.commit()

    # Garante a criação de todas as tabelas (incluindo as tabelas do Caderno Diário)
    db.create_all()

    try:
        from app.services.notebook_service import seed_default_protocols_if_needed
        seed_default_protocols_if_needed()
    except Exception:
        db.session.rollback()



