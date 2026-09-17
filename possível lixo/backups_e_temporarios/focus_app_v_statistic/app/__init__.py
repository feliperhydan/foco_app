from flask import Flask

from config import Config
from app.extensions import db


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    db.init_app(app)

    from app.routes.main import main_bp
    from app.routes.api import api_bp
    from app.routes.stats import stats_bp
    from app.routes.rewards import rewards_bp
    from app.routes.settings import settings_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(rewards_bp)
    app.register_blueprint(settings_bp)

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
