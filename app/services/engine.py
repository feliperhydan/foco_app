"""
Motor de Conclusão de Ciclo (manual, seção 17, 18, 42).

Este é o ÚNICO caminho do sistema por onde um FocusCycle passa a
contar como progresso. Nenhuma outra parte do código (rotas, JS,
estatísticas) deve incrementar contadores de progresso diretamente —
todas leem o resultado desta função.

Propriedades garantidas aqui:
  - IDEMPOTÊNCIA (seção 18): concluir o mesmo ciclo duas vezes nunca
    duplica contagem — a segunda chamada é um no-op que retorna o
    estado já existente.
  - TRANSAÇÃO ÚNICA (seção 42): ciclo, progresso e recompensas são
    gravados no mesmo commit. Se algo falhar no meio, nada é
    persistido (rollback) — a interface nunca deve mostrar "ciclo
    concluído" com contabilização parcial.
"""
from app.extensions import db
from app.models import FocusCycle
from app.services.clock import now, today
from app.services import progress_service, rewards_service


def complete_focus_cycle(cycle_id: int, title: str | None = None) -> dict:
    cycle = db.session.get(FocusCycle, cycle_id)
    if cycle is None:
        return {"ok": False, "error": "ciclo não encontrado"}

    # --- idempotência: já concluído ou abandonado -> não recontabiliza ---
    if cycle.status != "started":
        return {
            "ok": True,
            "already_processed": True,
            "cycle_id": cycle.id,
            "status": cycle.status,
        }

    if cycle.session is not None and cycle.session.date != today():
        return {
            "ok": False,
            "error": "ciclo fora do dia atual",
            "cycle_id": cycle.id,
            "session_date": cycle.session.date.isoformat() if cycle.session.date else None,
            "today": today().isoformat(),
        }

    try:
        cycle.completed_at = now()
        cycle.status = "completed"
        if title:
            cycle.title = title.strip()[:280]
        db.session.flush()

        progress_result = progress_service.apply_cycle_completion(cycle)

        achieved = []
        d = cycle.completed_at.date()

        if progress_result["daily_minimum_just_completed"]:
            achieved += rewards_service.check_and_register_for_progress("daily_minimum", d)
        if progress_result["daily_ideal_just_completed"]:
            achieved += rewards_service.check_and_register_for_progress("daily_ideal", d)
        if progress_result["weekly_just_completed"]:
            weekly = progress_result["weekly"]
            achieved += rewards_service.check_and_register_for_progress(
                "weekly", d, start_date=weekly.week_start, end_date=weekly.week_end
            )
        if progress_result["absolute_just_completed"]:
            absolute = progress_result["absolute"]
            achieved += rewards_service.check_and_register_for_progress(
                "absolute", d, absolute_progress_id=absolute.id
            )

        from app.services import daily_service
        daily_service.consolidate_daily(d, commit=False)

        db.session.commit()  # COMMIT único — seção 42
    except Exception:
        db.session.rollback()
        raise


    return {
        "ok": True,
        "already_processed": False,
        "cycle_id": cycle.id,
        "focus_duration_minutes": cycle.focus_duration_minutes,
        "daily_minimum_just_completed": progress_result["daily_minimum_just_completed"],
        "daily_ideal_just_completed": progress_result["daily_ideal_just_completed"],
        "extraordinary_just_unlocked": progress_result["extraordinary_just_unlocked"],
        "extraordinary_cycles": progress_result["extraordinary_cycles"],
        "weekly_just_completed": progress_result["weekly_just_completed"],
        "absolute_just_completed": progress_result["absolute_just_completed"],
        "rewards_achieved": [a.reward.title for a in achieved],
        "post_cycle_message": "",
    }
