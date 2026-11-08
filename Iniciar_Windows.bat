@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "RUNTIME=%~dp0runtime"
set "PYDIR=%RUNTIME%\python"
set "FFDIR=%RUNTIME%\ffmpeg"
set "MARKER=%RUNTIME%\.setup_ok"
set "PY=%PYDIR%\python.exe"

if not exist "%RUNTIME%" mkdir "%RUNTIME%"

if exist "%MARKER%" goto :run

echo ============================================================
echo   Video Magico - primeira execucao, configurando tudo...
echo   Isso so acontece uma vez. Pode levar alguns minutos.
echo   (baixando Python e FFmpeg, ambos gratuitos e oficiais)
echo ============================================================
echo.

where curl >nul 2>nul
if errorlevel 1 (
    echo ERRO: nao encontrei o "curl" neste Windows.
    echo Ele normalmente ja vem instalado no Windows 10/11.
    echo Copie esta mensagem e me avise, que eu te passo um jeito manual.
    pause
    exit /b 1
)

where tar >nul 2>nul
if errorlevel 1 (
    echo ERRO: nao encontrei o "tar" neste Windows.
    echo Copie esta mensagem e me avise, que eu te passo um jeito manual.
    pause
    exit /b 1
)

echo [1/5] Baixando Python portatil (oficial, python.org, gratuito)...
curl -L -o "%RUNTIME%\python.zip" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
if errorlevel 1 goto :fail

echo [2/5] Extraindo Python...
if not exist "%PYDIR%" mkdir "%PYDIR%"
tar -xf "%RUNTIME%\python.zip" -C "%PYDIR%"
if errorlevel 1 goto :fail

REM habilita o "site-packages" no Python portatil, pra instalar bibliotecas
> "%PYDIR%\python311._pth" (
    echo python311.zip
    echo .
    echo Lib\site-packages
    echo import site
)

echo [3/5] Instalando o gerenciador de pacotes (pip, gratuito)...
curl -L -o "%RUNTIME%\get-pip.py" "https://bootstrap.pypa.io/get-pip.py"
if errorlevel 1 goto :fail
"%PY%" "%RUNTIME%\get-pip.py" --no-warn-script-location
if errorlevel 1 goto :fail

echo [4/5] Instalando as pecas do Video Magico (todas open-source, sem custo)...
"%PY%" -m pip install --no-warn-script-location -r requirements.txt
if errorlevel 1 goto :fail

echo [5/5] Baixando o FFmpeg (gratuito, essencial pra edicao de video)...
if not exist "%FFDIR%" mkdir "%FFDIR%"
curl -L -o "%RUNTIME%\ffmpeg.zip" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
if errorlevel 1 goto :fail
tar -xf "%RUNTIME%\ffmpeg.zip" -C "%FFDIR%"
if errorlevel 1 goto :fail

echo ok> "%MARKER%"
echo.
echo Tudo pronto! Nas proximas vezes isso nao roda de novo, abre direto.
echo.

:run
REM O Python portatil (embarcado) usa um arquivo "python311._pth" que
REM restringe totalmente onde ele procura modulos - e, quando esse arquivo
REM existe, o Python IGNORA a variavel PYTHONPATH, entao so setar PYTHONPATH
REM nao resolve. Por padrao esse arquivo nao inclui a pasta do projeto (onde
REM ficam o app.py e a pasta "pipeline"), o que causa o erro
REM "No module named 'pipeline'" ao abrir. Aqui a gente regrava esse arquivo
REM toda vez que abre (rapido, so texto) garantindo que a pasta do projeto
REM esteja incluida - isso conserta sozinho instalacoes que ja foram
REM configuradas antes dessa correcao, sem precisar refazer o download.
if exist "%PYDIR%\python311._pth" (
    > "%PYDIR%\python311._pth" (
        echo python311.zip
        echo .
        echo Lib\site-packages
        echo ..\..
        echo import site
    )
)
REM (mantido como reforco extra, caso essa restricao mude em versoes futuras)
set "PYTHONPATH=%~dp0"

REM garante que pecas novas (adicionadas em atualizacoes do Video Magico,
REM tipo o importador de link do YouTube) fiquem instaladas mesmo em quem
REM ja configurou tudo antes - rapido quando ja esta tudo instalado, e se
REM nao tiver internet no momento so avisa e segue com o que ja tem.
echo Conferindo se ha pecas novas pra instalar...
"%PY%" -m pip install --no-warn-script-location -q -r requirements.txt
if errorlevel 1 (
    echo Aviso: nao consegui conferir/instalar pecas novas agora ^(sem internet?^). Seguindo com o que ja esta instalado.
)

REM acha a pasta onde o ffmpeg.exe foi extraido e coloca no PATH desta janela
set "FFBIN="
for /f "delims=" %%F in ('dir /s /b "%FFDIR%\ffmpeg.exe" 2^>nul') do set "FFBIN=%%~dpF"
if defined FFBIN set "PATH=%FFBIN%;%PATH%"

if not exist "%PY%" (
    echo ERRO: nao encontrei o Python configurado.
    echo Apague a pasta "runtime" e execute este arquivo de novo.
    pause
    exit /b 1
)

REM Ollama e so necessario pro MODO CHAT (conversar pedindo zoom, camera
REM lenta, efeitos sonoros). O modo automatico (arrastar na pasta entrada)
REM funciona sem ele. Por isso essa checagem nunca trava a abertura do app.
where ollama >nul 2>nul
if errorlevel 1 (
    echo.
    echo Aviso: nao encontrei o Ollama instalado.
    echo Ele so e necessario se voce quiser usar o MODO CHAT ^(conversar
    echo pedindo zoom, camera lenta, efeitos sonoros^). O modo automatico
    echo funciona normalmente sem ele.
    echo Pra instalar ^(gratuito^): https://ollama.com/download
    echo.
) else (
    echo Verificando o modelo de IA do Ollama ^(so baixa se ainda nao tiver^)...
    ollama pull llama3.2:3b >nul 2>nul
)

echo Iniciando o Video Magico...
echo O navegador vai abrir sozinho em alguns segundos...
echo.
"%PY%" app.py
pause
exit /b 0

:fail
echo.
echo ------------------------------------------------------------
echo Deu um erro na configuracao automatica (mensagem acima).
echo Copie o que apareceu e me manda que eu ajusto pra sua maquina.
echo ------------------------------------------------------------
pause
exit /b 1
