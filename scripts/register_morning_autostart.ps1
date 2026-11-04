# Windows Görev Zamanlayıcısı: VİOP Otonom Sabah Başlatma Servisi
# Her iş günü sabah 08:25'te seans öncesi sistemi otomatik olarak başlatır.

$TaskName = "VIOP_Otonom_Sabah_Baslat"
$BatPath = "c:\Users\alper\Desktop\VİOP\BASLAT_TERMINAL.bat"
$WorkingDir = "c:\Users\alper\Desktop\VİOP"

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatPath`"" -WorkingDirectory $WorkingDir
$Trigger = New-ScheduledTaskTrigger -Daily -At "08:25"
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force
    Write-Host "[BAŞARILI] Windows Görev Zamanlayıcısı görevini oluşturdu: $TaskName (Her sabah 08:25)"
} catch {
    Write-Warning "[UYARI] Görev kaydedilirken hata oluştu: $_"
}
