namespace GetGroupBoxMember.Models;

public class ADOperationResult
{
    public bool Success { get; init; }
    public string Message { get; init; } = string.Empty;
    public string? ErrorCode { get; init; }
    public DateTime Timestamp { get; init; } = DateTime.Now;

    public static ADOperationResult Ok(string msg = "Операция выполнена")
        => new() { Success = true, Message = msg };
    public static ADOperationResult Fail(string msg, string? code = null)
        => new() { Success = false, Message = msg, ErrorCode = code };
}

public record PasswordStatusInfo(
    DateTime? PasswordLastSet,
    DateTime? PasswordExpiry,
    bool PasswordNeverExpires,
    bool PasswordRequireChange);

public record AccountLockStatusInfo(bool LockedOut, bool Enabled);
