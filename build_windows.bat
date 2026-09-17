@echo off
echo ========================================================
echo  Compilando Foco para Windows
echo ========================================================

python -m venv .venv
call .venv\Scripts\activate

python -m pip install --upgrade pip
pip install -r requirements.txt

pyinstaller --clean foco.spec

echo.
echo ========================================================
echo  Executavel gerado em: dist\foco.exe
echo ========================================================
pause
