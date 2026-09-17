"""
Rotas do Caderno Diário.
"""
from datetime import date as date_, datetime, timedelta
from flask import Blueprint, jsonify, render_template, request, redirect, url_for

from app.services import clock, notebook_service
from app.services.config_service import get_current_configuration

notebook_bp = Blueprint("notebook", __name__)


def _parse_date(raw: str | None) -> date_:
    if raw:
        try:
            return date_.fromisoformat(raw)
        except ValueError:
            pass
    return clock.today()


@notebook_bp.route("/caderno")
def notebook():
    ref_date = _parse_date(request.args.get("date"))
    today = clock.today()

    is_today = ref_date == today
    is_past = ref_date < today
    is_future = ref_date > today

    prev_date = ref_date - timedelta(days=1)
    next_date = ref_date + timedelta(days=1)

    tab = request.args.get("tab", "registro")
    if tab not in ("registro", "retrato", "programacao", "protocolos", "pos_ciclos"):
        tab = "registro"

    date_fmt = notebook_service.format_date_pt(ref_date)
    entry = notebook_service.get_or_create_notebook(ref_date)
    retrato = notebook_service.get_retrato_snapshot(ref_date)
    programacao_items = notebook_service.get_programacao_items(ref_date)
    protocols = notebook_service.get_protocols()
    post_cycle_notes = notebook_service.get_post_cycle_notes(ref_date)

    show_programacao_banner = is_today and (not entry.programacao_dismissed) and (len(programacao_items) > 0)

    return render_template(
        "notebook.html",
        cfg=get_current_configuration(),
        ref_date=ref_date,
        today=today,
        is_today=is_today,
        is_past=is_past,
        is_future=is_future,
        prev_date=prev_date.isoformat(),
        next_date=next_date.isoformat(),
        date_fmt=date_fmt,
        tab=tab,
        entry=entry,
        retrato=retrato,
        programacao_items=programacao_items,
        protocols=protocols,
        post_cycle_notes=post_cycle_notes,
        show_programacao_banner=show_programacao_banner,
    )


# ---------------------------------------------------------------------------
# API ENDPOINTS
# ---------------------------------------------------------------------------

@notebook_bp.route("/api/notebook/save_registro", methods=["POST"])
def save_registro():
    data = request.get_json() or {}
    ref_date = _parse_date(data.get("date"))
    content = data.get("content", [])

    entry = notebook_service.save_registro_pessoal(ref_date, content)
    return jsonify({"status": "ok", "entry": entry.as_dict()})


@notebook_bp.route("/api/notebook/save_retrato", methods=["POST"])
def save_retrato():
    data = request.get_json() or {}
    ref_date = _parse_date(data.get("date"))
    inicio = data.get("inicio_estudos")
    fim = data.get("fim_estudos")
    cansaco = data.get("nivel_cansaco")

    entry = notebook_service.save_retrato_user_fields(ref_date, inicio, fim, cansaco)
    return jsonify({"status": "ok", "entry": entry.as_dict()})


@notebook_bp.route("/api/notebook/programacao/add", methods=["POST"])
def add_programacao():
    data = request.get_json() or request.form
    target_date = _parse_date(data.get("target_date"))
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"status": "error", "message": "Texto vazio"}), 400

    item = notebook_service.add_programacao_item(target_date, text)
    return jsonify({"status": "ok", "item": item.as_dict()})


@notebook_bp.route("/api/notebook/programacao/delete", methods=["POST"])
def delete_programacao():
    data = request.get_json() or {}
    item_id = data.get("item_id")
    if not item_id:
        return jsonify({"status": "error", "message": "ID não fornecido"}), 400
    success = notebook_service.delete_programacao_item(item_id)
    if not success:
        return jsonify({"status": "error", "message": "Item não encontrado"}), 404
    return jsonify({"status": "ok"})


@notebook_bp.route("/api/notebook/programacao/dismiss", methods=["POST"])
def dismiss_programacao():
    data = request.get_json() or {}
    ref_date = _parse_date(data.get("date"))
    notebook_service.dismiss_programacao(ref_date)
    return jsonify({"status": "ok"})


@notebook_bp.route("/api/notebook/programacao/copy", methods=["POST"])
def copy_programacao():
    data = request.get_json() or {}
    ref_date = _parse_date(data.get("date"))
    new_content = notebook_service.copy_programacao_to_registro(ref_date)
    return jsonify({"status": "ok", "registro_content": new_content})


@notebook_bp.route("/api/notebook/pos_ciclos/add", methods=["POST"])
def add_pos_ciclos():
    data = request.get_json() or request.form
    ref_date = _parse_date(data.get("date"))
    content = data.get("content", "").strip()
    category = data.get("category", "lembrete")
    cycle_num = data.get("cycle_number")

    if not content:
        return jsonify({"status": "error", "message": "Conteúdo vazio"}), 400

    note = notebook_service.add_post_cycle_note(ref_date, content, category, cycle_num)
    return jsonify({"status": "ok", "note": note.as_dict()})


@notebook_bp.route("/api/notebook/pos_ciclos/toggle", methods=["POST"])
def toggle_pos_ciclos():
    data = request.get_json() or {}
    note_id = data.get("note_id")
    note = notebook_service.toggle_post_cycle_note(note_id)
    if not note:
        return jsonify({"status": "error", "message": "Nota não encontrada"}), 404
    return jsonify({"status": "ok", "note": note.as_dict()})


@notebook_bp.route("/api/notebook/pos_ciclos/delete", methods=["POST"])
def delete_pos_ciclos():
    data = request.get_json() or {}
    note_id = data.get("note_id")
    if not note_id:
        return jsonify({"status": "error", "message": "ID não fornecido"}), 400
    success = notebook_service.delete_post_cycle_note(note_id)
    if not success:
        return jsonify({"status": "error", "message": "Nota não encontrada"}), 404
    return jsonify({"status": "ok"})


@notebook_bp.route("/api/notebook/protocols/add", methods=["POST"])
def add_protocol():
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    objective = data.get("objective", "").strip()
    activities = data.get("activities", [])
    if isinstance(activities, str):
        activities = [a.strip() for a in activities.split("\n") if a.strip()]
    try:
        avg_duration = int(data.get("avg_duration_minutes") or 15)
    except (ValueError, TypeError):
        avg_duration = 15
    recommended_time = data.get("recommended_time", "").strip()

    if not title or not objective:
        return jsonify({"status": "error", "message": "Título e objetivo são obrigatórios"}), 400

    if len(notebook_service.get_protocols()) >= 6:
        return jsonify({"status": "error", "message": "Limite de 6 protocolos atingido"}), 400

    proto = notebook_service.create_protocol(title, objective, activities, avg_duration, recommended_time)
    if not proto:
        return jsonify({"status": "error", "message": "Não foi possível criar o protocolo (limite atingido)"}), 400
    return jsonify({"status": "ok", "protocol": proto.as_dict()})


@notebook_bp.route("/api/notebook/protocols/update", methods=["POST"])
def update_protocol():
    data = request.get_json() or {}
    protocol_id = data.get("id")
    if not protocol_id:
        return jsonify({"status": "error", "message": "ID não fornecido"}), 400

    title = data.get("title", "").strip()
    objective = data.get("objective", "").strip()
    activities = data.get("activities", [])
    if isinstance(activities, str):
        activities = [a.strip() for a in activities.split("\n") if a.strip()]
    try:
        avg_duration = int(data.get("avg_duration_minutes") or 15)
    except (ValueError, TypeError):
        avg_duration = 15
    recommended_time = data.get("recommended_time", "").strip()

    if not title or not objective:
        return jsonify({"status": "error", "message": "Título e objetivo são obrigatórios"}), 400

    proto = notebook_service.update_protocol(protocol_id, title, objective, activities, avg_duration, recommended_time)
    if not proto:
        return jsonify({"status": "error", "message": "Protocolo não encontrado"}), 404
    return jsonify({"status": "ok", "protocol": proto.as_dict()})


@notebook_bp.route("/api/notebook/protocols/delete", methods=["POST"])
def delete_protocol():
    data = request.get_json() or {}
    protocol_id = data.get("id")
    if not protocol_id:
        return jsonify({"status": "error", "message": "ID não fornecido"}), 400

    success = notebook_service.delete_protocol(protocol_id)
    if not success:
        return jsonify({"status": "error", "message": "Protocolo não encontrado"}), 404
    return jsonify({"status": "ok"})


@notebook_bp.route("/api/notebook/protocols/copy", methods=["POST"])
def copy_protocol():
    data = request.get_json() or {}
    ref_date = _parse_date(data.get("date"))
    protocol_id = data.get("protocol_id") or data.get("id")
    if not protocol_id:
        return jsonify({"status": "error", "message": "ID do protocolo não fornecido"}), 400

    new_content = notebook_service.copy_protocol_to_registro(ref_date, int(protocol_id))
    if new_content is None:
        return jsonify({"status": "error", "message": "Protocolo não encontrado"}), 404

    return jsonify({"status": "ok", "registro_content": new_content})
