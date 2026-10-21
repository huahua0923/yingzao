# Diagnostic only: launch SU once, report whether it stays alive. ASCII only (PS 5.1 + no BOM).
param([string]$Skp, [string]$Rb)
$exe = 'C:\Program Files\SketchUp\SketchUp 2023\SketchUp.exe'
$p = Start-Process -FilePath $exe -ArgumentList @($Skp, '-RubyStartup', $Rb) -PassThru
Write-Output ("START pid=" + $p.Id + " skp=" + (Split-Path -Leaf $Skp))
for ($i = 1; $i -le 8; $i++) {
    Start-Sleep -Seconds 3
    $alive = $null -ne (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)
    $all = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like '*sketchup*' })
    $titles = @($all | ForEach-Object { $_.MainWindowTitle } | Where-Object { $_ })
    Write-Output ("t=" + ($i * 3) + "s alive=" + $alive + " n_su=" + $all.Count + " titles=" + ($titles -join '|'))
    if (-not $alive -and $all.Count -eq 0) { break }
}
try {
    $p.Refresh()
    $code = if ($p.HasExited) { $p.ExitCode } else { 'still-running' }
    Write-Output ("EXITCODE " + $code)
} catch { Write-Output "EXITCODE N/A" }
