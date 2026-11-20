using System;
using System.IO;
using System.Threading;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Avalonia.Threading;

namespace GetGroupBoxMember.Services;

internal static class FreezeWatchdog
{
    private static readonly string LogPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "GetGroupBoxMember", "logs", "freeze.log");

    private static readonly string DumpDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "GetGroupBoxMember", "dumps");

    private static Thread? _watchThread;
    private static volatile bool _running;
    private static DateTime _lastUiHeartbeat = DateTime.UtcNow;
    private static readonly object _heartbeatLock = new();
    private static int _uiThreadId = -1;
    private static int _freezeCount = 0;
    private static DateTime _lastDumpTime = DateTime.MinValue;
    private static volatile bool _uiThreadAlive = false;

    [DllImport("dbghelp.dll", SetLastError = true)]
    private static extern bool MiniDumpWriteDump(IntPtr hProcess, uint processId, IntPtr hFile,
        uint dumpType, IntPtr exceptionParam, IntPtr userStreamParam, IntPtr callbackParam);

    private const uint MiniDumpNormal = 0x00000000;
    private const uint MiniDumpWithFullMemory = 0x00000002;
    private const uint MiniDumpWithIndirectlyReferencedMemory = 0x00000040;
    private const uint MiniDumpWithThreadInfo = 0x00001000;

    public static void Start()
    {
        if (_running) return;
        _running = true;

        try
        {
            if (!Directory.Exists(DumpDir)) Directory.CreateDirectory(DumpDir);
            File.WriteAllText(LogPath, $"=== FreezeWatchdog started {DateTime.Now} ==={Environment.NewLine}");
        }
        catch { }

        _watchThread = new Thread(WatchLoop)
        {
            Name = "FreezeWatchdog",
            IsBackground = true,
            Priority = ThreadPriority.Highest
        };
        _watchThread.Start();
    }

    private static void WatchLoop()
    {
        Thread.Sleep(3000);

        while (_running)
        {
            try
            {
                var now = DateTime.UtcNow;

                int workerThreads, completionPortThreads;
                ThreadPool.GetAvailableThreads(out workerThreads, out completionPortThreads);
                int activeThreads = Process.GetCurrentProcess().Threads.Count;

                DateTime lastHeartbeat;
                lock (_heartbeatLock)
                {
                    lastHeartbeat = _lastUiHeartbeat;
                    _uiThreadAlive = false;
                }

                Dispatcher.UIThread.Post(() =>
                {
                    lock (_heartbeatLock)
                    {
                        _lastUiHeartbeat = DateTime.UtcNow;
                        _uiThreadAlive = true;
                    }
                });

                Thread.Sleep(2000);

                bool uiResponded;
                lock (_heartbeatLock)
                {
                    uiResponded = _uiThreadAlive;
                }

                var silenceAfterPing = (DateTime.UtcNow - lastHeartbeat).TotalMilliseconds;

                if (!uiResponded && silenceAfterPing > 5000)
                {
                    _freezeCount++;
                    Log($"*** FREEZE DETECTED #{_freezeCount} *** UI thread has NOT responded to heartbeat ping for {silenceAfterPing:F0}ms");
                    Log($"  ThreadPool: available workers={workerThreads}, completionPorts={completionPortThreads}");
                    Log($"  Process threads: {activeThreads}");

                    try
                    {
                        var proc = Process.GetCurrentProcess();
                        Log($"  CPU time: {proc.TotalProcessorTime.TotalSeconds:F1}s, WorkingSet: {proc.WorkingSet64 / 1024 / 1024}MB");

                        int uiThreadId = -1;
                        try
                        {
                            uiThreadId = Dispatcher.UIThread.CheckAccess() ? Environment.CurrentManagedThreadId : -1;
                        }
                        catch { }

                        foreach (ProcessThread pt in proc.Threads)
                        {
                            try
                            {
                                var state = pt.ThreadState.ToString();
                                var waitReason = pt.WaitReason.ToString();

                                if (pt.Id == uiThreadId)
                                {
                                    Log($"  *** UI THREAD (id={uiThreadId}): state={state}, waitReason={waitReason}, priority={pt.PriorityLevel}");
                                }
                            }
                            catch { }
                        }
                    }
                    catch { }

                    LogDumpOpenWindows();

                    if ((DateTime.UtcNow - _lastDumpTime).TotalSeconds > 30)
                    {
                        _lastDumpTime = DateTime.UtcNow;
                        WriteMiniDump();
                    }
                }
            }
            catch (Exception ex)
            {
                try { Log($"Watchdog exception: {ex.Message}"); } catch { }
            }

            Thread.Sleep(1000);
        }
    }

    private static void WriteMiniDump()
    {
        try
        {
            var dumpPath = Path.Combine(DumpDir, $"ggbm_freeze_{DateTime.Now:yyyyMMdd_HHmmss}.dmp");
            using var fs = new FileStream(dumpPath, FileMode.Create, FileAccess.ReadWrite, FileShare.None);
            var proc = Process.GetCurrentProcess();
            uint dumpType = MiniDumpNormal | MiniDumpWithThreadInfo | MiniDumpWithIndirectlyReferencedMemory;
            bool ok = MiniDumpWriteDump(proc.SafeHandle.DangerousGetHandle(), (uint)proc.Id, fs.SafeFileHandle.DangerousGetHandle(), dumpType, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (ok)
                Log($"  Mini-dump written: {dumpPath} ({new FileInfo(dumpPath).Length / 1024 / 1024}MB)");
            else
                Log($"  Mini-dump FAILED: Win32 error={Marshal.GetLastWin32Error()}");
        }
        catch (Exception ex)
        {
            Log($"  Mini-dump exception: {ex.Message}");
        }
    }

    private static void LogDumpOpenWindows()
    {
        try
        {
            var wm = WindowManager.Instance;
            var windows = wm.GetOpenWindows();
            Log($"  Open windows: {windows.Count}");
            foreach (var w in windows)
            {
                try
                {
                    Log($"    - {w.GetType().Name}: Title={w.Title}, IsActive={w.IsActive}, Bounds={w.Bounds}");
                }
                catch
                {
                    Log($"    - (failed to read window info)");
                }
            }
        }
        catch (Exception ex)
        {
            Log($"  Failed to dump windows: {ex.Message}");
        }
    }

    private static void Log(string message)
    {
        try
        {
            var entry = $"[{DateTime.Now:HH:mm:ss.fff}] {message}";
            File.AppendAllText(LogPath, entry + Environment.NewLine);
        }
        catch { }
    }
}
