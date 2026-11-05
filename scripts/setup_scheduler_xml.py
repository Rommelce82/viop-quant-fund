import os
import subprocess

xml_content = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <URI>\\VIOP_Otonom_Sabah_Baslat</URI>
    <Description>VIOP Otonom Canli Operasyon Sabah Baslatici</Description>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <WakeToRun>true</WakeToRun>
    <IdleSettings>
      <Duration>PT10M</Duration>
      <WaitTimeout>PT1H</WaitTimeout>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
  </Settings>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-11-05T08:25:00+03:00</StartBoundary>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c "c:\\Users\\alper\\Desktop\\VİOP\\BASLAT_TERMINAL.bat"</Arguments>
      <WorkingDirectory>c:\\Users\\alper\\Desktop\\VİOP</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

xml_path = os.path.join(os.path.dirname(__file__), "task_temp.xml")
with open(xml_path, "w", encoding="utf-16") as f:
    f.write(xml_content)

res = subprocess.run(["schtasks", "/create", "/tn", "VIOP_Otonom_Sabah_Baslat", "/xml", xml_path, "/f"], capture_output=True, text=True)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)

if os.path.exists(xml_path):
    os.remove(xml_path)
