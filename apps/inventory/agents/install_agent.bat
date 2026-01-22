@echo off
setlocal EnableDelayedExpansion

set "AGENT_DIR=C:\Apps\TI-Agent"
set "SERVER=http://192.168.100.247:5001"
set "NSSM_URL=https://nssm.cc/release/nssm-2.24.zip"
set "AGENT_PS=%AGENT_DIR%\agent.ps1"
set "NSSM=%AGENT_DIR%\nssm.exe"

echo.
echo [TI Manager] Instalando agente nas maquinas...
echo.

:: Criar pasta
if not exist "%AGENT_DIR%" mkdir "%AGENT_DIR%"

:: Baixar NSSM
if not exist "%NSSM%" (
    echo Baixando NSSM...
    powershell -Command "Invoke-WebRequest -Uri '%NSSM_URL%' -OutFile '%AGENT_DIR%\nssm.zip'" >nul 2>&1
    powershell -Command "Expand-Archive -Path '%AGENT_DIR%\nssm.zip' -DestinationPath '%AGENT_DIR%' -Force" >nul 2>&1
    move "%AGENT_DIR%\nssm-2.24\win64\nssm.exe" "%AGENT_DIR%\" >nul 2>&1
    rd /s /q "%AGENT_DIR%\nssm-2.24" >nul 2>&1
    del "%AGENT_DIR%\nssm.zip" >nul 2>&1
)

:: Baixar agente
echo Baixando agente atualizado...
powershell -Command "Invoke-WebRequest -Uri '%SERVER%/api/agent/download/' -OutFile '%AGENT_PS%' -UseBasicParsing" >nul 2>&1

:: Instalar serviço
echo Instalando servico TI-Agent...
"%NSSM%" install "TI-Agent" powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File "%AGENT_PS%" >nul
REM Diretório de trabalho (MUITO IMPORTANTE)
"%NSSM%" set "TI-Agent" AppDirectory "%AGENT_DIR%" >nul
"%NSSM%" set "TI-Agent" AppRestartDelay 5000 >nul
"%NSSM%" start "TI-Agent" >nul

echo.
echo [OK] Agente instalado com sucesso!
echo Diretorio: %AGENT_DIR%
echo Servico: TI-Agent
echo Atualizacoes: Automaticas
echo.
pause