# Create a Python virtual environment named "venv"
python -m venv venv

# Activate the virtual environment
& .\venv\Scripts\Activate.ps1

# Upgrade pip to the latest version
python -m pip install --upgrade pip

# Install required packages from requirements.txt
pip install -r requirements.txt

Write-Host ""
Write-Host "Virtual environment setup complete and dependencies installed."
Write-Host "To activate the virtual environment later, run:"
Write-Host "    .\venv\Scripts\Activate.ps1"
