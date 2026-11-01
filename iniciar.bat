@echo off
chcp 65001 >nul
if not exist .venv\Scripts\buscaimoveis.exe (echo Rode instalar.bat primeiro. & pause & exit /b 1)
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8000"
.venv\Scripts\buscaimoveis servir --celular
pause
