using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using GetGroupBoxMember.Services;
using GetGroupBoxMember.Views.Controls;
using System;
using System.Data;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views;

public partial class CompareGroupsWindow : WindowBase
{
    private readonly IADService _adService;
    private DataTable? _resultTable;

    public CompareGroupsWindow()
    {
        InitializeComponent();
        _adService = new ADService();

        Opened += (s, e) =>
        {
            Login1TextBox?.Focus();
            MainGridTable?.SetUncColumn(1);
        };
    }

    private async void CompareButton_Click(object? sender, RoutedEventArgs e)
    {
        string login1 = Login1TextBox.Text?.Trim() ?? "";
        string login2 = Login2TextBox.Text?.Trim() ?? "";

        if (string.IsNullOrWhiteSpace(login1) || string.IsNullOrWhiteSpace(login2))
        {
            var msg = string.IsNullOrWhiteSpace(login1)
                ? "Введите логин первого пользователя."
                : "Введите логин второго пользователя.";
            await ShowMessageAsync(msg, "Ошибка");
            return;
        }

        if (login1.Equals(login2, StringComparison.OrdinalIgnoreCase))
        {
            await ShowMessageAsync("Введите разные логины пользователей.", "Ошибка");
            return;
        }


        LoadingOverlay.IsVisible = true;
        EmptyStateBorder.IsVisible = false;
        MainGridTable.SetDataSource(null);

        try
        {
            var result = await _adService.GetUsersGroupComparisonAsync(login1, login2);

            if (result == null || result.Rows.Count == 0)
            {
                LoadingOverlay.IsVisible = false;
                await ShowMessageAsync("Группы не найдены ни у одного из пользователей.", "Информация");
                return;
            }

            _resultTable = result;
            _resultTable.TableName = $"{login1} vs {login2}";

            foreach (var row in result.AsEnumerable().Take(3))
            {
            }

            try { MainGridTable.SetDataSource(result); }
            catch (Exception ex) {  throw; }

            try { MainGridTable.RebuildTable(); }
            catch (Exception ex) {  throw; }

            try { MainGridTable.IsVisible = true; }
            catch (Exception ex) {  throw; }


            LoadingOverlay.IsVisible = false;

        }
        catch (Exception ex)
        {
            await ShowMessageAsync($"Ошибка: {ex.Message}", "Ошибка");
        }
        finally
        {
            LoadingOverlay.IsVisible = false;
        }
    }

    private async void ExportXlsx_Click(object? sender, RoutedEventArgs e)
    {
        if (_resultTable == null || _resultTable.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.", "Информация");
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
                SuggestedFileName = FileDialogHelper.SanitizeFileName($"Сравнение_групп_{Login1TextBox.Text}_vs_{Login2TextBox.Text}"),
                FileTypeChoices = new[]
                {
                    new FilePickerFileType("Excel") { Patterns = new[] { "*.xlsx" } }
                }
            });
        }
        catch (Exception ex)
        {
            await ShowMessageAsync($"Ошибка при выборе файла: {ex.Message}", "Ошибка");
            return;
        }

        if (file != null)
        {
            var log = new ExcelLog(file.Path.LocalPath);
            var ex = await Task.Run(() => log.WriteXlsx(_resultTable));
            if (ex != null)
                await ShowMessageAsync(ex.Message, "Ошибка экспорта");
            else
                await ShowMessageAsync("Успешно!", "Экспорт");
        }
    }

    private async void ExportTxt_Click(object? sender, RoutedEventArgs e)
    {
        if (_resultTable == null || _resultTable.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.", "Информация");
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
                SuggestedFileName = FileDialogHelper.SanitizeFileName($"Сравнение_групп_{Login1TextBox.Text}_vs_{Login2TextBox.Text}"),
                FileTypeChoices = new[]
                {
                    new FilePickerFileType("Text") { Patterns = new[] { "*.txt" } }
                }
            });
        }
        catch (Exception ex)
        {
            await ShowMessageAsync($"Ошибка при выборе файла: {ex.Message}", "Ошибка");
            return;
        }

        if (file != null)
        {
            var log = new ExcelLog(file.Path.LocalPath);
            var ex = await Task.Run(() => log.WriteTxt(_resultTable));
            if (ex != null)
                await ShowMessageAsync(ex.Message, "Ошибка экспорта");
            else
                await ShowMessageAsync("Успешно!", "Экспорт");
        }
    }

    private async void CopyToClipboard_Click(object? sender, RoutedEventArgs e)
    {
        if (_resultTable == null)
        {
            await ShowMessageAsync("Нет данных для копирования.", "Информация");
            return;
        }

        try
        {
            var sb = new System.Text.StringBuilder();
            foreach (DataColumn col in _resultTable.Columns)
            {
                sb.Append(col.ColumnName + "\t");
            }
            sb.AppendLine();
            foreach (DataRow row in _resultTable.Rows)
            {
                foreach (DataColumn col in _resultTable.Columns)
                {
                    sb.Append(row[col.ColumnName]?.ToString() + "\t");
                }
                sb.AppendLine();
            }

            var topLevel = GetTopLevel(this);
            if (topLevel?.Clipboard != null)
            {
                await topLevel.Clipboard.SetTextAsync(sb.ToString());
                await ShowMessageAsync("Скопировано в буфер обмена.", "Копирование");
            }
            else
            {
                await ShowMessageAsync("Буфер обмена недоступен.", "Копирование");
            }
        }
        catch (Exception ex)
        {
            await ShowMessageAsync($"Ошибка копирования: {ex.Message}", "Ошибка");
        }
    }

    private async void CopyFormatted_Click(object? sender, RoutedEventArgs e)
    {
        if (_resultTable == null)
        {
            await ShowMessageAsync("Нет данных для копирования.", "Информация");
            return;
        }

        try
        {
            string login1 = Login1TextBox.Text?.Trim() ?? "";
            string login2 = Login2TextBox.Text?.Trim() ?? "";
            var sb = new System.Text.StringBuilder();

            sb.AppendLine($"Сравнение групп пользователей: {login1} vs {login2}");
            sb.AppendLine(new string('=', 60));
            sb.AppendLine();
            sb.AppendLine($"Только у {login1}:");
            sb.AppendLine(new string('-', 40));

            foreach (DataRow row in _resultTable.Rows)
            {
                var key = "Только у " + login1;
                if (_resultTable.Columns.Contains(key) && row[key]?.ToString() == "✓")
                {
                    var groupName = row["Группа"]?.ToString();
                    var description = row["Описание"]?.ToString();
                    sb.AppendLine($"  • {groupName}");
                    if (!string.IsNullOrWhiteSpace(description))
                        sb.AppendLine($"    {description}");
                }
            }

            sb.AppendLine();
            sb.AppendLine($"Только у {login2}:");
            sb.AppendLine(new string('-', 40));

            foreach (DataRow row in _resultTable.Rows)
            {
                var key = "Только у " + login2;
                if (_resultTable.Columns.Contains(key) && row[key]?.ToString() == "✓")
                {
                    var groupName = row["Группа"]?.ToString();
                    var description = row["Описание"]?.ToString();
                    sb.AppendLine($"  • {groupName}");
                    if (!string.IsNullOrWhiteSpace(description))
                        sb.AppendLine($"    {description}");
                }
            }

            sb.AppendLine();
            sb.AppendLine("Общие группы:");
            sb.AppendLine(new string('-', 40));

            foreach (DataRow row in _resultTable.Rows)
            {
                if (_resultTable.Columns.Contains("Общая") && row["Общая"]?.ToString() == "✓")
                {
                    var groupName = row["Группа"]?.ToString();
                    var description = row["Описание"]?.ToString();
                    sb.AppendLine($"  • {groupName}");
                    if (!string.IsNullOrWhiteSpace(description))
                        sb.AppendLine($"    {description}");
                }
            }

            var topLevel = GetTopLevel(this);
            if (topLevel?.Clipboard != null)
            {
                await topLevel.Clipboard.SetTextAsync(sb.ToString());
            }
            await ShowMessageAsync("Форматированный текст скопирован в буфер обмена.", "Копирование");
        }
        catch (Exception ex)
        {
            await ShowMessageAsync($"Ошибка копирования: {ex.Message}", "Ошибка");
        }
    }

    private async Task ShowMessageAsync(string message, string title)
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

        if (GetTopLevel(this) is Window topLevel)
        {
            await dialog.ShowDialog(topLevel);
        }
    }
}