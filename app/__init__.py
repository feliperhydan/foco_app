import os
import sys

from flask import Flask

from config import Config
from app.extensions import db
from app.services.config_service import get_current_configuration, default_debug_tools_enabled
from app.services.schema_compat import ensure_compat_schema
from app.services.time_utils import utcnow_naive


def ensure_database_initialized() -> None:
    """Garante que as tabelas existem e há uma Configuration inicial se o banco for novo."""
    from app.models import Configuration, DebugState

    db.create_all()
    ensure_compat_schema()

    if Configuration.query.filter_by(valid_to=None).first() is None:
        cfg = Configuration(
            valid_from=utcnow_naive(),
            valid_to=None,
            focus_minutes=35,
            short_break_minutes=5,
            long_break_minutes=20,
            cycles_per_session=4,
            daily_minimum_goal=6,
            daily_ideal_goal=8,
            weekly_goal=36,
            water_bottle_ml=750,
            water_goal_ml=3500,
            theme="dark",
            primary_color="#1F5C45",
            debug_tools_enabled=default_debug_tools_enabled(),
        )
        db.session.add(cfg)
        db.session.commit()

    if DebugState.query.filter_by(name="clock").first() is None:
        db.session.add(DebugState(name="clock", clock_offset_days=0))
        db.session.commit()


def create_app(config_class: type = Config) -> Flask:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        template_dir = os.path.join(bundle_dir, "app", "templates")
        static_dir = os.path.join(bundle_dir, "app", "static")
        app = Flask(
            __name__,
            template_folder=template_dir,
            static_folder=static_dir,
            instance_relative_config=True,
        )
    else:
        app = Flask(__name__, instance_relative_config=True)

    app.config.from_object(config_class)
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)

    with app.app_context():
        ensure_database_initialized()


    @app.context_processor
    def inject_current_configuration():
        return {"current_cfg": get_current_configuration()}

    from app.routes.main import main_bp
    from app.routes.api import api_bp
    from app.routes.stats import stats_bp
    from app.routes.rewards import rewards_bp
    from app.routes.settings import settings_bp
    from app.routes.notebook import notebook_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(rewards_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(notebook_bp)

    # Blueprints (registrados aqui à medida que a Camada 11 —
    # Interface — for implementada; por enquanto o projeto expõe só
    # o modelo de dados e um comando de CLI para inicializar o banco).
    from app.cli import register_cli
    register_cli(app)

    return app


# Import dos modelos para que fiquem registrados no metadata do
# SQLAlchemy assim que a app é criada (necessário para db.create_all()
# e para autogeração de migrations).
from app import models  # noqa: E402,F401
