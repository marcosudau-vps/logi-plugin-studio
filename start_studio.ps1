$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python .\tools\run_studio.py @args
exit $LASTEXITCODE
