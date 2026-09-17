"""
Serviço de Recompensas (manual, seção 15, 16, 40 — "nunca gerar
recompensa duas vezes pelo mesmo evento").

Chamado pelo motor de conclusão logo depois que o progresso é
atualizado, só quando uma entidade de progresso ACABOU de completar
(flag `*_just_completed` vinda de `progress_service.apply_cycle_completion`).
Isso garante que uma recompensa nunca é registrada duas vezes para o
mesmo evento de conclusão — o gatilho é a transição de estado, não o
estado em si.
"""
from datetime import date as date_

from app.extensions import db
from app.models import Reward, RewardAchievement


def _register(reward: Reward, achieved_date: date_, start_date=None, end_date=None):
    achievement = RewardAchievement(
        reward_id=reward.id, achieved_date=achieved_date,
        title_snapshot=reward.title,
        start_date=start_date, end_date=end_date,
    )
    db.session.add(achievement)
    return achievement


def check_and_register_for_progress(progress_type: str, achieved_date: date_,
                                     start_date=None, end_date=None,
                                     absolute_progress_id: int | None = None) -> list[RewardAchievement]:
    """
    progress_type: 'daily_minimum' | 'daily_ideal' | 'weekly' | 'absolute'

    Só deve ser chamada quando a entidade de progresso correspondente
    ACABOU de virar 'completed' — a checagem de "já completou antes"
    é responsabilidade de quem chama (progress_service), não daqui.
    """
    query = Reward.query.filter_by(progress_type=progress_type, active=True)
    if progress_type == "absolute" and absolute_progress_id is not None:
        query = query.filter(
            (Reward.absolute_progress_id == absolute_progress_id)
            | (Reward.absolute_progress_id.is_(None))
        )
    rewards = query.all()

    achievements = []
    for reward in rewards:
        achievements.append(_register(reward, achieved_date, start_date, end_date))
    return achievements
