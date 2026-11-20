$c = New-Object System.Net.WebSockets.ClientWebSocket
$ct = [System.Threading.CancellationToken]::None
$c.ConnectAsync([Uri]"ws://127.0.0.1:5173/ws?token=CuPCK58QaBQoqE3aI4k822uLqnqjaGYzIODbuZ0PFpU", $ct).Wait()
$buf = New-Object byte[] 65536
$seg = [ArraySegment[byte]]::new($buf)
$frames = @()
$deadline = (Get-Date).AddSeconds(30)
$pending = $c.ReceiveAsync($seg, $ct)
while ((Get-Date) -lt $deadline) {
  if ($pending.IsCompleted) {
    $n = $pending.Result.Count
    $frames += [System.Text.Encoding]::UTF8.GetString($buf, 0, $n)
    $pending = $c.ReceiveAsync($seg, $ct)
  } else { Start-Sleep -Milliseconds 150 }
}
$c.Dispose()
$frames -join "`n" | Set-Content "E:\Opencode\support-hub\scripts\ws_frames2.log"
Write-Host "done, frames: $($frames.Count)"