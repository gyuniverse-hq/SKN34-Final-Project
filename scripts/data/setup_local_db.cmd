@echo off
rem One-command local DB setup for the VISHUE team. See README_TEAM_SETUP.md.
rem
rem   scripts\data\setup_local_db.cmd <path-to-dump>
rem
rem Runs steps 2 to 7 of the guide: starts the postgres container, installs
rem pg_trgm, restores the dump, creates the AI-Hub tables and verifies the
rem result. AI-Hub data is loaded separately with scripts\data\aihub\load_all.py.
setlocal

set "DUMP=%~1"
if "%DUMP%"=="" goto usage
if not exist "%DUMP%" (
  echo [ERROR] Dump file not found: %DUMP%
  exit /b 1
)

pushd "%~dp0..\.."
set "COMPOSE=infra/compose/compose.yaml"
rem A machine whose Docker cannot run the alpine postgres image keeps a
rem local override next to compose.yaml. Use it whenever it is there.
set "CF=-f %COMPOSE%"
if exist "infra\compose\compose.local.yaml" set "CF=-f %COMPOSE% -f infra/compose/compose.local.yaml"
set "PSQL=docker compose %CF% exec -T postgres psql -P pager=off -q -U vishue"
set "LOG=%TEMP%\vishue_setup.txt"

echo [1/7] Checking prerequisites
where docker >nul 2>&1 || (echo [ERROR] docker was not found on PATH. & goto fail)
where uv >nul 2>&1 || (echo [ERROR] uv was not found on PATH. & goto fail)

echo [2/7] Preparing env files
if not exist ".env" copy ".env.example" ".env" >nul
if not exist "backend\api\.env" copy "backend\api\.env.example" "backend\api\.env" >nul

echo [3/7] Starting the postgres container
docker compose %CF% --env-file .env up -d postgres || goto fail

echo [4/7] Waiting for postgres to accept connections
set /a TRIES=0
:waitdb
docker compose %CF% exec -T postgres pg_isready -U vishue -d vishue_db > "%LOG%" 2>&1 <nul
if not errorlevel 1 goto dbready
set /a TRIES+=1
if %TRIES% geq 45 goto failwait
rem ping instead of timeout: timeout fails when stdin is redirected.
ping -n 3 127.0.0.1 >nul
goto waitdb
:dbready

for /f "usebackq delims=" %%c in (`%PSQL% -d vishue_db -t -A -c "select count(*) from information_schema.tables where table_schema='public'" 2^>nul ^<nul`) do set "TABLES=%%c"
if not "%TABLES%"=="0" (
  echo [ERROR] vishue_db already has %TABLES% tables, so the restore would clash.
  echo         If it is already set up, you are done. To wipe it and start over:
  echo             docker compose %CF% exec postgres psql -P pager=off -U vishue -d vishue_db -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  goto fail
)

echo [5/7] Installing the pg_trgm extension
%PSQL% -d vishue_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" <nul || goto fail

echo [6/7] Restoring the dump
docker compose %CF% cp "%DUMP%" postgres:/tmp/team.dump || goto fail
docker compose %CF% exec -T postgres pg_restore -U vishue -d vishue_db --no-owner --no-privileges /tmp/team.dump <nul
if errorlevel 1 echo [WARN] pg_restore reported errors. Step 7 decides whether the data is complete.
docker compose %CF% exec -T postgres rm -f /tmp/team.dump >nul 2>&1 <nul

echo [7/7] Creating the AI-Hub tables and verifying
echo       The first run also installs python packages. This can take a few minutes.
pushd backend\api
uv run alembic stamp 0013 || (popd & goto fail)
uv run alembic upgrade head || (popd & goto fail)
uv run alembic check || (popd & goto fail)
popd

docker compose %CF% exec -T postgres psql -P pager=off -v ON_ERROR_STOP=1 -U vishue -d vishue_db < scripts\data\verify_local_db.sql > "%LOG%" 2>&1
type "%LOG%"
findstr /c:"MISMATCH" /c:"ERROR" "%LOG%" >nul && goto failverify

echo.
echo Done. vishue_db is ready.
echo Start the stack with:
echo     docker compose %CF% --env-file .env up -d --build
echo AI-Hub data, if you need it, is loaded separately. See README_TEAM_SETUP.md.
popd
exit /b 0

:usage
echo Usage: scripts\data\setup_local_db.cmd ^<path-to-dump^>
echo Example: scripts\data\setup_local_db.cmd C:\Downloads\vishue_db_20261104.dump
exit /b 2

:failwait
echo [ERROR] postgres did not become ready within 90 seconds. Last error:
if exist "%LOG%" type "%LOG%"
echo.
echo         If this machine had an older setup, the database is probably still
echo         named "vishue". Rename it and run this again:
echo             docker compose %CF% exec postgres psql -P pager=off -U vishue -d postgres -c "ALTER DATABASE vishue RENAME TO vishue_db;"
goto fail

:failverify
echo.
echo [ERROR] Verification failed. The numbers above do not match the expected ones.
echo         Full output: %LOG%
goto fail

:fail
echo.
echo Setup stopped. Nothing further was changed.
popd
exit /b 1
