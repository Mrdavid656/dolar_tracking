# Registers two Windows scheduled tasks that back up GitHub's scheduler from this
# computer:
#   - one takes the reading when GitHub has not, and fills in the sources GitHub's
#     servers cannot reach (backfill.ps1);
#   - one starts the daily email when GitHub has not sent it (email_backup.ps1).
#
# Usage (from PowerShell):  .\scripts\register_backup_tasks.ps1
# To remove them:           Unregister-ScheduledTask -TaskName DolarTrackingBackfill
#                           Unregister-ScheduledTask -TaskName DolarTrackingEmail
#
# The tasks work in their own clone of the repository so they never touch a working
# copy you are editing. Readings are taken at 07:07 and 19:07 Bolivia time;
# the reading task starts once at 20 past, and backfill.ps1 itself retries every 20
# minutes for 100 minutes while the reading is incomplete. The email goes out at
# 08:07; its task starts at 08:20 and email_backup.ps1 retries every 10 minutes for
# 90 minutes while no recent reading is published. This computer's clock must be on
# Bolivia time, and the email task needs the GitHub CLI (gh) signed in.

param(
    [string]$RepositoryUrl = "https://github.com/Mrdavid656/dolar_tracking.git",
    [string]$Directory = (Join-Path $env:LOCALAPPDATA "dolar_tracking"),
    [string]$TaskName = "DolarTrackingBackfill",
    [string]$EmailTaskName = "DolarTrackingEmail"
)

if (-not (Test-Path (Join-Path $Directory ".git"))) {
    git clone --quiet $RepositoryUrl $Directory
    if ($LASTEXITCODE -ne 0) { throw "Could not clone $RepositoryUrl" }
}

function New-ScriptAction($name) {
    $script = Join-Path $Directory "scripts\$name"
    New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)  # room for every retry

$triggers = "07:20", "19:20" | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }

Register-ScheduledTask -TaskName $TaskName -Action (New-ScriptAction "backfill.ps1") -Trigger $triggers `
    -Settings $settings -Description "Backfills dollar rates that GitHub's servers cannot reach." -Force | Out-Null

# Registering must not send an email by itself: when today's 08:20 has passed, the
# first start is tomorrow's, so Windows does not see a missed start to catch up on.
$emailStart = (Get-Date).Date.AddHours(8).AddMinutes(20)
if ($emailStart -lt (Get-Date)) { $emailStart = $emailStart.AddDays(1) }

Register-ScheduledTask -TaskName $EmailTaskName -Action (New-ScriptAction "email_backup.ps1") `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $emailStart) -Settings $settings `
    -Description "Starts the daily dollar email when GitHub's scheduler has not." -Force | Out-Null

Write-Output "Tasks '$TaskName' and '$EmailTaskName' registered. They run from $Directory and log to backfill.log and email_backup.log there."
