@echo off
REM Levanta el backend de la simulacion. Doble click, o "correr-server" en cmd.
REM Deja esta ventana abierta mientras usas Unity: aqui se ven los ticks.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No encuentro el entorno virtual en .venv
    echo.
    echo Crealo con:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Backend en http://127.0.0.1:5000   ^(Ctrl+C para parar^)
echo.

REM Se llama al python del venv directamente: no hace falta activarlo.
.venv\Scripts\python.exe server.py

REM Si el server se cae, la ventana no se cierra de golpe y se puede leer el error.
echo.
echo El server se detuvo.
pause
