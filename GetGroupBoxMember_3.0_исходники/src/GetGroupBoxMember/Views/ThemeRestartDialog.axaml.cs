using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;
using GetGroupBoxMember.Models;
using GetGroupBoxMember.Services;
using System;
using System.Diagnostics;

namespace GetGroupBoxMember.Views;

public partial class ThemeRestartDialog : Window
{
    private readonly AppTheme _newTheme;

    public ThemeRestartDialog(AppTheme newTheme)
    {
        _newTheme = newTheme;
        InitializeComponent();

        var colors = ThemeService.Instance.GetColors(newTheme);
        ThemeLabel.Text = $"Выбрана тема: {colors.Name}";
    }

    private void RestartButton_Click(object? sender, RoutedEventArgs e)
    {
        Close();
        RestartApplication();
    }

    private void CancelButton_Click(object? sender, RoutedEventArgs e)
    {
        Close();
    }

    private void RestartApplication()
    {
        try
        {
            var exePath = Environment.ProcessPath;
            if (string.IsNullOrEmpty(exePath)) return;

            Process.Start(new ProcessStartInfo { FileName = exePath, UseShellExecute = true });

            if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            {
                desktop.Shutdown();
            }
        }
        catch
        {
        }
    }
}
