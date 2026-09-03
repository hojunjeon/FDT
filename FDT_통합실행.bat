@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "FDT_PYTHON=%~dp0.venv\Scripts\python.exe"
set "FDT_HOST=127.0.0.1"
set "FDT_PORT=8787"
set "FDT_PROBE_TIMEOUT=5"
set "FDT_LOG_DIR=%~dp0log"
if not exist "%FDT_LOG_DIR%" md "%FDT_LOG_DIR%" >nul 2>&1
for /f "delims=" %%L in ('powershell.exe -NoLogo -NoProfile -Command "Get-Date -Format yyddMM-HHmm"') do set "FDT_LOG_STAMP=%%L"
set "FDT_LOG_SUFFIX="
set /a FDT_LOG_INDEX=1 >nul
:log_path
set "FDT_LOG_FILE=%FDT_LOG_DIR%\%FDT_LOG_STAMP%%FDT_LOG_SUFFIX%.log"
if not exist "%FDT_LOG_FILE%" goto :log_ready
set "FDT_LOG_SUFFIX=-%FDT_LOG_INDEX%"
set /a FDT_LOG_INDEX+=1 >nul
goto :log_path
:log_ready
if not defined FDT_OLLAMA_URL set "FDT_OLLAMA_URL=http://127.0.0.1:11434"
if not defined FDT_LLM_MODEL set "FDT_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M"

echo ======================================================
echo   FDT 통합 실행기 - 로컬 대시보드
echo ======================================================
echo.

if not exist "%FDT_PYTHON%" (
  echo [오류] Python 가상환경을 찾을 수 없습니다:
  echo        "%FDT_PYTHON%"
  echo        먼저 .venv를 만든 뒤 다시 실행하세요.
  exit /b 1
)

call :probe_marker "http://%FDT_HOST%:%FDT_PORT%/api/health" "fdt-local-dashboard"
if not errorlevel 1 (
  echo [안내] FDT 서버가 이미 실행 중입니다. 새 서버를 띄우지 않습니다.
  start "" "http://%FDT_HOST%:%FDT_PORT%"
  exit /b 0
)

call :port_listening %FDT_PORT%
if not errorlevel 1 (
  echo [오류] 포트 %FDT_PORT%가 다른 프로세스에 의해 사용 중입니다.
  echo        기존 프로세스를 종료하지 않았습니다. 해당 프로세스를 확인한 뒤 다시 실행하세요.
  exit /b 2
)

echo [확인] Ollama 상태 확인 중...
set "FDT_PROBE_TIMEOUT=2"
call :probe_marker "http://127.0.0.1:11434/api/tags" "models"
if not errorlevel 1 goto :ollama_ready

call :port_listening 11434
if not errorlevel 1 (
  echo [경고] 11434 포트가 Ollama가 아닌 다른 프로세스에 의해 사용 중입니다.
  echo        LLM 없이 FDT template fallback으로 계속합니다.
  goto :ollama_done
)

where ollama.exe >nul 2>&1
if errorlevel 1 (
  echo [경고] Ollama를 찾지 못했습니다. LLM 없이 template fallback으로 계속합니다.
  goto :ollama_done
)

echo [안내] Ollama가 꺼져 있어 백그라운드로 시작합니다. 모델은 자동 다운로드하지 않습니다.
start "" /b ollama.exe serve >nul 2>&1
for /l %%N in (1,1,15) do (
  call :probe_marker "http://127.0.0.1:11434/api/tags" "models"
  if not errorlevel 1 goto :ollama_ready
  if not "%%N"=="15" timeout /t 1 /nobreak >nul
)
echo [경고] Ollama readiness 대기 시간이 초과되었습니다. template fallback으로 계속합니다.
goto :ollama_done

:ollama_ready
echo [확인] Ollama가 실행 중입니다.
call :ollama_model_available
if errorlevel 1 echo [경고] 모델 "%FDT_LLM_MODEL%"이 없어 template fallback으로 동작할 수 있습니다. 자동 pull은 하지 않습니다.

:ollama_done
set "FDT_PROBE_TIMEOUT=5"
echo.
echo [시작] FDT 서버: http://%FDT_HOST%:%FDT_PORT%
echo [로그] 실시간 저장: "%FDT_LOG_FILE%"
start "FDT Dashboard" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "& $env:FDT_PYTHON -m fdt.cli serve --host $env:FDT_HOST --port $env:FDT_PORT 2>&1 | Tee-Object -FilePath $env:FDT_LOG_FILE -Append"

for /l %%N in (1,1,30) do (
  call :probe_marker "http://%FDT_HOST%:%FDT_PORT%/api/health" "fdt-local-dashboard"
  if not errorlevel 1 goto :fdt_ready
  if not "%%N"=="30" timeout /t 1 /nobreak >nul
)

echo.
echo [오류] FDT 서버가 30초 안에 준비되지 않았습니다.
echo        "FDT Dashboard" 창의 서버 로그를 확인하세요. 다른 프로세스는 종료하지 않았습니다.
exit /b 3

:fdt_ready
start "" "http://%FDT_HOST%:%FDT_PORT%"
echo.
echo [완료] 대시보드를 열었습니다: http://%FDT_HOST%:%FDT_PORT%
echo [안내] 서버 로그는 "FDT Dashboard" 창과 "%FDT_LOG_FILE%"에 표시됩니다. 종료하려면 그 창을 닫으세요.
pause
exit /b 0

:probe_marker
set "FDT_PROBE_URL=%~1"
set "FDT_PROBE_MARKER=%~2"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; $url=$env:FDT_PROBE_URL; $marker=$env:FDT_PROBE_MARKER; $timeout=[int]$env:FDT_PROBE_TIMEOUT; $body=''; try { $response=Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec $timeout -ErrorAction Stop; $body=[string]$response.Content } catch { if ($_.Exception.Response) { try { $reader=New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream()); $body=$reader.ReadToEnd() } catch {} } }; if ([string]$body -and ([string]$body).IndexOf($marker,[System.StringComparison]::OrdinalIgnoreCase) -ge 0) { exit 0 }; exit 1"
exit /b %ERRORLEVEL%

:port_listening
set "FDT_CHECK_PORT=%~1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$port=[int]$env:FDT_CHECK_PORT; $listeners=[Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners(); if ($listeners | Where-Object { $_.Port -eq $port }) { exit 0 }; exit 1"
exit /b %ERRORLEVEL%

:ollama_model_available
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; $model=$env:FDT_LLM_MODEL; try { $response=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -ErrorAction Stop; $data=$response.Content | ConvertFrom-Json; if (@($data.models | ForEach-Object { [string]$_.name }) -contains $model) { exit 0 } } catch {}; exit 1"
exit /b %ERRORLEVEL%
