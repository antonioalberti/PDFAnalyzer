# PDFAnalyzer - Full Execution Pipeline
# This script runs all analysis methods and LaTeX generation scripts in series.

$SourceFolder = "C:\Users\Scalifax\CodeRepository\JCC-2026a\Standards"
$KeywordsJson = "cloud.json"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Starting PDFAnalyzer Full Pipeline" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Method 1: Granular Analysis (Snippet-based)
Write-Host "`n[1/5] Running Method 1: Granular Analysis..." -ForegroundColor Yellow
python main.py $SourceFolder 0 5 $KeywordsJson

# 2. Method 2: Full-Context Analysis
Write-Host "`n[2/5] Running Method 2: Full-Context Analysis..." -ForegroundColor Yellow
python full_pdf_analyzer.py --source $SourceFolder --keywords $KeywordsJson --output $SourceFolder

# 3. Generate Keyword Occurrences Tables
Write-Host "`n[3/5] Generating Keyword Occurrences Tables..." -ForegroundColor Yellow
python generate_occurrences.py $SourceFolder $KeywordsJson

# 4. Generate Cost and Token Summary Tables
Write-Host "`n[4/5] Generating Cost and Token Summary Tables..." -ForegroundColor Yellow
python generate_cost_summary.py $SourceFolder

# 5. Generate Final Comparison Notes Table
Write-Host "`n[5/5] Generating Final Comparison Notes Table..." -ForegroundColor Yellow
python generate_notes_table.py $SourceFolder $KeywordsJson

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "Pipeline Completed Successfully!" -ForegroundColor Green
Write-Host "All LaTeX tables are available in: $SourceFolder" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green