@echo off
chcp 65001 >nul
echo === Instalando o Buscador de imoveis ===
where py >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python 3.10 ou mais novo em https://www.python.org/downloads/
  echo e marque a opcao "Add python.exe to PATH" durante a instalacao. Depois rode este arquivo de novo.
  pause & exit /b 1
)
py -3 -m venv .venv || (echo Falha ao criar o ambiente. & pause & exit /b 1)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[rapido]" || .venv\Scripts\python -m pip install -e . || (echo Falha na instalacao. Verifique a internet. & pause & exit /b 1)
echo.
echo Pronto! Para usar, de dois cliques em iniciar.bat
pause
