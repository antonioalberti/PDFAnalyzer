@echo off
setlocal enabledelayedexpansion

REM Define the PDFAnalyzer folder path
set PDF_ANALYZER_DIR=C:\Users\Scalifax\CodeRepository\PDFAnalyzer

REM Define the folder path with PDFs
set PDF_SOURCE_DIR=C:\Users\Scalifax\CodeRepository\REFSIM2026

REM Define the reference file path
set REF_JSON=%PDF_ANALYZER_DIR%\REF.json

REM Define the LLM model to use
set MODEL=gpt-4.1-mini-2025-04-14

REM Define if prompt approval is active (false for automation)
set PROMPT_APPROVAL=false

REM Define the minimum number of representative matches
set MIN_REPRESENTATIVE_MATCHES=10

REM Activate virtual environment if it exists
if exist "%PDF_ANALYZER_DIR%\venv\Scripts\activate.bat" (
    call "%PDF_ANALYZER_DIR%\venv\Scripts\activate.bat"
    echo Virtual environment activated
) else (
    echo Virtual environment not found, using default Python
)

REM Navigate to PDFAnalyzer directory
cd /d "%PDF_ANALYZER_DIR%"

echo Processing files in batches of 3...

REM Counter for processed files
set FILE_COUNT=0
set BATCH_NUM=0

REM Loop to process files in batches of 3
for /f "delims=" %%f in ('dir /b /a-d "%PDF_SOURCE_DIR%\*.pdf" ^| sort') do (
    set /a FILE_COUNT+=1
    
    if !FILE_COUNT! equ 1 (
        set /a BATCH_NUM+=1
        echo.
        echo ============================================
        echo BATCH !BATCH_NUM! - Processing 3 files:
        echo ============================================
        set START_INDEX=!FILE_COUNT!
    )
    
    echo Processing: %%f
    
    if !FILE_COUNT! equ 3 (
        set END_INDEX=!FILE_COUNT!
        
        echo Running analysis for batches !START_INDEX! to !END_INDEX!...
        python main.py "%PDF_SOURCE_DIR%" !START_INDEX! !END_INDEX! "%REF_JSON%" --model "%MODEL%" --prompt-approval %PROMPT_APPROVAL% --min-representative-matches %MIN_REPRESENTATIVE_MATCHES%
        
        echo.
        echo BATCH !BATCH_NUM! completed.
        
        set FILE_COUNT=0
    )
)

REM Process the last batch if there are remaining files
if !FILE_COUNT! gtr 0 (
    set /a BATCH_NUM+=1
    echo.
    echo ============================================
    echo BATCH !BATCH_NUM! - Processing remaining files: !FILE_COUNT!
    echo ============================================
    
    set END_INDEX=!FILE_COUNT!
    echo Running analysis for batches !START_INDEX! to !END_INDEX!...
    python main.py "%PDF_SOURCE_DIR%" !START_INDEX! !END_INDEX! "%REF_JSON%" --model "%MODEL%" --prompt-approval %PROMPT_APPROVAL% --min-representative-matches %MIN_REPRESENTATIVE_MATCHES%
    
    echo.
    echo BATCH !BATCH_NUM! completed.
)

echo.
echo ============================================
echo ALL BATCHES PROCESSED!
echo ============================================
echo.
echo Results saved in folder: %PDF_SOURCE_DIR%
echo.

endlocal
pause
