@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

if not exist "backups" mkdir "backups"

for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  if not "%%A"=="" (
    if not "%%A:~0,1%%"=="#" (
      set "%%A=%%B"
    )
  )
)

if "%POSTGRES_USER%"=="" set "POSTGRES_USER=shopbot"
if "%POSTGRES_DB%"=="" set "POSTGRES_DB=shopbot"
if "%POSTGRES_PASSWORD%"=="" set "POSTGRES_PASSWORD=shopbot_secret"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set TS=%%I
set "BACKUP_FILE=backups\shopbot-%TS%.sql"

echo [1/3] Dang tao backup vao %BACKUP_FILE%

docker compose ps db >nul 2>&1
if %errorlevel%==0 (
  echo [2/3] Phat hien docker compose service db. Dang backup tu container...
  docker compose exec -T db pg_dump -U "%POSTGRES_USER%" -d "%POSTGRES_DB%" > "%BACKUP_FILE%"
) else (
  echo [2/3] Khong thay docker db. Thu backup bang pg_dump local...
  set "PGPASSWORD=%POSTGRES_PASSWORD%"
  pg_dump -h localhost -U "%POSTGRES_USER%" -d "%POSTGRES_DB%" > "%BACKUP_FILE%"
)

if errorlevel 1 (
  echo [LOI] Backup that bai. Hay kiem tra docker compose db hoac cai dat pg_dump local.
  if exist "%BACKUP_FILE%" del "%BACKUP_FILE%"
  exit /b 1
)

echo [3/3] Backup thanh cong: %BACKUP_FILE%
echo Goi y: copy file nay sang o khac hoac cloud de an toan hon.
exit /b 0
