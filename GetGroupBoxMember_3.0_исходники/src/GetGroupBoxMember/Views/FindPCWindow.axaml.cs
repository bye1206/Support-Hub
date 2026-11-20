using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using GetGroupBoxMember.Services;
using System;
using System.Data;
using System.IO;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views;

public partial class FindPCWindow : WindowBase
{
    public DataTable? DataSource
    {
        get => _dataSource;
        set
        {
            _dataSource = value;
            if (value != null)
            {
                Title = value.TableName ?? "Найти ПК";
            }
            if (value != null && MainGridTable != null)
            {
                MainGridTable.SetDataSource(value);
                LoadingOverlay.IsVisible = false;
            }
        }
    }

    private DataTable? _dataSource;

    public FindPCWindow()
    {
        InitializeComponent();

        Loaded += (s, e) =>
        {
            if (_dataSource != null && MainGridTable != null)
            {
                MainGridTable.SetDataSource(_dataSource);
                LoadingOverlay.IsVisible = false;
            }
        };
    }

    private void ShowLoading()
    {
        if (LoadingOverlay != null)
        {
            LoadingOverlay.IsVisible = true;
            LoadingOverlay.BringIntoView();
        }
    }

    private void HideLoading()
    {
        if (LoadingOverlay != null)
        {
            LoadingOverlay.IsVisible = false;
        }
    }

    public FindPCWindow(DataTable dataSource) : this()
    {
        DataSource = dataSource;
    }

    public async Task<DataTable?> LoadFromServiceAsync(Func<Task<DataTable>> loader)
    {
        LoadingOverlay.IsVisible = true;
        MainGridTable.IsVisible = false;

        try
        {
            var dt = await loader();
            DataSource = dt;
            return dt;
        }
        finally
        {
            MainGridTable.IsVisible = true;
        }
    }

    private async void ExportXlsx_Click(object? sender, RoutedEventArgs e)
    {
        if (_dataSource == null || _dataSource.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var topLevel = GetTopLevel(this);
        if (topLevel == null) return;

        IStorageFile? file = null;
        try
        {
            file = await topLevel.StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "Экспорт в Excel",
                SuggestedFileName = FileDialogHelper.SanitizeFileName($"PC_Search_{DateTime.Now:yyyyMMdd}"),
                FileTypeChoices = new[]
                {
                    new FilePickerFileType("Excel") { Patterns = new[] { "*.xlsx" } }
                }
            });
        }
        catch (Exception ex)
        {
            await ShowMessageAsync($"Ошибка при выборе файла: {ex.Message}");
            return;
        }

        if (file != null)
        {
            var log = new ExcelLog(file.Path.LocalPath);
            var ex = await Task.Run(() => log.WriteXlsx(_dataSource));
            if (ex != null)
                await ShowMessageAsync(ex.Message);
            else
                await ShowMessageAsync("Успешно!");
        }
    }

    private async void ExportTxt_Click(object? sender, RoutedEventArgs e)
    {
        if (_dataSource == null || _dataSource.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var topLevel = GetTopLevel(this);
        if (topLevel == null) return;

        IStorageFile? file = null;
        try
        {
            file = await topLevel.StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "Экспорт в текст",
                SuggestedFileName = FileDialogHelper.SanitizeFileName($"PC_Search_{DateTime.Now:yyyyMMdd}"),
                FileTypeChoices = new[]
                {
                    new FilePickerFileType("Text") { Patterns = new[] { "*.txt" } }
                }
            });
        }
        catch (Exception ex)
        {
            await ShowMessageAsync($"Ошибка при выборе файла: {ex.Message}");
            return;
        }

        if (file != null)
        {
            var log = new ExcelLog(file.Path.LocalPath);
            var ex = await Task.Run(() => log.WriteTxt(_dataSource));
            if (ex != null)
                await ShowMessageAsync(ex.Message);
            else
                await ShowMessageAsync("Успешно!");
        }
    }

    protected override void OnClosing(WindowClosingEventArgs e)
    {
        if (_dataSource != null)
        {
            _dataSource.Clear();
            _dataSource.Dispose();
            _dataSource = null;
        }
        base.OnClosing(e);
    }

    private async void CopyToClipboard_Click(object? sender, RoutedEventArgs e)
    {
        if (_dataSource == null || _dataSource.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для копирования.");
            return;
        }

        try
        {
            var sb = new System.Text.StringBuilder();
            
            for (int i = 0; i < _dataSource.Columns.Count; i++)
            {
                sb.Append(_dataSource.Columns[i].ColumnName);
                if (i < _dataSource.Columns.Count - 1)
                    sb.Append('\t');
            }
            sb.AppendLine();

            for (int row = 0; row < _dataSource.Rows.Count; row++)
            {
                for (int col = 0; col < _dataSource.Columns.Count; col++)
                {
                    var val = _dataSource.Rows[row][col]?.ToString()?.Replace("\r", "").Replace("\n", " ").Replace("\t", " ") ?? "";
                    sb.Append(val);
                    if (col < _dataSource.Columns.Count - 1)
                        sb.Append('\t');
                }
                sb.AppendLine();
            }

            var topLevel = GetTopLevel(this);
            if (topLevel?.Clipboard != null)
            {
                await topLevel.Clipboard.SetTextAsync(sb.ToString());
                await ShowMessageAsync($"Скопировано {_dataSource.Rows.Count} строк в буфер обмена!");
            }
            else
            {
                await ShowMessageAsync("Буфер обмена недоступен.");
            }
        }
        catch (Exception ex)
        {
            await ShowMessageAsync($"Ошибка копирования: {ex.Message}");
        }
    }

    private async Task ShowMessageAsync(string message, string title = "Информация")
    {
        var dialog = new Window
        {
            Title = title,
            Width = 350,
            Height = 150,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Background = (Brush)Application.Current?.FindResource("ThemeCardBackground") 
                ?? new SolidColorBrush(Colors.Black),
            Content = new StackPanel
            {
                Spacing = 16,
                Margin = new Thickness(20),
                VerticalAlignment = VerticalAlignment.Center,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap, Foreground = (Brush)Application.Current?.FindResource("ThemeTextOnCard") ?? new SolidColorBrush(Colors.White), HorizontalAlignment = HorizontalAlignment.Center },
                    new Button { Content = "OK", HorizontalAlignment = HorizontalAlignment.Center }
                }
            }
        };

        if (dialog.Content is StackPanel sp && sp.Children.Count > 1 && sp.Children[1] is Button btn)
        {
            btn.Click += (s, e) => dialog.Close();
        }

        if (GetTopLevel(this) is Window top)
        {
            await dialog.ShowDialog(top);
        }
    }
}
