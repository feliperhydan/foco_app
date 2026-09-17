"""
Service do Caderno Diário.

Gerencia o registro pessoal diário, o retrato do dia (snapshot do sistema + campos do usuário),
a programação por data, os protocolos cotidianos e as anotações pós-ciclo.
Preserva rigorosamente a integridade histórica (dias encerrados são congelados).
"""
from __future__ import annotations

from datetime import date as date_, datetime
from typing import Any

from app.extensions import db
from app.models import NotebookEntry, NotebookSchedule, PostCycleNote, Protocol
from app.services import clock, history_service


WEEKDAYS_PT = [
    "SEGUNDA-FEIRA", "TERÇA-FEIRA", "QUARTA-FEIRA",
    "QUINTA-FEIRA", "SEXTA-FEIRA", "SÁBADO", "DOMINGO"
]
MONTHS_PT = [
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]


def format_date_pt(d: date_) -> dict[str, str]:
    weekday_str = WEEKDAYS_PT[d.weekday()]
    date_str = f"{d.day} de {MONTHS_PT[d.month]} de {d.year}"
    return {"weekday": weekday_str, "date_formatted": date_str}


def get_or_create_notebook(d: date_) -> NotebookEntry:
    entry = NotebookEntry.query.filter_by(date=d).first()
    if entry is None:
        entry = NotebookEntry(
            date=d,
            registro_content=[],
            inicio_estudos="",
            fim_estudos="",
            nivel_cansaco=0,
            programacao_dismissed=False,
        )
        db.session.add(entry)
        db.session.commit()
    return entry


def save_registro_pessoal(d: date_, content: list[dict[str, Any]]) -> NotebookEntry:
    today = clock.today()
    # Integridade histórica: dias passados são congelados
    if d < today:
        return get_or_create_notebook(d)

    entry = get_or_create_notebook(d)
    entry.registro_content = content
    db.session.commit()
    return entry


def save_retrato_user_fields(d: date_, inicio: str | None, fim: str | None, cansaco: int | None) -> NotebookEntry:
    today = clock.today()
    if d < today:
        return get_or_create_notebook(d)

    entry = get_or_create_notebook(d)
    if inicio is not None:
        entry.inicio_estudos = inicio
    if fim is not None:
        entry.fim_estudos = fim
    if cansaco is not None:
        entry.nivel_cansaco = max(0, min(5, cansaco))
    db.session.commit()
    return entry


def get_retrato_snapshot(d: date_) -> dict[str, Any]:
    """
    Retorna o snapshot do Retrato do Dia.
    Reutiliza os dados do motor de histórico (history_service) sem calcular médias ou julgamentos.
    """
    day_data = history_service.get_day(d)
    entry = get_or_create_notebook(d)

    cycle_contexts = day_data.get("cycle_contexts", [])
    cycles_count = sum(c.get("focus", {}).get("cycles_completed", 0) for c in cycle_contexts)
    focus_minutes = sum(c.get("focus", {}).get("minutes_completed", 0) for c in cycle_contexts)
    session_started = day_data.get("session_started", False)

    # Formatar minutos de foco (ex: 4h40 ou 25 min)
    if focus_minutes >= 60:
        h = focus_minutes // 60
        m = focus_minutes % 60
        minutes_fmt = f"{h}h{m:02d}" if m > 0 else f"{h}h"
    else:
        minutes_fmt = f"{focus_minutes} min"

    short_breaks = sum(c.get("rest_short", {}).get("cycles_completed", 0) for c in cycle_contexts)
    long_breaks = sum(c.get("rest_long", {}).get("cycles_completed", 0) for c in cycle_contexts)
    pausas_fmt = f"{short_breaks} curtas · {long_breaks} longas"

    water_data = day_data.get("water", {})
    total_ml = water_data.get("total_ml", 0)
    total_l = round(total_ml / 1000.0, 2)
    l_str = str(int(total_l)) if total_l.is_integer() else str(total_l)
    water_fmt = f"{l_str} L".replace(".", ",")

    todo_data = day_data.get("todo", {})
    todo_total = todo_data.get("items_total", 0)
    todo_completed = todo_data.get("items_completed", 0)
    todo_fmt = f"{todo_completed}/{todo_total} concluídos" if todo_total > 0 else "0 concluídos"

    rewards = day_data.get("rewards", {})
    min_completed = rewards.get("daily_minimum", {}).get("goal_completed", False)
    ideal_completed = rewards.get("daily_ideal", {}).get("goal_completed", False)

    if min_completed and ideal_completed:
        metas_fmt = "Mínimo e Ideal concluídos"
    elif min_completed:
        metas_fmt = "Mínimo concluído"
    elif ideal_completed:
        metas_fmt = "Ideal concluído"
    else:
        metas_fmt = "Em andamento"

    # Se não houve sessões/ciclos registrados, usar o estado neutro definido no PDF
    has_activity = cycles_count > 0 or session_started or focus_minutes > 0

    return {
        "has_activity": has_activity,
        "cycles": cycles_count,
        "focus_minutes_fmt": minutes_fmt,
        "pausas_fmt": pausas_fmt,
        "water_fmt": water_fmt,
        "todo_fmt": todo_fmt,
        "metas_fmt": metas_fmt,
        "user_inicio": entry.inicio_estudos or "",
        "user_fim": entry.fim_estudos or "",
        "user_cansaco": entry.nivel_cansaco or 0,
    }


# ---------------------------------------------------------------------------
# PROGRAMAÇÃO POR DATA
# ---------------------------------------------------------------------------

def get_programacao_items(d: date_) -> list[dict[str, Any]]:
    items = NotebookSchedule.query.filter_by(target_date=d).order_by(NotebookSchedule.id.asc()).all()
    return [item.as_dict() for item in items]


def add_programacao_item(target_date: date_, text: str) -> NotebookSchedule:
    item = NotebookSchedule(target_date=target_date, text=text, copied=False)
    db.session.add(item)
    db.session.commit()
    return item


def delete_programacao_item(item_id: int) -> bool:
    item = db.session.get(NotebookSchedule, item_id)
    if item:
        db.session.delete(item)
        db.session.commit()
        return True
    return False


def dismiss_programacao(d: date_) -> None:
    entry = get_or_create_notebook(d)
    entry.programacao_dismissed = True
    db.session.commit()


def copy_programacao_to_registro(d: date_) -> list[dict[str, Any]]:
    """
    Copia os itens agendados para o Registro Pessoal como linhas com bullet.
    """
    entry = get_or_create_notebook(d)
    items = NotebookSchedule.query.filter_by(target_date=d).all()

    existing_lines = list(entry.registro_content or [])

    for item in items:
        # Adicionar item como bullet
        bullet_line = {
            "id": f"line-{int(datetime.now().timestamp() * 1000)}-{item.id}",
            "text": item.text,
            "type": "bullet",
            "checked": False,
            "bold": False,
            "color": "default",
            "time": "",
        }
        existing_lines.append(bullet_line)
        item.copied = True

    entry.registro_content = existing_lines
    entry.programacao_dismissed = True
    db.session.commit()
    return existing_lines


# ---------------------------------------------------------------------------
# PROTOCOLOS COTIDIANOS
# ---------------------------------------------------------------------------

DEFAULT_PROTOCOLS = [
    {
        "title": "Revisão Matinal",
        "objective": "Alinhar prioridades e clarear a mente antes do primeiro ciclo de foco.",
        "activities": ["Revisar metas do dia", "Verificar materiais e abas abertas", "Definir único objetivo do 1º ciclo"],
        "avg_duration_minutes": 10,
        "recommended_time": "07:30 - 08:00",
        "is_default": True,
    },
    {
        "title": "Encerramento do Dia",
        "objective": "Concluir as atividades do dia e desconectar o cérebro do trabalho.",
        "activities": ["Anotar observações no Caderno Diário", "Organizar a lista de to-do de amanhã", "Fechar abas e programas não utilizados"],
        "avg_duration_minutes": 15,
        "recommended_time": "18:00 - 18:30",
        "is_default": True,
    },
    {
        "title": "Preparação para Estudos Intensos",
        "objective": "Garantir ambiente e foco máximo sem interrupções.",
        "activities": ["Colocar celular em Modo Foco / Silencioso", "Encher a garrafa de água (1L)", "Revisar anotações rápidas do ciclo anterior"],
        "avg_duration_minutes": 5,
        "recommended_time": "08:00 - 08:30",
        "is_default": True,
    },
    {
        "title": "Descompressão Pós-Estudo",
        "objective": "Descansar a vista e acelerar a assimilação de conteúdo.",
        "activities": ["Alongar pescoço e ombros", "Caminhar longe das telas", "Beber água e respirar fundo por 3 minutos"],
        "avg_duration_minutes": 10,
        "recommended_time": "12:00 - 12:30",
        "is_default": True,
    },
    {
        "title": "Revisão de Conteúdo Complexo",
        "objective": "Consolidar conceitos difíceis de aulas e estudos.",
        "activities": ["Escrever resumo simples em voz alta", "Resolver 3 exercícios sem consultar gabarito", "Anotar dúvidas no Caderno Pós-ciclos"],
        "avg_duration_minutes": 25,
        "recommended_time": "14:00 - 15:00",
        "is_default": True,
    },
]


def seed_default_protocols_if_needed() -> None:
    if Protocol.query.count() == 0:
        for proto in DEFAULT_PROTOCOLS:
            p = Protocol(
                title=proto["title"],
                objective=proto["objective"],
                activities=proto["activities"],
                avg_duration_minutes=proto["avg_duration_minutes"],
                recommended_time=proto["recommended_time"],
                is_default=True,
            )
            db.session.add(p)
        db.session.commit()


def get_protocols() -> list[dict[str, Any]]:
    seed_default_protocols_if_needed()
    protocols = Protocol.query.order_by(Protocol.id.asc()).all()
    return [p.as_dict() for p in protocols]


def create_protocol(title: str, objective: str, activities: list[str], avg_duration: int, recommended_time: str) -> Protocol | None:
    if Protocol.query.count() >= 6:
        return None
    p = Protocol(
        title=title,
        objective=objective,
        activities=activities,
        avg_duration_minutes=avg_duration,
        recommended_time=recommended_time,
        is_default=False,
    )
    db.session.add(p)
    db.session.commit()
    return p


def update_protocol(protocol_id: int, title: str, objective: str, activities: list[str], avg_duration: int, recommended_time: str) -> Protocol | None:
    p = Protocol.query.get(protocol_id)
    if not p:
        return None
    p.title = title
    p.objective = objective
    p.activities = activities
    p.avg_duration_minutes = avg_duration
    p.recommended_time = recommended_time
    db.session.commit()
    return p


def delete_protocol(protocol_id: int) -> bool:
    p = Protocol.query.get(protocol_id)
    if not p:
        return False
    db.session.delete(p)
    db.session.commit()
    return True


def copy_protocol_to_registro(d: date_, protocol_id: int) -> list[dict[str, Any]] | None:
    """
    Copia as atividades de um protocolo para o Registro Pessoal do dia `d` como linhas com checkbox.
    """
    proto = Protocol.query.get(protocol_id)
    if not proto:
        return None

    entry = get_or_create_notebook(d)
    existing_lines = list(entry.registro_content or [])

    now = datetime.now()
    now_str = now.strftime("%H:%M")
    base_ts = int(now.timestamp() * 1000)

    for idx, act_text in enumerate(proto.activities or []):
        chk_line = {
            "id": f"line-{base_ts}-{idx}",
            "time": now_str,
            "text": act_text,
            "type": "checkbox",
            "checked": False,
            "bold": False,
            "color": "default",
            "size": "small",
        }
        existing_lines.append(chk_line)

    entry.registro_content = existing_lines
    db.session.commit()
    return existing_lines


# ---------------------------------------------------------------------------
# ANOTAÇÕES PÓS-CICLO
# ---------------------------------------------------------------------------

POST_CYCLE_CATEGORY_PRIORITY = {
    "lembrete": 1,
    "duvida": 2,
    "dúvida": 2,
    "tarefa": 3,
    "ideia": 4,
}


def get_post_cycle_notes(d: date_) -> list[dict[str, Any]]:
    notes = PostCycleNote.query.filter_by(date=d).order_by(PostCycleNote.id.asc()).all()
    notes.sort(
        key=lambda n: (
            POST_CYCLE_CATEGORY_PRIORITY.get((n.category or "").lower().strip(), 99),
            n.id,
        )
    )
    return [n.as_dict() for n in notes]


def add_post_cycle_note(d: date_, content: str, category: str = "lembrete", cycle_number: int | None = None) -> PostCycleNote:
    note = PostCycleNote(
        date=d,
        content=content,
        category=category,
        cycle_number=cycle_number,
        resolved=False,
    )
    db.session.add(note)
    db.session.commit()
    return note


def toggle_post_cycle_note(note_id: int) -> PostCycleNote | None:
    note = db.session.get(PostCycleNote, note_id)
    if note:
        note.resolved = not note.resolved
        db.session.commit()
    return note


def delete_post_cycle_note(note_id: int) -> bool:
    note = db.session.get(PostCycleNote, note_id)
    if note:
        db.session.delete(note)
        db.session.commit()
        return True
    return False
