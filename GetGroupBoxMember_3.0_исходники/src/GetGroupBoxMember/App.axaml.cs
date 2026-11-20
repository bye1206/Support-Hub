using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Styling;
using GetGroupBoxMember.Models;
using GetGroupBoxMember.Services;
using GetGroupBoxMember.Views;
using System;

namespace GetGroupBoxMember;

public partial class App : Application
{
    private static readonly ThemeService _themeService = ThemeService.Instance;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
        LoadThemeResources();
        var settings = AppSettings.Load();
        RequestedThemeVariant = ThemeService.GetThemeVariant(settings.CurrentTheme);
    }

    private void LoadThemeResources()
    {
        try
        {
            var loaded = AvaloniaXamlLoader.Load(
                new Uri("avares://GetGroupBoxMember/Styles/ThemeResources.axaml"));
            
            if (loaded is ResourceDictionary themeResources)
            {
                foreach (var resource in themeResources)
                {
                    Resources[resource.Key] = resource.Value;
                }
            }
        }
        catch (Exception ex)
        {
            FileLogger.Log($"[App.LoadThemeResources] ERROR: {ex.Message}");
        }
    }

    public override void OnFrameworkInitializationCompleted()
    {
        var settings = AppSettings.Load();
        var theme = settings.CurrentTheme;
        RequestedThemeVariant = ThemeService.GetThemeVariant(theme);
        _themeService.ApplyThemeResources(theme);

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new MainWindow();
        }

        base.OnFrameworkInitializationCompleted();
    }
}
