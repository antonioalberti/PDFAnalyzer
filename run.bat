@echo off
if "%~1"=="" (
    echo Usage: run.bat [source_folder] [start_index] [end_index] [min_representative_matches]
    echo Example: run.bat C:\Users\alberti\Documents\Artigos 0 42 100
    exit /b 1
)
if "%~2"=="" (
    echo Usage: run.bat [source_folder] [start_index] [end_index] [min_representative_matches]
    echo Example: run.bat C:\Users\alberti\Documents\Artigos 0 42 100
    exit /b 1
)
if "%~3"=="" (
    echo Usage: run.bat [source_folder] [start_index] [end_index] [min_representative_matches]
    echo Example: run.bat C:\Users\alberti\Documents\Artigos 0 42 100
    exit /b 1
)
if "%~4"=="" (
    echo Usage: run.bat [source_folder] [start_index] [end_index] [min_representative_matches]
    echo Example: run.bat C:\Users\alberti\Documents\Artigos 0 42 100
    exit /b 1
)

set SOURCE_FOLDER=%~1
if "%SOURCE_FOLDER:~-1%"=="\" (
    set SOURCE_FOLDER=%SOURCE_FOLDER:~0,-1%
)
set START_INDEX=%~2
set END_INDEX=%~3
set MIN_REPRESENTATIVE_MATCHES=%~4
set KEYWORDS_PATH=6G.json
set MODEL=openai/gpt-4.1-mini-2025-04-14
set PROMPT_APPROVAL=false

for /l %%i in (%START_INDEX%,1,%END_INDEX%) do (
    echo Processing file p%%i.pdf
    python main.py "%SOURCE_FOLDER%\p%%i.pdf" %KEYWORDS_PATH% --min-representative-matches %MIN_REPRESENTATIVE_MATCHES% --model %MODEL% --prompt-approval %PROMPT_APPROVAL% > "%SOURCE_FOLDER%\p%%i.txt"
)
echo All files processed.
