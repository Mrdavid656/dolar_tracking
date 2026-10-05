# Fills in the sources that GitHub's servers could not reach, from this computer.
# Meant to be run by the scheduled task created by register_backfill_task.ps1,
# inside a clone of the repository that is used for nothing else.

$repository = Split-Path -Parent $PSScriptRoot
$log = Join-Path $repository "backfill.log"

function Write-Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message" | Out-File -FilePath $log -Append -Encoding utf8
}

Set-Location $repository
$env:PYTHONIOENCODING = "utf-8"

git pull --rebase --quiet
if ($LASTEXITCODE -ne 0) { Write-Log "git pull failed"; exit 1 }

$output = python -m dolar_market.backfill
if ($LASTEXITCODE -ne 0) { Write-Log "backfill failed: $output"; exit 1 }
Write-Log ($output -join " | ")

git add data/rates.csv
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { exit 0 }  # nothing was added

git commit --quiet -m "Backfill sources unreachable from GitHub"
git push --quiet
if ($LASTEXITCODE -ne 0) { Write-Log "git push failed"; exit 1 }
Write-Log "pushed backfilled rows"
