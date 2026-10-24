# читает .env и задаёт переменные, затем запускает PocketBase
Get-Content .env | Where-Object { $_ -match '^\s*[A-Za-z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
}
$env:BACKEND_URL = "http://127.0.0.1:8000"   # локально, без Docker
./pocketbase.exe serve