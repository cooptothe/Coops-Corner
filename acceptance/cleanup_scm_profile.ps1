# Cleanup-only recovery for a completed host test whose profile deletion hit 32.
# No service installation, credential reset, hive unload, process kill or reboot.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ReportPath,
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this cleanup helper in Administrator PowerShell.'
}
$resolvedReport = (Resolve-Path -LiteralPath $ReportPath).Path
$report = Get-Content -LiteralPath $resolvedReport -Raw | ConvertFrom-Json
if ($report.format -notin @('corner.installed-host-acceptance/1', 'corner.credential-rotation-acceptance/1') -or
    $report.status -ne 'failed_cleanup_required' -or
    $report.account -cnotmatch '^cah([0-9a-f]{12})$') {
    throw 'Not a recognized disposable host-acceptance cleanup report.'
}
$suffix = $Matches[1]
$expectedStage = Join-Path $env:ProgramData ('CornerHostAcceptance_' + $suffix)
$expectedReport = Join-Path $expectedStage 'report.json'
if ($resolvedReport -ine $expectedReport -or $report.stage -ine $expectedStage -or
    $report.service -cne ('CornerHost' + $suffix) -or
    $report.cleanup.service -ne 'removed' -or $report.cleanup.database_roles -ne 'removed' -or
    $report.cleanup.windows_account_profile_credential.operation -ne 'DeleteTestProfile' -or
    $report.cleanup.windows_account_profile_credential.code -ne 32) {
    throw 'Report does not match this narrowly scoped profile-cleanup operation.'
}
$requiredChecks = @('repeat_scm_graceful_stop_start', 'scm_drains_active_completion',
    'scm_force_stop_rollback_and_frozen_reclaim', 'scm_supervisor_restart_and_exactly_once_recovery',
    'retained_evidence_has_no_test_passwords')
if ($report.format -eq 'corner.credential-rotation-acceptance/1') {
    $requiredChecks = @('initial_vault_credential_passes_readiness',
        'service_stopped_with_frozen_command_preserved', 'same_login_role_memberships_and_privileges',
        'old_secret_rejected_on_new_connections', 'old_authenticated_session_survives_password_change',
        'exact_old_session_terminated_and_absent', 'stale_vault_fails_readiness_without_claiming',
        'same_config_authority_and_vault_target', 'new_vault_credential_passes_readiness',
        'frozen_command_and_domain_identity_preserved', 'retained_evidence_has_no_test_passwords')
}
foreach ($check in $requiredChecks) {
    if ($report.checks.$check -ne 'passed') { throw 'Host checks did not all pass; inspect before cleanup.' }
}
$sids = @($report.processes | ForEach-Object { $_.sid } | Sort-Object -Unique)
if ($sids.Count -ne 1 -or $sids[0] -notmatch '^S-1-5-21-\d+-\d+-\d+-\d+$') {
    throw 'No unambiguous test-account SID in retained evidence.'
}
$testSid = [string]$sids[0]
$accountName = [string]$report.account
$serviceName = [string]$report.service
if (Get-CimInstance Win32_Service -Filter "Name='$serviceName'") {
    throw 'Test service still exists. Refusing profile/account deletion.'
}
$testUser = @(Get-LocalUser | Where-Object { $_.Name -ceq $accountName })
if ($testUser.Count -gt 1 -or ($testUser.Count -eq 1 -and $testUser[0].SID.Value -ne $testSid)) {
    throw 'Account name/SID mismatch. Refusing deletion.'
}
$profile = @(Get-CimInstance Win32_UserProfile -Filter "SID='$testSid'")
if ($profile.Count -gt 1) { throw 'Ambiguous profile.' }
if ($profile.Count -eq 1) {
    $profilePath = [IO.Path]::GetFullPath([string]$profile[0].LocalPath)
    if ($profile[0].Special -or [IO.Path]::GetFileName($profilePath.TrimEnd('\')) -cne $accountName) {
        throw 'Unexpected profile path/type. Refusing deletion.'
    }
    if ($profile[0].Loaded) {
        throw 'Test profile is still loaded. Save your work, restart Windows normally, then run this helper again. Do not force-unload it.'
    }
}
if (-not $Execute) {
    [pscustomobject]@{mode='read_only'; account=$accountName; sid=$testSid;
        profile_present=($profile.Count -eq 1); account_present=($testUser.Count -eq 1);
        ready_for_cleanup=$true} | ConvertTo-Json
    return
}
if ($profile.Count -eq 1) {
    # Use Windows profile management, never recursive filesystem deletion.
    $profile[0] | Remove-CimInstance
}
if (Get-CimInstance Win32_UserProfile -Filter "SID='$testSid'") {
    throw 'Profile remains registered; account deletion not attempted.'
}
if ($profile.Count -eq 1 -and (Test-Path -LiteralPath $profilePath)) {
    throw 'Profile files remain. Do not force-delete; inspect before removing the account.'
}
# Recheck SID immediately before deletion; never remove by name alone.
$remainingUser = @(Get-LocalUser | Where-Object { $_.Name -ceq $accountName })
if ($remainingUser.Count -eq 1) {
    if ($remainingUser[0].SID.Value -ne $testSid) { throw 'Account identity changed.' }
    Remove-LocalUser -SID $remainingUser[0].SID
}
if (Get-LocalUser | Where-Object { $_.SID.Value -eq $testSid }) { throw 'Test account still exists.' }
$receipt = [pscustomobject]@{
    format='corner.host-cleanup/1'; status='cleanup_complete';
    checked_at=[DateTime]::UtcNow.ToString('o'); original_report=$resolvedReport;
    original_report_sha256=(Get-FileHash -LiteralPath $resolvedReport -Algorithm SHA256).Hash.ToLowerInvariant();
    service=$serviceName; account=$accountName; sid=$testSid;
    service_absent=$true; profile_absent=$true; account_absent=$true;
    evidence_directory_retained=$expectedStage
}
$receiptPath = Join-Path $expectedStage ('cleanup-' + [Guid]::NewGuid().ToString('N') + '.json')
$receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json
Write-Output ('Cleanup receipt retained: ' + $receiptPath)
