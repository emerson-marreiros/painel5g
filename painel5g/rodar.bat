@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente .venv e instalando dependencias...
  py -3.12 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" -m streamlit run app.py
pause
