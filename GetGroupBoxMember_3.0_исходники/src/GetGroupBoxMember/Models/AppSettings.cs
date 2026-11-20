using System.Collections.Generic;
using System.Text.Json;
using System.IO;
using System;

namespace GetGroupBoxMember.Models;

internal static class FileLogger
{
    private static readonly string LogPath;
    private static readonly object _lock = new();

    static FileLogger()
    {
        var logDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "GetGroupBoxMember", "logs");
        if (!Directory.Exists(logDir))
            Directory.CreateDirectory(logDir);
        LogPath = Path.Combine(logDir, "ggbm.log");
    }

    public static void Log(string message)
    {
        lock (_lock)
        {
            try
            {
                var entry = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] {message}";
                File.AppendAllText(LogPath, entry + Environment.NewLine);
            }
            catch { }
        }
    }

    public static string GetLogPath() => LogPath;
}

public class AppSettings
{
    private static AppSettings? _instance;
    private static readonly object _lock = new();

    public AppTheme CurrentTheme { get; set; } = AppTheme.Dark;
    public Dictionary<string, WindowSize> WindowSizes { get; set; } = new();

    public string DefaultDC { get; set; } = string.Empty;
    public string UserLogPath { get; set; } = @"\\svm-9\scripts\UserLog";
    public bool ShowAllMemberMaillist { get; set; } = false;

    private static readonly string SettingsPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "GetGroupBoxMember",
        "settings.json");

    public AppSettings() { }

    public static AppSettings Load()
    {
        lock (_lock)
        {
            if (_instance != null)
                return _instance;

            try
            {
                if (File.Exists(SettingsPath))
                {
                    var json = File.ReadAllText(SettingsPath);
                    var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
                    _instance = JsonSerializer.Deserialize<AppSettings>(json, options);
                    if (_instance != null)
                        return _instance;
                }
            }
            catch (Exception ex)
            {
                FileLogger.Log($"[AppSettings.Load] ERROR: {ex.Message}");
            }

            _instance = new AppSettings();
            return _instance;
        }
    }

    public void Save()
    {
        lock (_lock)
        {
            try
            {
                var directory = Path.GetDirectoryName(SettingsPath);
                if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory))
                    Directory.CreateDirectory(directory);

                var options = new JsonSerializerOptions { WriteIndented = true };
                var json = JsonSerializer.Serialize(this, options);
                File.WriteAllText(SettingsPath, json);
            }
            catch (Exception ex)
            {
                FileLogger.Log($"[AppSettings.Save] ERROR: {ex.Message}");
            }
        }
    }

    public void Reload()
    {
        var loaded = Load();
        CurrentTheme = loaded.CurrentTheme;
        DefaultDC = loaded.DefaultDC;
        UserLogPath = loaded.UserLogPath;
        ShowAllMemberMaillist = loaded.ShowAllMemberMaillist;
        WindowSizes = loaded.WindowSizes;
    }
}

public class WindowSize
{
    public double Width { get; set; }
    public double Height { get; set; }
    public double? Left { get; set; }
    public double? Top { get; set; }

    public WindowSize() { }

    public WindowSize(double width, double height, double? left = null, double? top = null)
    {
        Width = width;
        Height = height;
        Left = left;
        Top = top;
    }
}
