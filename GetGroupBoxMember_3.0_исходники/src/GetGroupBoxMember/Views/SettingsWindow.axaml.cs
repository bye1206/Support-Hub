using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Platform.Storage;
using GetGroupBoxMember.Models;
using GetGroupBoxMember.Services;
using System.Collections.Generic;
using System.Linq;

namespace GetGroupBoxMember.Views;

public partial class SettingsWindow : WindowBase
{
    private AppTheme _originalTheme;
    private AppTheme _selectedTheme;
    private bool _themeChanged;

    public SettingsWindow()
    {
        InitializeComponent();

        _originalTheme = _themeService.CurrentTheme;
        _selectedTheme = _originalTheme;

        LoadSettings();
        LoadThemes();
        UpdateCurrentThemeLabel();
    }

    private void LoadSettings()
    {
        var dc = _settings.DefaultDC;
        DcInputTextBox.Text = string.IsNullOrEmpty(dc) ? "" : dc.TrimEnd('/');
        UserLogPathTextBox.Text = _settings.UserLogPath ?? "";
        ShowAllMemberMaillistCheckBox.IsChecked = _settings.ShowAllMemberMaillist;
    }

    private void LoadThemes()
    {
        var themes = _themeService.GetAllThemes().ToList();
        var themeNames = themes.Select(t => t.Name).ToList();
        ThemeList.ItemsSource = themeNames;
    }

    private void UpdateCurrentThemeLabel()
    {
        var colors = _themeService.GetColors(_selectedTheme);
        CurrentThemeLabel.Text = colors.Name;
    }

    private void ThemeButton_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Border border && border.Child is TextBlock textBlock)
        {
            var themeName = textBlock.Text;
            var themes = _themeService.GetAllThemes().ToList();
            var selectedTheme = themes.FirstOrDefault(t => t.Name == themeName);

            if (selectedTheme != default)
            {
                _selectedTheme = selectedTheme.Theme;
                _themeChanged = _selectedTheme != _originalTheme;
                UpdateCurrentThemeLabel();
            }
        }
    }

    private async void BrowseUserLog_Click(object? sender, RoutedEventArgs e)
    {
        var topLevel = GetTopLevel(this);
        if (topLevel == null) return;

        var result = await topLevel.StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = "Выберите папку UserLog",
            AllowMultiple = false
        });

        if (result.Count > 0)
        {
            UserLogPathTextBox.Text = result[0].Path.LocalPath;
        }
    }

    private void SaveButton_Click(object? sender, RoutedEventArgs e)
    {
        _settings.DefaultDC = string.IsNullOrWhiteSpace(DcInputTextBox.Text) ? "" : DcInputTextBox.Text + "/";
        _settings.UserLogPath = UserLogPathTextBox.Text ?? "";
        _settings.ShowAllMemberMaillist = ShowAllMemberMaillistCheckBox.IsChecked ?? false;
        _settings.Save();

        if (_themeChanged)
        {
            _settings.CurrentTheme = _selectedTheme;
            _settings.Save();

            var restartDialog = new ThemeRestartDialog(_selectedTheme);
            restartDialog.Show();
            Close();
        }
        else
        {
            Close();
        }
    }

    private void CancelButton_Click(object? sender, RoutedEventArgs e)
    {
        Close();
    }
}
