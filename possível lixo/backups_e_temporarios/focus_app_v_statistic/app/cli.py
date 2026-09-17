"""
Comandos de CLI para gerenciar a persistência nesta primeira etapa
(Camada 1 do manual). Uso:

    flask --app run.py init-db      # cria as tabelas + configuração inicial
    flask --app run.py reset-db     # apaga tudo e recria
    flask --app run.py seed-demo    # roda o fluxo de validação da seção 45
    flask --app run.py shell-info   # mostra contagem de linhas por tabela
"""
from datetime import datetime, timedelta, date

import click

from app.extensions import db


def register_cli(app):
    app.cli.add_command(init_db_command)
    app.cli.add_command(reset_db_command)
    app.cli.add_command(seed_demo_command)
    app.cli.add_command(shell_info_command)


@click.command("init-db")
def init_db_command():
    """Cria as tabelas e uma Configuration inicial (se não houver nenhuma)."""
    from app.models import Configuration

    db.create_all()

    if Configuration.query.filter_by(valid_to=None).first() is None:
        cfg = Configuration(
            valid_from=datetime.utcnow(),
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
        )
        db.session.add(cfg)
        db.session.commit()
        click.echo(f"Banco criado. Configuration inicial id={cfg.id} (foco={cfg.focus_minutes}min).")
    else:
        click.echo("Banco criado. Já existia uma Configuration vigente.")


@click.command("reset-db")
def reset_db_command():
    """Apaga todas as tabelas e recria do zero. Uso só em desenvolvimento."""
    if not click.confirm("Isso apaga TODOS os dados locais. Continuar?"):
        return
    db.drop_all()
    db.create_all()
    click.echo("Banco resetado.")


@click.command("seed-demo")
def seed_demo_command():
    """
    Roda (parte de) o fluxo de validação descrito no manual, seção 45,
    para provar que o esquema suporta a regra ciclo ≠ minuto e a
    vigência de configuração. Não implementa o motor de conclusão
    (isso é Camada 5) — grava os registros diretamente para servir de
    fixture de teste do modelo de dados.
    """
    from app.models import (
        Configuration, Session, FocusCycle, DailyMinimumProgress,
        DailyIdealProgress, ExtraordinaryProgress, WeeklyProgress,
        AbsoluteProgress, Reward, RewardAchievement, WaterLog,
    )

    db.create_all()

    today = date.today()

    # --- Configuração A: foco de 35 min ---
    cfg_a = Configuration(
        valid_from=datetime.utcnow() - timedelta(days=10),
        valid_to=datetime.utcnow() - timedelta(days=1),
        focus_minutes=35, short_break_minutes=5, long_break_minutes=20,
        cycles_per_session=4, daily_minimum_goal=6, daily_ideal_goal=8,
        weekly_goal=36, water_bottle_ml=750, water_goal_ml=3500,
    )
    # --- Configuração B: foco muda para 45 min, vigente ---
    cfg_b = Configuration(
        valid_from=datetime.utcnow() - timedelta(days=1),
        valid_to=None,
        focus_minutes=45, short_break_minutes=5, long_break_minutes=20,
        cycles_per_session=4, daily_minimum_goal=6, daily_ideal_goal=8,
        weekly_goal=36, water_bottle_ml=750, water_goal_ml=3500,
    )
    db.session.add_all([cfg_a, cfg_b])
    db.session.flush()

    session_ = Session(date=today, status="active")
    db.session.add(session_)
    db.session.flush()

    # 8 ciclos concluídos com a config antiga (35 min) — mínimo + ideal batem
    for i in range(8):
        c = FocusCycle(
            session_id=session_.id,
            configuration_id=cfg_a.id,
            started_at=datetime.utcnow() - timedelta(minutes=(8 - i) * 40),
            completed_at=datetime.utcnow() - timedelta(minutes=(8 - i) * 40 - 35),
            focus_duration_minutes=cfg_a.focus_minutes,  # snapshot — sempre 35
            status="completed",
        )
        db.session.add(c)

    # 3 ciclos extraordinários já com a config nova (45 min)
    for i in range(3):
        c = FocusCycle(
            session_id=session_.id,
            configuration_id=cfg_b.id,
            started_at=datetime.utcnow() - timedelta(minutes=(3 - i) * 50),
            completed_at=datetime.utcnow() - timedelta(minutes=(3 - i) * 50 - 45),
            focus_duration_minutes=cfg_b.focus_minutes,  # snapshot — sempre 45
            status="completed",
        )
        db.session.add(c)

    daily_min = DailyMinimumProgress(
        date=today, goal=6, current_count=8, configuration_id=cfg_a.id,
        status="completed", completed_at=datetime.utcnow(),
    )
    daily_ideal = DailyIdealProgress(
        date=today, goal=8, current_count=8, configuration_id=cfg_a.id,
        status="completed", completed_at=datetime.utcnow(),
    )
    db.session.add_all([daily_min, daily_ideal])
    db.session.flush()

    extra = ExtraordinaryProgress(
        date=today, daily_ideal_id=daily_ideal.id, configuration_id=cfg_b.id,
        extra_cycles=3, extra_minutes=3 * cfg_b.focus_minutes,
    )
    db.session.add(extra)

    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    weekly = WeeklyProgress(
        week_start=week_start, week_end=week_end, goal=36, current_count=11,
        configuration_id=cfg_b.id,
    )
    db.session.add(weekly)

    absolute = AbsoluteProgress(
        title="MP3", goal_cycles=1000, current_count=734,
    )
    db.session.add(absolute)

    reward = Reward(title="1 hora de videogame", progress_type="daily_ideal", active=True)
    db.session.add(reward)
    db.session.flush()
    db.session.add(RewardAchievement(reward_id=reward.id, achieved_date=today))

    db.session.add(WaterLog(date=today, volume_ml=750, configuration_id=cfg_b.id))
    db.session.add(WaterLog(date=today, volume_ml=750, configuration_id=cfg_b.id))
    db.session.add(WaterLog(date=today, volume_ml=750, configuration_id=cfg_b.id))

    db.session.commit()

    total_minutes = sum(
        fc.focus_duration_minutes
        for fc in FocusCycle.query.filter_by(status="completed").all()
    )
    click.echo("Seed de demonstração criado.")
    click.echo(f"  Ciclos concluídos: {FocusCycle.query.filter_by(status='completed').count()}")
    click.echo(f"  Minutos totais (somados por ciclo, nunca por config atual): {total_minutes}")
    click.echo(f"  Extraordinário: +{extra.extra_cycles} ciclos / +{extra.extra_minutes} min")
    click.echo("  -> confira: os 8 primeiros ciclos continuam valendo 35min mesmo com a")
    click.echo("     configuração atual em 45min. Essa é a regra central do manual (seção 2).")


@click.command("shell-info")
def shell_info_command():
    """Mostra rapidamente quantas linhas cada tabela tem."""
    from app import models as m

    tables = [
        m.Configuration, m.Session, m.FocusCycle, m.RestCycle,
        m.DailyMinimumProgress, m.DailyIdealProgress, m.ExtraordinaryProgress,
        m.WeeklyProgress, m.AbsoluteProgress, m.WishlistItem,
        m.Reward, m.RewardAchievement, m.WaterLog,
    ]
    for t in tables:
        click.echo(f"{t.__tablename__:28s} {t.query.count()}")
