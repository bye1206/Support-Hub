namespace GetGroupBoxMember.Services;

public static class ADAuditLogger
{
    private static readonly string LogPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "GetGroupBoxMember", "logs", "audit.log");
    private static readonly object _lock = new();

    public static void Log(string operation, string targetDN, string operatorName,
                           bool success, string message, string? errorCode = null)
    {
        var entry = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] " +
                    $"OP={operation} TARGET={targetDN} " +
                    $"OPERATOR={operatorName} " +
                    $"RESULT={(success ? "SUCCESS" : "FAIL")} " +
                    $"CODE={errorCode ?? "N/A"} MSG={message}";
        try { lock (_lock) { File.AppendAllText(LogPath, entry + Environment.NewLine); } }
        catch { }
    }
}
