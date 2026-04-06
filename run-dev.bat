@echo off
setlocal

echo.
echo  ====================================
echo   BaryonRunner - Dev Build
echo  ====================================
echo.

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Please start Docker and retry.
    pause
    exit /b 1
)

echo [1/2] Building image locally...
docker compose -f docker-compose.dev.yml build
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo [2/2] Starting BaryonRunner...
echo.
echo   GUI  ^>  http://localhost:8082
echo.

docker rm -f baryonrunner >nul 2>&1
docker run --rm --name baryonrunner --privileged --cgroupns=host -p 8082:8082 baryonrunner
pause
