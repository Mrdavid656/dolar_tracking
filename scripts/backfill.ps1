# Backs up GitHub's scheduler from this computer: takes the reading itself when
# GitHub has not, and otherwise fills in the sources GitHub's servers could not reach.
# Meant to be run by the scheduled task created by register_backfill_task.ps1,
# inside a clone of the repository that is used for nothing else.
#
# The task starts it once per reading. It stops as soon as the reading is complete
# and published; only when something is still missing does it wait and try again.

$repository = Split-Path -Parent $PSScriptRoot
$log = Join-Path $repository "backfill.log"
$attempts = 6        # the first one and five retries: 100 minutes in all
$retryMinutes = 20
$incomplete = 2      # exit status of dolar_market.backfill while sources are missing

function Write-Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message" | Out-File -FilePath $log -Append -Encoding utf8
}

# One pass. True when the latest reading ended up complete and published.
function Invoke-Attempt {
    git pull --rebase --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Log "git pull failed"; return $false }

    # No reading in the last three hours means GitHub's scheduled run never came.
    $output = python -m dolar_market.scrape --if-older-than 180
    if ($LASTEXITCODE -ne 0) { Write-Log "reading failed: $output"; return $false }
    $tookReading = [bool]($output -match "sources saved")
    if ($tookReading) { Write-Log ($output -join " | ") }

    $output = python -m dolar_market.backfill
    $status = $LASTEXITCODE
    if ($status -notin 0, $incomplete) { Write-Log "backfill failed: $output"; return $false }
    Write-Log ($output -join " | ")

    git add data/rates.csv | Out-Null
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        $message = if ($tookReading) { "Rates $(Get-Date -Format 'yyyy-MM-dd HH:mm') (backup reading)" } else { "Backfill sources unreachable from GitHub" }
        git commit --quiet -m $message | Out-Null
    }

    # Also covers a commit left behind by an earlier push that failed.
    if ([int](git rev-list --count '@{u}..HEAD') -gt 0) {
        git push --quiet | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Log "git push failed"; return $false }
        Write-Log $(if ($tookReading) { "pushed a backup reading" } else { "pushed backfilled rows" })
    }
    return $status -eq 0
}

Set-Location $repository
$env:PYTHONIOENCODING = "utf-8"

foreach ($attempt in 1..$attempts) {
    if (Invoke-Attempt) { exit 0 }
    if ($attempt -lt $attempts) {
        Write-Log "attempt $attempt of $attempts did not finish; trying again in $retryMinutes minutes"
        Start-Sleep -Seconds ($retryMinutes * 60)
    }
}
Write-Log "gave up after $attempts attempts"
exit 1
