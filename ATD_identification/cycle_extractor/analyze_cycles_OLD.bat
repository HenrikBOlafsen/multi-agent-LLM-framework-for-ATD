@echo off
setlocal

:: run with: .\analyze_cycles.bat ..\..\projects_to_analyze\customTestProject\

REM === CONFIG ===
set DEPENDS_JAR=..\depends\depends.jar
set OUTPUT_DIR=..\output

REM === Check input argument ===
if "%~1"=="" (
    echo Please provide the project path!
    echo Usage: analyze_cycles.bat path\to\project
    exit /b 1
)

set PROJECT_PATH=%~1
:: Remove trailing backslash if present
if "%PROJECT_PATH:~-1%"=="\" set PROJECT_PATH=%PROJECT_PATH:~0,-1%

set MOD_SDSM=%OUTPUT_DIR%\result-modules-sdsm.json
set FUNC_SDSM=%OUTPUT_DIR%\result-functions-sdsm.json

REM === Create output folder if it doesn't exist ===
if not exist %OUTPUT_DIR% (
    mkdir %OUTPUT_DIR%
)

echo Analyzing project: %PROJECT_PATH%

REM === Step 1: Run Depends (module-level) ===
echo Running Depends (module-level)...
java -Xmx8g -jar %DEPENDS_JAR% python "%PROJECT_PATH%" %MOD_SDSM% --format=json --granularity=file --detail

REM === Step 2: Run Depends (function-level) ===
echo Running Depends (function-level)...
java -Xmx8g -jar %DEPENDS_JAR% python "%PROJECT_PATH%" %FUNC_SDSM% --format=json --granularity=method --detail

REM === Step 3: Parse module-level cycles ===
echo Parsing module-level cycles...
python parse_module_cycles.py %MOD_SDSM%-file.json %OUTPUT_DIR%\module_cycles.json

REM === Step 4: Parse function-level cycles ===
echo Parsing function-level cycles...
python parse_function_cycles.py %FUNC_SDSM%-method.json %OUTPUT_DIR%\function_cycles.json

REM === Step 5: Compute global metrics ===
echo Computing global metrics...
python compute_global_metrics.py %MOD_SDSM%-file.json %FUNC_SDSM%-method.json %OUTPUT_DIR%\scc_metrics.json

REM === Step 6: Merge both into one ===
echo Merging into final cycles.json...
python merge_cycles.py %OUTPUT_DIR%\module_cycles.json %OUTPUT_DIR%\function_cycles.json %OUTPUT_DIR%\scc_metrics.json %OUTPUT_DIR%\cycles.json

echo All cycles saved to: %OUTPUT_DIR%\cycles.json

endlocal
