#!/bin/bash

# PDFAnalyzer - Full Execution Pipeline (Ubuntu/Linux version)
# This script runs all analysis methods and LaTeX generation scripts in series.

# Adjust these paths as needed for your Ubuntu environment
SOURCE_FOLDER="../JCC-2026a/Standards"
KEYWORDS_JSON="cloud.json"

# Colors for output
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${CYAN}==========================================================${NC}"
echo -e "${CYAN}Starting PDFAnalyzer Full Pipeline${NC}"
echo -e "${CYAN}==========================================================${NC}"

# 1. Method 1: Granular Analysis (Snippet-based)
echo -e "\n${YELLOW}[1/5] Running Method 1: Granular Analysis...${NC}"
python3 main.py "$SOURCE_FOLDER" 0 5 "$KEYWORDS_JSON"

# 2. Method 2: Full-Context Analysis
echo -e "\n${YELLOW}[2/5] Running Method 2: Full-Context Analysis...${NC}"
python3 full_pdf_analyzer.py --source "$SOURCE_FOLDER" --keywords "$KEYWORDS_JSON" --output "$SOURCE_FOLDER"

# 3. Generate Keyword Occurrences Tables
echo -e "\n${YELLOW}[3/5] Generating Keyword Occurrences Tables...${NC}"
python3 generate_occurrences.py "$SOURCE_FOLDER" "$KEYWORDS_JSON"

# 4. Generate Cost and Token Summary Tables
echo -e "\n${YELLOW}[4/5] Generating Cost and Token Summary Tables...${NC}"
python3 generate_cost_summary.py "$SOURCE_FOLDER"

# 5. Generate Final Comparison Notes Table
echo -e "\n${YELLOW}[5/5] Generating Final Comparison Notes Table...${NC}"
python3 generate_notes_table.py "$SOURCE_FOLDER" "$KEYWORDS_JSON"

echo -e "\n${GREEN}==========================================================${NC}"
echo -e "${GREEN}Pipeline Completed Successfully!${NC}"
echo -e "${GREEN}All LaTeX tables are available in: $SOURCE_FOLDER${NC}"
echo -e "${GREEN}==========================================================${NC}"