$projectDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
Set-Location -Path $projectDir

Write-Host "=========================================================="
Write-Host " Running Automated Stock Analysis Daily Sync Task "
Write-Host "=========================================================="

# 1. Pull latest delta Parquet files from GitHub
git pull origin main

# 2. Sync unmerged Parquet files into local DuckDB database
python -m src.cli sync-delta --deltas-dir data/daily_deltas

Write-Host "Sync process complete."
