$c = New-Object System.Net.WebSockets.ClientWebSocket
$ct = [System.Threading.CancellationToken]::None
$c.ConnectAsync([Uri]"ws://127.0.0.1:5173/ws?token=CuPCK58QaBQoqE3aI4k822uLqnqjaGYzIODbuZ0PFpU", $ct).Wait()
$buf = New-Object byte[] 65536
$seg = [ArraySegment[byte]]::new($buf)
# consume "ready"
$r = $c.ReceiveAsync($seg, $ct); $r.Wait(5000) | Out-Null
Write-Host "ready received, waiting for probe event (publish via WSL redis-cli)..."
$t = $c.ReceiveAsync($seg, $ct)
$t.Wait(20000) | Out-Null
if ($t.IsCompleted -and -not $t.Result.EndOfMessage -or $t.IsCompleted) {
  $n = $t.Result.Count
  Write-Host "FRAME: $([System.Text.Encoding]::UTF8.GetString($buf, 0, $n))"
} else { Write-Host "NO EVENT in 20s" }
$c.Dispose()