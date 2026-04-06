@echo off
setlocal

echo.
echo  ====================================
echo   BaryonRunner
echo  ====================================
echo.

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Please start Docker and retry.
    pause
    exit /b 1
)

echo [1/2] Pulling latest image...
docker pull ghcr.io/fairflow-bioinformaticsframework/baryon_gui:latest
if errorlevel 1 (
    echo [ERROR] Pull failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo [2/2] Starting BaryonRunner...
echo.
echo   GUI  ^>  http://localhost:8082
echo.

docker rm -f baryonrunner >nul 2>&1
docker run --rm --name baryonrunner --privileged --cgroupns=host -p 8082:8082 ghcr.io/fairflow-bioinformaticsframework/baryon_gui:latest
pause
