"""
Serviço de Configuração (manual, seção 6 e 33).

Regra única deste módulo: uma Configuration nunca é editada depois de
criada. Alterar um parâmetro sempre fecha a vigência atual e cria uma
linha nova. Todo o resto do sistema (ciclos, progresso, estatísticas)
lê a configuração vigente através de `get_current_configuration()` e
nunca deve tentar "corrigir" uma configuração passada.
"""
from datetime import datetime
import os

from app.extensions import db
from app.models import Configuration
from app.services.clock import now

# Campos que compõem o pacote de configuração vigente. Usado para
# copiar os valores atuais ao criar a próxima versão, mudando só o
# que o usuário pediu para mudar.
_CONFIG_FIELDS = [
    "focus_minutes", "short_break_minutes", "long_break_minutes",
    "cycles_per_session", "daily_minimum_goal", "daily_ideal_goal",
    "weekly_goal", "water_bottle_ml", "water_goal_ml", "theme",
    "primary_color", "debug_tools_enabled", "auto_start_focus", "auto_start_break",
    "post_cycle_messages_enabled", "volume_system", "volume_focus_end", "volume_rest_end",
    "sound_focus_end", "sound_conclude_btn", "sound_rest_end",
]


def default_debug_tools_enabled() -> bool:
    return os.environ.get("FOCUS_DEBUG_TOOLS", "1") == "1"


def debug_tools_enabled() -> bool:
    return bool(get_current_configuration().debug_tools_enabled)


def get_current_configuration() -> Configuration:
    """
    Retorna a Configuration vigente (valid_to IS NULL). Se por algum
    motivo não existir nenhuma (banco vazio), cria uma com os
    defaults do modelo — isso não deveria acontecer em produção
    porque `init-db` já garante a primeira linha.
    """
    cfg = Configuration.query.filter_by(valid_to=None).order_by(Configuration.id.desc()).first()
    if cfg is None:
        cfg = Configuration(
            valid_from=now(),
            valid_to=None,
            debug_tools_enabled=default_debug_tools_enabled(),
        )
        db.session.add(cfg)
        db.session.commit()
    return cfg


def update_configuration(**changes) -> Configuration:
    """
    Aplica uma mudança de configuração criando uma nova vigência.

    `changes` só precisa conter os campos que realmente mudaram — os
    demais são copiados da configuração vigente atual. A configuração
    antiga é fechada (`valid_to = agora`), nunca apagada.
    """
    current = get_current_configuration()

    real_changes = {}
    for key, value in changes.items():
        if key in _CONFIG_FIELDS and value is not None:
            if getattr(current, key) != value:
                real_changes[key] = value

    if not real_changes:
        return current

    current.valid_to = now()

    new_values = {field: getattr(current, field) for field in _CONFIG_FIELDS}
    for key, value in real_changes.items():
        new_values[key] = value

    new_cfg = Configuration(valid_from=now(), valid_to=None, **new_values)
    db.session.add(new_cfg)
    db.session.commit()
    return new_cfg


def configuration_history(limit: int = 20):
    """Configurações mais recentes primeiro — usado na tela de Configurações (seção 27 do briefing visual)."""
    return (
        Configuration.query.order_by(Configuration.valid_from.desc()).limit(limit).all()
    )


def get_configuration_at(moment: datetime) -> Configuration:
    """
    Retorna a Configuration que estava vigente em `moment`.

    A consulta busca a linha com valid_from <= moment e cujo valid_to é
    posterior a moment ou NULL (ainda vigente). Caso não exista nenhuma
    configuração anterior a moment, retorna a mais antiga disponível.
    """
    cfg = (
        Configuration.query
        .filter(
            Configuration.valid_from <= moment,
            db.or_(Configuration.valid_to.is_(None), Configuration.valid_to > moment),
        )
        .order_by(Configuration.valid_from.desc())
        .first()
    )
    if cfg is None:
        # Fallback: configuração mais antiga do banco (nunca deveria acontecer
        # em produção, mas evita crash durante testes ou dados incompletos).
        cfg = Configuration.query.order_by(Configuration.valid_from.asc()).first()
    if cfg is None:
        cfg = get_current_configuration()
    return cfg
