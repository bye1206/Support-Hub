using Avalonia;
using Avalonia.Controls;
using Avalonia.Markup.Xaml;
using Avalonia.Media;
using Avalonia.Styling;
using GetGroupBoxMember.Models;
using System;
using System.Collections.Generic;
using System.Linq;

namespace GetGroupBoxMember.Services;

public class ThemeService
{
    private static ThemeService? _instance;
    public static ThemeService Instance => _instance ??= new ThemeService();

    private AppSettings _settings;
    private ThemeColors _currentColors;

    public event EventHandler<(AppTheme Theme, ThemeColors Colors)>? ThemeChanged;

    public ThemeColors CurrentColors => _currentColors;
    public AppTheme CurrentTheme => _settings.CurrentTheme;

    private ThemeService()
    {
        _settings = AppSettings.Load();
        _currentColors = ThemeManager.GetColors(_settings.CurrentTheme);
    }

    public void SetTheme(AppTheme theme)
    {
        if (_settings.CurrentTheme == theme) return;

        _settings.CurrentTheme = theme;
        _currentColors = ThemeManager.GetColors(theme);
        _settings.Save();
        ApplyThemeResources(theme);
        ThemeChanged?.Invoke(this, (theme, _currentColors));
    }

    public void ApplyThemePreview(AppTheme theme)
    {
        _currentColors = ThemeManager.GetColors(theme);
        ApplyThemeResources(theme);
        UpdateThemeVariant(theme);
        ThemeChanged?.Invoke(this, (theme, _currentColors));
    }

    private void UpdateThemeVariant(AppTheme theme)
    {
        var variant = GetThemeVariant(theme);
        var app = Application.Current;
        if (app != null)
        {
            app.RequestedThemeVariant = variant;
        }
    }

    public void ApplyThemeResources(AppTheme? theme = null)
    {
        var appTheme = theme ?? _settings.CurrentTheme;
        var prefix = appTheme switch
        {
            AppTheme.Dark => "",
            AppTheme.Light => "Light",
            AppTheme.Pink => "Pink",
            AppTheme.Green => "Green",
            AppTheme.Blue => "Blue",
            AppTheme.Orange => "Orange",
            AppTheme.Purple => "Purple",
            _ => ""
        };

        var app = Application.Current;
        if (app == null) return;

        var resources = app.Resources;

        void Set(string baseKey)
        {
            var fullKey = string.IsNullOrEmpty(prefix) ? baseKey : prefix + baseKey;
            if (resources.TryGetValue(fullKey, out var v))
                resources[baseKey] = v;
        }

        Set("ThemeBackground");
        Set("ThemeCardBackground");
        Set("ThemeElevatedSurface");
        Set("ThemeBorder");
        Set("ThemeTextPrimary");
        Set("ThemeTextSecondary");
        Set("ThemeTextMuted");
        Set("ThemeAccent");
        Set("ThemeAccentHover");
        Set("ThemeAccentPressed");
        Set("ThemeButtonBackground");
        Set("ThemeButtonHover");
        Set("AccentGreen");
        Set("AccentBlue");
        Set("AccentOrange");
        Set("AccentPurple");
        Set("AccentPink");
        Set("AccentRed");
        Set("LinkColor");
        Set("ThemeSuccessText");
        Set("ThemeWarningText");
        Set("ThemeOverlay");
        Set("ThemeMenuForeground");
        Set("ThemeMutedText");
        Set("ThemeButtonDefault");
        Set("ThemeButtonDefaultHover");
        Set("ThemeTextBoxBackground");
        Set("ThemeBorderAlt");
        Set("StatusGreen");
        Set("StatusGreenHover");
        Set("StatusPurple");
        Set("StatusRed");
        Set("StatusBlue");
        Set("StatusOrange");
        Set("ThemeSearchButton");
        Set("ThemeSearchButtonHover");
        Set("ThemeSearchButtonPressed");
        Set("ThemeTextOnElevated");
        Set("ThemeTextOnTextBox");
        Set("ThemeTextOnCard");
        Set("ThemeRadioText");
        Set("ThemeRadioTextChecked");
        Set("ThemeAccentButtonForeground");
        Set("ThemeSearchButtonForeground");
        Set("ThemeButtonPressedForeground");
        Set("ThemeGridLines");
        Set("ThemeActionLoadingBackground");
        Set("ThemeActionButtonAccent");
        Set("ThemeActionButtonAccentHover");
        Set("ThemeActionButtonAccentPressed");

    }

    public static ThemeVariant GetThemeVariant(AppTheme theme)
    {
        return theme switch
        {
            AppTheme.Dark => ThemeVariant.Dark,
            AppTheme.Light => ThemeVariant.Light,
            AppTheme.Pink => ThemeVariant.Light,
            AppTheme.Green => ThemeVariant.Dark,
            AppTheme.Blue => ThemeVariant.Dark,
            AppTheme.Orange => ThemeVariant.Dark,
            AppTheme.Purple => ThemeVariant.Dark,
            _ => ThemeVariant.Dark
        };
    }

    public WindowSize? GetWindowSize(string windowName)
    {
        if (_settings.WindowSizes.TryGetValue(windowName, out var size))
            return size;
        return null;
    }

    public void SaveWindowSize(string windowName, double width, double height, double? left = null, double? top = null)
    {
        _settings.WindowSizes[windowName] = new WindowSize(width, height, left, top);
        _settings.Save();
    }

    public ThemeColors GetColors(AppTheme theme) => ThemeManager.GetColors(theme);
    public IEnumerable<(AppTheme Theme, string Name)> GetAllThemes() => ThemeManager.GetAllThemes();
}
