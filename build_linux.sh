#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "==> Verificando ambiente virtual..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

echo "==> Instalando/Atualizando dependências..."
.venv/bin/pip install -r requirements.txt

echo "==> Compilando executável com PyInstaller..."
.venv/bin/pyinstaller --clean foco.spec

echo ""
echo "=========================================================="
echo " Sucesso! Executável gerado em:"
echo "   $DIR/dist/foco"
echo "=========================================================="
