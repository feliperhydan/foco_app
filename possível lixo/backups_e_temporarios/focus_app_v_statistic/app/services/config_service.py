"""
Serviço de Configuração (manual, seção 6 e 33).

Regra única deste módulo: uma Configuration nunca é editada depois de
criada. Alterar um parâmetro sempre fecha a vigência atual e cria uma
linha nova. Todo o resto do sistema (ciclos, progresso, estatísticas)
lê a configuração vigente através de `get_current_configuration()` e
nunca deve tentar "corrigir" uma configuração passada.
"""
from app.extensions import db
from app.models import Configuration
from app.services import clock

# Campos que compõem o pacote de configuração vigente. Usado para
# copiar os valores atuais ao criar a próxima versão, mudando só o
# que o usuário pediu para mudar.
_CONFIG_FIELDS = [
    "focus_minutes", "short_break_minutes", "long_break_minutes",
    "cycles_per_session", "daily_minimum_goal", "daily_ideal_goal",
    "weekly_goal", "water_bottle_ml", "water_goal_ml", "theme",
    "primary_color",
]


def get_current_configuration() -> Configuration:
    """
    Retorna a Configuration vigente (valid_to IS NULL). Se por algum
    motivo não existir nenhuma (banco vazio), cria uma com os
    defaults do modelo — isso não deveria acontecer em produção
    porque `init-db` já garante a primeira linha.
    """
    cfg = Configuration.query.filter_by(valid_to=None).order_by(Configuration.id.desc()).first()
    if cfg is None:
        cfg = Configuration(valid_from=clock.now(), valid_to=None)
        db.session.add(cfg)
        db.session.commit()
    return cfg


def get_configuration_at(moment) -> Configuration | None:
    """
    Retorna a Configuration vigente no instante `moment` (um datetime
    naive) — histórico, não só a atual. Necessário para reconstruir
    contexto de um dia passado (ex.: meta de água vigente naquele
    dia) sem depender de `get_current_configuration()`, que só
    responde pelo presente.

    `moment` deve estar entre `valid_from` (inclusive) e `valid_to`
    (exclusive, ou vigente se `valid_to is None`). Para um `moment`
    anterior à primeira Configuration já criada (só ocorre para datas
    de antes da própria aplicação existir), cai de volta para a
    Configuration mais antiga disponível — nunca retorna `None` se
    existir pelo menos uma linha na tabela.
    """
    cfg = (
        Configuration.query
        .filter(Configuration.valid_from <= moment)
        .filter((Configuration.valid_to.is_(None)) | (Configuration.valid_to > moment))
        .order_by(Configuration.valid_from.desc())
        .first()
    )
    if cfg is not None:
        return cfg
    return Configuration.query.order_by(Configuration.valid_from.asc()).first()


def update_configuration(**changes) -> Configuration:
    """
    Aplica uma mudança de configuração criando uma nova vigência.

    `changes` só precisa conter os campos que realmente mudaram — os
    demais são copiados da configuração vigente atual. A configuração
    antiga é fechada (`valid_to = agora`), nunca apagada.
    """
    current = get_current_configuration()

    now = clock.now()
    current.valid_to = now

    new_values = {field: getattr(current, field) for field in _CONFIG_FIELDS}
    for key, value in changes.items():
        if key in _CONFIG_FIELDS and value is not None:
            new_values[key] = value

    new_cfg = Configuration(valid_from=now, valid_to=None, **new_values)
    db.session.add(new_cfg)
    db.session.commit()
    return new_cfg


def configuration_history(limit: int = 20):
    """Configurações mais recentes primeiro — usado na tela de Configurações (seção 27 do briefing visual)."""
    return (
        Configuration.query.order_by(Configuration.valid_from.desc()).limit(limit).all()
    )
