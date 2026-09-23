@echo off
rem ============================================================
rem  ConcorsiRadar - run settimanale (FP Formazione)
rem  Doppio clic: scarica i bandi, li classifica e produce in
rem  output\ il JSON da importare nel FP Gestionale
rem  (Applicativi -> Radar Concorsi -> Importa JSON).
rem ============================================================
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -m radar.run weekly
) else (
  python -m radar.run weekly
)
echo.
echo Fatto. Il file JSON per il gestionale e' nella cartella output\
pause
