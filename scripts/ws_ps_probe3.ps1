$c = New-Object System.Net.WebSockets.ClientWebSocket
$ct = [System.Threading.CancellationToken]::None
$c.ConnectAsync([Uri]"ws://127.0.0.1:5173/ws?token=CuPCK58QaBQoqE3aI4k822uLqnqjaGYzIODbuZ0PFpU", $ct).Wait()
$buf = New-Object byte[] 65536
$seg = [ArraySegment[byte]]::new($buf)
$log = @()
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
  $t = $c.ReceiveAsync($seg, $ct)
  $t.Wait(1000) | Out-Null
  if ($t.IsCompleted) {
    $n = $t.Result.Count
    $log += [System.Text.Encoding]::UTF8.GetString($buf, 0, $n)
  }
}
$c.Dispose()
$log -join "`n" | Set-Content "E:\Opencode\support-hub\scripts\ws_frames.log"
Write-Host "frames collected"