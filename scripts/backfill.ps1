# Backs up GitHub's scheduler from this computer: takes the reading itself when
# GitHub has not, and otherwise fills in the sources GitHub's servers could not reach.
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

# No reading in the last three hours means GitHub's scheduled run never came.
$output = python -m dolar_market.scrape --if-older-than 180
if ($LASTEXITCODE -ne 0) { Write-Log "reading failed: $output"; exit 1 }
$tookReading = [bool]($output -match "sources saved")
if ($tookReading) { Write-Log ($output -join " | ") }

$output = python -m dolar_market.backfill
if ($LASTEXITCODE -ne 0) { Write-Log "backfill failed: $output"; exit 1 }
Write-Log ($output -join " | ")

git add data/rates.csv
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { exit 0 }  # nothing was added

$message = if ($tookReading) { "Rates $(Get-Date -Format 'yyyy-MM-dd HH:mm') (backup reading)" } else { "Backfill sources unreachable from GitHub" }
git commit --quiet -m $message
git push --quiet
if ($LASTEXITCODE -ne 0) { Write-Log "git push failed"; exit 1 }
Write-Log $(if ($tookReading) { "pushed a backup reading" } else { "pushed backfilled rows" })
