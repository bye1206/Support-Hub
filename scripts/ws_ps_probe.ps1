$c = New-Object System.Net.WebSockets.ClientWebSocket
$ct = [System.Threading.CancellationToken]::None
$c.ConnectAsync([Uri]"ws://127.0.0.1:5173/ws?token=CuPCK58QaBQoqE3aI4k822uLqnqjaGYzIODbuZ0PFpU", $ct).Wait()
Write-Host "CONNECTED state=$($c.State)"
$buf = New-Object byte[] 65536
$seg = [ArraySegment[byte]]::new($buf)
$t = $c.ReceiveAsync($seg, $ct)
$t.Wait(8000) | Out-Null
if ($t.IsCompleted) {
  $n = $t.Result.Count
  Write-Host "FRAME: $([System.Text.Encoding]::UTF8.GetString($buf, 0, $n))"
} else { Write-Host "NO HANDSHAKE FRAME in 8s" }