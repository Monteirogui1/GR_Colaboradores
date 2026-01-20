@echo off
setlocal EnableDelayedExpansion

:: -------------------- CONFIGURAÇÕES --------------------
set "AGENT_DIR=C:\Apps\TI-Agent"
set "AGENT_EXE=agent.exe"
set "NSSM_EXE=nssm.exe"
set "SERVICE_NAME=TI-Agent"
set "SCRIPT_DIR=%~dp0"

:: -------------------- HEADER --------------------
echo ============================================
echo  Instalador TI-Agent (.EXE) como Servico
echo ============================================

:: ---- CRIAR DIRETORIO ----
if not exist "%AGENT_DIR%" (
    md "%AGENT_DIR%"
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel criar %AGENT_DIR%
        pause
        exit /b 1
    )
    echo [OK] Criado: %AGENT_DIR%
) else (
    echo [OK] Diretorio existe: %AGENT_DIR%
)

:: ---- COPIAR EXECUTAVEL ----
echo Copiando %AGENT_EXE%...
copy /Y "%SCRIPT_DIR%%AGENT_EXE%" "%AGENT_DIR%\%AGENT_EXE%" >nul
if errorlevel 1 (
    echo [ERRO] Falha ao copiar %AGENT_EXE%
    pause
    exit /b 1
)
echo [OK] Copiado: %AGENT_EXE%

:: ---- COPIAR NSSM ----
echo Copiando %NSSM_EXE%...
copy /Y "%SCRIPT_DIR%%NSSM_EXE%" "%AGENT_DIR%\%NSSM_EXE%" >nul
if errorlevel 1 (
    echo [ERRO] Falha ao copiar %NSSM_EXE%
    pause
    exit /b 1
)
echo [OK] Copiado: %NSSM_EXE%

:: ---- REGISTRAR SERVICO ----
pushd "%AGENT_DIR%"
"%AGENT_DIR%\%NSSM_EXE%" stop "%SERVICE_NAME%" >nul 2>&1
"%AGENT_DIR%\%NSSM_EXE%" remove "%SERVICE_NAME%" confirm >nul 2>&1

echo Instalando o servico %SERVICE_NAME%...
"%AGENT_DIR%\%NSSM_EXE%" install "%SERVICE_NAME%" "%AGENT_DIR%\%AGENT_EXE%"
if errorlevel 1 (
    echo [ERRO] Falha ao instalar servico
    popd
    pause
    exit /b 1
)

"%AGENT_DIR%\%NSSM_EXE%" set "%SERVICE_NAME%" AppRestartDelay 5000 >nul
"%AGENT_DIR%\%NSSM_EXE%" set "%SERVICE_NAME%" AppStdout "%AGENT_DIR%\stdout.log" >nul
"%AGENT_DIR%\%NSSM_EXE%" set "%SERVICE_NAME%" AppStderr "%AGENT_DIR%\stderr.log" >nul

"%AGENT_DIR%\%NSSM_EXE%" start "%SERVICE_NAME%"
if errorlevel 1 (
    echo [ERRO] Falha ao iniciar servico
    popd
    pause
    exit /b 1
)

popd

echo ============================================
echo    INSTALACAO CONCLUIDA!
echo    Servico: %SERVICE_NAME% rodando.
echo    Para verificar status: sc query "%SERVICE_NAME%"
echo    Log: %AGENT_DIR%\stdout.log
echo ============================================
pause
