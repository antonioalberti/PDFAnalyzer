@echo off
if "%~1"=="" (
    echo Usage: run.bat [source_folder] [max_files]
    echo Example: run.bat C:\Users\alberti\Documents\Artigos 42
    exit /b 1
)
if "%~2"=="" (
    echo Usage: run.bat [source_folder] [max_files]
    echo Example: run.bat C:\Users\alberti\Documents\Artigos 42
    exit /b 1
)

set SOURCE_FOLDER=%~1
if "%SOURCE_FOLDER:~-1%"=="\" (
    set SOURCE_FOLDER=%SOURCE_FOLDER:~0,-1%
)
set MAX_FILES=%~2
set KEYWORDS_PATH=6G.json

for /l %%i in (0,1,%MAX_FILES%) do (
    echo Processing file p%%i.pdf
    python main.py "%SOURCE_FOLDER%\p%%i.pdf" %KEYWORDS_PATH% > "%SOURCE_FOLDER%\p%%i.txt"
)
echo All files processed.
