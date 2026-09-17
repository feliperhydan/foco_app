#!/usr/bin/env python3
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
from pathlib import Path

from app import create_app


def get_data_dir() -> Path:
    if sys.platform == "win32":
        data_dir = Path(os.environ.get("APPDATA", Path.home())) / "Foco"
    else:
        data_dir = Path.home() / ".local" / "share" / "Foco"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def setup_logging():
    log_dir = get_data_dir()
    log_file = log_dir / "foco_app.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout) if sys.stdout else logging.NullHandler(),
        ],
    )
    logging.info("Iniciando Foco Desktop Application...")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def wait_for_server(url: str, timeout: float = 6.0) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def find_app_browser():
    """
    Busca um navegador com suporte a modo janela (--app=URL).
    Retorna uma lista de comando base ou None.
    """
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        local_appdata = os.environ.get("LocalAppData", "")

        candidates = [
            Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(local_appdata) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(local_appdata) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(program_files) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate)]
        # Tenta no PATH do Windows
        for name in ["msedge.exe", "chrome.exe", "brave.exe"]:
            cmd = shutil.which(name)
            if cmd:
                return [cmd]
        return None

    # Linux / macOS
    linux_executables = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
    ]
    for exe in linux_executables:
        cmd = shutil.which(exe)
        if cmd:
            return [cmd]

    # Verifica flatpaks comuns no Linux
    flatpak_cmd = shutil.which("flatpak")
    if flatpak_cmd:
        flatpak_apps = [
            "com.google.Chrome",
            "org.chromium.Chromium",
            "com.brave.Browser",
            "com.microsoft.Edge",
        ]
        for app_id in flatpak_apps:
            check = subprocess.run(
                [flatpak_cmd, "info", app_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if check.returncode == 0:
                return [flatpak_cmd, "run", app_id]

    return None


def main():
    setup_logging()
    port = find_free_port()
    url = f"http://127.0.0.1:{port}/"
    logging.info(f"Porta local selecionada: {port}")

    # Inicia o servidor Flask com Waitress em thread paralela
    from threading import Thread
    from waitress import serve

    flask_app = create_app()

    def run_server():
        try:
            serve(flask_app, host="127.0.0.1", port=port, _quiet=True, threads=4)
        except Exception as exc:
            logging.error(f"Erro no servidor Waitress: {exc}", exc_info=True)

    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    # Health check antes de abrir a janela
    logging.info("Aguardando servidor local responder...")
    if not wait_for_server(url, timeout=7.0):
        logging.error("O servidor não respondeu a tempo.")
        sys.exit(1)

    logging.info(f"Servidor online em {url}. Abrindo interface gráfica...")

    browser_cmd = find_app_browser()

    # Perfil isolado para modo app
    profile_dir = Path(tempfile.gettempdir()) / f"foco_browser_{port}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    if browser_cmd:
        logging.info(f"Iniciando janela nativa com comando: {browser_cmd}")
        args = list(browser_cmd) + [
            f"--app={url}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,820",
        ]
        try:
            proc = subprocess.Popen(args)
            proc.wait()
            logging.info("Janela do aplicativo fechada pelo usuário. Encerrando...")
        except Exception as exc:
            logging.error(f"Falha ao abrir modo app: {exc}. Usando fallback...", exc_info=True)
            webbrowser.open(url)
            # Mantém vivo se fallback foi usado
            while True:
                time.sleep(1)
    else:
        logging.info("Nenhum navegador com suporte a modo app detectado. Abrindo no navegador padrão...")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Encerrando via teclado...")

    # Limpa perfil temporário
    try:
        shutil.rmtree(profile_dir, ignore_errors=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
