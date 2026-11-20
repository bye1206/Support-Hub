using Avalonia;
using System;
using System.IO;
using System.Threading.Tasks;

namespace GetGroupBoxMember;

class Program
{
    private static readonly string CrashLogPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "GetGroupBoxMember", "logs", "ggbm_crash.log");

    [STAThread]
    public static void Main(string[] args)
    {
        var logDir = Path.GetDirectoryName(CrashLogPath);
        if (!string.IsNullOrEmpty(logDir) && !Directory.Exists(logDir))
            Directory.CreateDirectory(logDir);

        AppDomain.CurrentDomain.UnhandledException += (s, e) =>
        {
            var ex = e.ExceptionObject as Exception;
            var msg = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] UNHANDLED EXCEPTION: {ex}\nStackTrace: {ex?.StackTrace}\n";
            try { File.AppendAllText(CrashLogPath, msg); } catch { }
        };

        TaskScheduler.UnobservedTaskException += (s, e) =>
        {
            var msg = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff}] UNOBSERVED TASK EXCEPTION: {e.Exception}\nStackTrace: {e.Exception.StackTrace}\n";
            try { File.AppendAllText(CrashLogPath, msg); } catch { }
            e.SetObserved();
        };

        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp()
    {
        return AppBuilder.Configure<App>()
            .UsePlatformDetect();
    }
}
