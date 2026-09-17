import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, Response

from app.services.config_service import get_current_configuration, update_configuration, configuration_history

settings_bp = Blueprint("settings", __name__)


import os
from werkzeug.utils import secure_filename
from flask import current_app

def get_sounds_dir(category=None):
    if category and category in ("focus_end", "conclude_btn", "rest_end"):
        folder = os.path.join(current_app.root_path, "static", "sounds", "uploads", category)
    else:
        folder = os.path.join(current_app.root_path, "static", "sounds", "uploads")
    os.makedirs(folder, exist_ok=True)
    return folder

def _get_custom_sounds(category):
    folder = get_sounds_dir(category)
    custom_sounds = []
    if os.path.exists(folder):
        for fname in sorted(os.listdir(folder)):
            if fname.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".aac")):
                url = f"/static/sounds/uploads/{category}/{fname}"
                display_name = f"Personalizado — {fname}"
                custom_sounds.append({"name": display_name, "url": url})
    return custom_sounds

def _get_available_sounds():
    return {
        "focus_end": {
            "default": {"name": "Padrão", "url": "/static/sounds/fim_de_foco.mp3"},
            "custom": _get_custom_sounds("focus_end"),
        },
        "conclude_btn": {
            "default": {"name": "Padrão", "url": "/static/sounds/do_pos_conclusao.mp3"},
            "custom": _get_custom_sounds("conclude_btn"),
        },
        "rest_end": {
            "default": {"name": "Padrão", "url": "/static/sounds/fim_de_descanso.mp3"},
            "custom": _get_custom_sounds("rest_end"),
        },
    }

@settings_bp.route("/configuracoes", methods=["GET"])
def settings():
    cfg = get_current_configuration()
    history = configuration_history()
    backup_ok = request.args.get("backup_ok")
    backup_msg = request.args.get("backup_msg")
    category_sounds = _get_available_sounds()
    return render_template(
        "settings.html",
        cfg=cfg,
        history=history,
        backup_ok=(backup_ok == "1") if backup_ok is not None else None,
        backup_msg=backup_msg,
        category_sounds=category_sounds,
    )

@settings_bp.route("/configuracoes/som/upload", methods=["POST"])
def upload_sound():
    file = request.files.get("audio_file")
    sound_category = request.form.get("sound_category")  # 'focus_end' | 'conclude_btn' | 'rest_end'
    
    if not file or not file.filename or sound_category not in ("focus_end", "conclude_btn", "rest_end"):
        return redirect(url_for("settings.settings"))
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".mp3", ".wav", ".ogg", ".m4a", ".aac"):
        return redirect(url_for("settings.settings"))
    
    fname = secure_filename(file.filename)
    if not fname:
        fname = f"custom_sound_{int(datetime.now().timestamp())}{ext}"
    
    target_dir = get_sounds_dir(sound_category)
    target_path = os.path.join(target_dir, fname)
    file.save(target_path)
    
    url = f"/static/sounds/uploads/{sound_category}/{fname}"
    changes = {}
    if sound_category == "focus_end":
        changes["sound_focus_end"] = url
    elif sound_category == "conclude_btn":
        changes["sound_conclude_btn"] = url
    elif sound_category == "rest_end":
        changes["sound_rest_end"] = url
    
    if changes:
        update_configuration(**changes)
    
    return redirect(url_for("settings.settings"))

@settings_bp.route("/configuracoes/som/delete", methods=["POST"])
def delete_sound():
    sound_category = request.form.get("sound_category")
    sound_url = request.form.get("sound_url")

    if sound_category not in ("focus_end", "conclude_btn", "rest_end"):
        return redirect(url_for("settings.settings"))

    expected_prefix = f"/static/sounds/uploads/{sound_category}/"
    if not sound_url or not sound_url.startswith(expected_prefix):
        return redirect(url_for("settings.settings"))

    filename = os.path.basename(sound_url)
    fname = secure_filename(filename)
    if not fname:
        return redirect(url_for("settings.settings"))

    target_path = os.path.join(get_sounds_dir(sound_category), fname)
    if os.path.isfile(target_path):
        os.remove(target_path)

    # Se o som deletado era o ativo nessa categoria, volta ao padrão
    field_defaults = {
        "focus_end":    ("sound_focus_end",    "/static/sounds/fim_de_foco.mp3"),
        "conclude_btn": ("sound_conclude_btn", "/static/sounds/do_pos_conclusao.mp3"),
        "rest_end":     ("sound_rest_end",     "/static/sounds/fim_de_descanso.mp3"),
    }
    field, default_url = field_defaults[sound_category]
    cfg = get_current_configuration()
    if getattr(cfg, field, None) == sound_url:
        update_configuration(**{field: default_url})

    return redirect(url_for("settings.settings"))

@settings_bp.route("/configuracoes/backup/download", methods=["GET"])
def download_backup():
    from app.services import backup_service
    backup_data = backup_service.export_backup()
    json_str = json.dumps(backup_data, indent=2, ensure_ascii=False)
    filename = f"focus_backup_{datetime.now().strftime('%Y-%m-%d')}.json"
    return Response(
        json_str,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@settings_bp.route("/configuracoes/backup/restore", methods=["POST"])
def restore_backup():
    from app.services import backup_service
    file = request.files.get("backup_file")
    if not file or not file.filename:
        return redirect(url_for("settings.settings", backup_ok=0, backup_msg="Nenhum arquivo enviado."))

    try:
        content = json.load(file)
    except Exception:
        return redirect(url_for("settings.settings", backup_ok=0, backup_msg="Arquivo de backup selecionado não é um JSON válido."))

    ok, msg = backup_service.import_backup(content)
    return redirect(url_for("settings.settings", backup_ok=1 if ok else 0, backup_msg=msg))



@settings_bp.route("/configuracoes", methods=["POST"])
def update_settings():
    form = request.form
    changes = {}
    int_fields = [
        "focus_minutes", "short_break_minutes", "long_break_minutes",
        "cycles_per_session", "daily_minimum_goal", "daily_ideal_goal",
        "weekly_goal", "water_bottle_ml", "water_goal_ml",
        "volume_system", "volume_focus_end", "volume_rest_end",
    ]
    for field in int_fields:
        raw = form.get(field)
        if raw is not None and raw != "":
            try:
                val = int(raw)
                if field.startswith("volume_"):
                    val = max(0, min(100, val))
                changes[field] = val
            except ValueError:
                pass

    theme = form.get("theme")
    if theme in ("light", "dark", "auto"):
        changes["theme"] = theme

    debug_tools_enabled = form.get("debug_tools_enabled")
    changes["debug_tools_enabled"] = debug_tools_enabled in ("1", "true", "on", "yes")

    auto_start_focus = form.get("auto_start_focus")
    changes["auto_start_focus"] = auto_start_focus in ("1", "true", "on", "yes")

    auto_start_break = form.get("auto_start_break")
    changes["auto_start_break"] = auto_start_break in ("1", "true", "on", "yes")

    post_cycle_messages_enabled = form.get("post_cycle_messages_enabled")
    changes["post_cycle_messages_enabled"] = post_cycle_messages_enabled in ("1", "true", "on", "yes")

    sound_focus_end = form.get("sound_focus_end")
    if sound_focus_end:
        changes["sound_focus_end"] = sound_focus_end

    sound_conclude_btn = form.get("sound_conclude_btn")
    if sound_conclude_btn:
        changes["sound_conclude_btn"] = sound_conclude_btn

    sound_rest_end = form.get("sound_rest_end")
    if sound_rest_end:
        changes["sound_rest_end"] = sound_rest_end

    update_configuration(**changes)
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/debug/time/advance", methods=["POST"])
def debug_advance_time():
    from app.services.config_service import debug_tools_enabled
    if not debug_tools_enabled():
        return redirect(url_for("settings.settings"))
    from app.services.debug_service import advance_time
    days_raw = request.form.get("days", "1")
    try:
        days = int(days_raw)
    except ValueError:
        days = 1
    advance_time(days)
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/debug/time/reset", methods=["POST"])
def debug_reset_time():
    from app.services.config_service import debug_tools_enabled
    if not debug_tools_enabled():
        return redirect(url_for("settings.settings"))
    from app.services.debug_service import reset_time
    reset_time()
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/debug/cycles/simulate", methods=["POST"])
def debug_simulate_cycles():
    from app.services.config_service import debug_tools_enabled
    if not debug_tools_enabled():
        return redirect(url_for("settings.settings"))
    from app.services.debug_service import simulate_cycles
    count_raw = request.form.get("count", "1")
    title = request.form.get("title", "Debug cycle")
    try:
        count = int(count_raw)
    except ValueError:
        count = 1
    simulate_cycles(count=count, title=title)
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/debug/day/complete", methods=["POST"])
def debug_complete_day():
    from app.services.config_service import debug_tools_enabled
    if not debug_tools_enabled():
        return redirect(url_for("settings.settings"))
    from app.services.debug_service import complete_day_goal
    target = request.form.get("target", "ideal")
    if target not in ("minimum", "ideal"):
        target = "ideal"
    complete_day_goal(target=target)
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/debug/week/next", methods=["POST"])
def debug_next_week():
    from app.services.config_service import debug_tools_enabled
    if not debug_tools_enabled():
        return redirect(url_for("settings.settings"))
    from app.services.debug_service import jump_to_next_week
    jump_to_next_week()
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/debug/data/generate", methods=["POST"])
def debug_generate_data():
    from app.services.config_service import debug_tools_enabled
    if not debug_tools_enabled():
        return redirect(url_for("settings.settings"))
    from app.services.debug_service import generate_test_data
    try:
        days = int(request.form.get("days", "7"))
    except ValueError:
        days = 7
    try:
        cycles_per_day = int(request.form.get("cycles_per_day", "3"))
    except ValueError:
        cycles_per_day = 3
    try:
        water_per_day = int(request.form.get("water_per_day", "2"))
    except ValueError:
        water_per_day = 2
    generate_test_data(days=days, cycles_per_day=cycles_per_day, water_per_day=water_per_day)
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/debug/data/clear-generated", methods=["POST"])
def debug_clear_generated_data():
    from app.services.config_service import debug_tools_enabled
    if not debug_tools_enabled():
        return redirect(url_for("settings.settings"))
    from app.services.debug_service import clear_generated_test_data
    clear_generated_test_data()
    return redirect(url_for("settings.settings"))


@settings_bp.route("/configuracoes/debug/data/clear", methods=["POST"])
def debug_clear_database():
    from app.services.config_service import debug_tools_enabled
    if not debug_tools_enabled():
        return redirect(url_for("settings.settings"))
    from app.services.debug_service import clear_database_data
    clear_database_data()
    return redirect(url_for("settings.settings"))
