using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Threading;
using System;
using System.Collections.Generic;

namespace GetGroupBoxMember.Services;

public sealed class WindowManager : IWindowManager
{
    private static readonly Lazy<WindowManager> _instance = new(() => new WindowManager());
    public static WindowManager Instance => _instance.Value;

    private readonly List<Window> _openWindows = new();
    private readonly object _lock = new();

    private WindowManager() { }

    public void OpenWindow<T>() where T : Window, new()
    {
        var window = new T();
        OpenWindow(window);
    }

    public void OpenWindow(Window window)
    {
        RegisterOpenedWindow(window);
        window.Show();
        window.Activate();
    }

    public IReadOnlyList<Window> GetOpenWindows()
    {
        lock (_lock)
        {
            return _openWindows.ToArray();
        }
    }

    public void BringToFront(Window window)
    {
        if (window.WindowState == WindowState.Minimized)
        {
            window.WindowState = WindowState.Normal;
        }
        window.Activate();
    }

    public void CloseAllWindows()
    {
        List<Window> windowsToClose;
        lock (_lock)
        {
            windowsToClose = new List<Window>(_openWindows);
        }

        foreach (var window in windowsToClose)
        {
            try
            {
                window.Close();
            }
            catch { }
        }
    }

    public void RegisterOpenedWindow(Window window)
    {
        lock (_lock)
        {
            if (!_openWindows.Contains(window))
            {
                _openWindows.Add(window);
                window.Closed += OnWindowClosed;
            }
        }
    }

    public void UnregisterWindow(Window window)
    {
        lock (_lock)
        {
            _openWindows.Remove(window);
        }
    }

    private void OnWindowClosed(object? sender, EventArgs e)
    {
        if (sender is Window window)
        {
            window.Closed -= OnWindowClosed;
            UnregisterWindow(window);
        }
    }

    public event Action<string>? NotificationRequested;

    public void ShowNotification(string message)
    {
        NotificationRequested?.Invoke(message);
    }

    public static Window? GetMainWindow()
    {
        return (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.MainWindow;
    }
}
