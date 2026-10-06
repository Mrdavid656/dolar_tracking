# Backs up GitHub's scheduler for the daily email from this computer: starts the
# "Daily email" workflow when today's email has not gone out yet.
# Meant to be run by the scheduled task created by register_backup_tasks.ps1.
#
# It only starts the workflow: the email is still built and sent on GitHub, where
# the credentials live. The workflow keeps a marker per day, so this script does
# nothing once the email went out, and a scheduled run that arrives after this one
# sends nothing either.
#
# It waits for a recent reading to be published, because the workflow refuses to
# send stale prices. Unlike backfill.ps1 it only asks GitHub and never touches the
# clone's files: both may be running at once when the computer is switched on late.
# Needs the GitHub CLI (gh) signed in, and this computer's clock on Bolivia time.

$repository = Split-Path -Parent $PSScriptRoot
$log = Join-Path $repository "email_backup.log"
$attempts = 10       # the first one and nine retries: 90 minutes in all
$retryMinutes = 10
$maxReadingAge = New-TimeSpan -Hours 5  # the workflow's own limit is six; leave it room

function Write-Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message" | Out-File -FilePath $log -Append -Encoding utf8
}

# One pass. True when there is nothing left to do today.
function Invoke-Attempt {
    $today = Get-Date -Format 'yyyy-MM-dd'
    $markers = gh cache list --key "email-sent-$today" --json key --jq length
    if ($LASTEXITCODE -ne 0) { Write-Log "could not ask GitHub for today's marker"; return $false }
    if ([int]$markers -gt 0) { Write-Log "today's email already went out; nothing to do"; return $true }

    $rows = gh api -H "Accept: application/vnd.github.raw" "repos/{owner}/{repo}/contents/data/rates.csv"
    if ($LASTEXITCODE -ne 0) { Write-Log "could not read the published dataset"; return $false }
    $timestamp = (($rows | Where-Object { $_ } | Select-Object -Last 1) -split ",")[0]
    $age = [datetimeoffset]::Now - [datetimeoffset]::Parse($timestamp, [cultureinfo]::InvariantCulture)
    if ($age -gt $maxReadingAge) { Write-Log "latest published reading ($timestamp) is too old to send"; return $false }

    gh workflow run email.yml | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Log "could not start the email workflow"; return $false }
    Write-Log "started the email workflow with reading $timestamp"
    return $true
}

Set-Location $repository

foreach ($attempt in 1..$attempts) {
    if (Invoke-Attempt) { exit 0 }
    if ($attempt -lt $attempts) {
        Write-Log "attempt $attempt of $attempts did not finish; trying again in $retryMinutes minutes"
        Start-Sleep -Seconds ($retryMinutes * 60)
    }
}
Write-Log "gave up after $attempts attempts"
exit 1
