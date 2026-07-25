Set objShell = CreateObject("WScript.Shell")
objShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""C:\Users\ike03\Desktop\code\ai_stock\nasdaq_monitor_watchdog.ps1""", 0, False
