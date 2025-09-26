$ErrorActionPreference = "Stop"
$uri = "http://127.0.0.1:8787/tasks/send-reminders?look_back_minutes=15"
$headers = @{ Authorization="Bearer changeme-super-long"; "X-API-Key"="devkey" }
Invoke-RestMethod -Method POST -Uri $uri -Headers $headers | Out-Null
