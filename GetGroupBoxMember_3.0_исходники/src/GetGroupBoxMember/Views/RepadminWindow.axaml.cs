using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using GetGroupBoxMember.Services;
using GetGroupBoxMember.Views.Controls;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Data;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views;

public partial class RepadminWindow : WindowBase
{
    private readonly IADService _adService;
    private string _objectLogin;
    private DataTable? _attributeMetaDataTable;
    private DataTable? _valueMetaDataTable;
    private DataView? _attributeMetaDataView;
    private DataView? _valueMetaDataView;
    private List<string> _attributesList = new();
    private bool _isLoading = false;
    private readonly System.Diagnostics.Stopwatch _sw = new();

    public RepadminWindow() : this("")
    {
    }

    public RepadminWindow(string login)
    {
        InitializeComponent();
        _adService = new ADService();
        _objectLogin = login;
        Title = $"Информация RepAdmin по объекту: {login}";

        LoadDataAsync();
    }

    private async void LoadDataAsync()
    {
        _sw.Restart();
        LoadingOverlay.IsVisible = true;
        _isLoading = true;

        try
        {
            Task<DataTable> attrTask = _adService.GetRepadminInfoAttributeMetaDataAsync(_objectLogin);
            Task<DataTable> valueTask = _adService.GetRepadminInfoValueMetaDataAsync(_objectLogin);

            await Task.WhenAll(attrTask, valueTask);

            _attributeMetaDataTable = attrTask.Result;
            _valueMetaDataTable = valueTask.Result;

            if (_attributeMetaDataTable != null && _attributeMetaDataTable.Rows.Count == 0)
            {
                _attributeMetaDataTable = null;
            }

            if (_valueMetaDataTable != null && _valueMetaDataTable.Rows.Count == 0)
            {
                _valueMetaDataTable = null;
            }

            if (_attributeMetaDataTable != null)
            {
                _attributeMetaDataView = _attributeMetaDataTable.DefaultView;
                BindAttributeDataToGrid();
            }

            if (_valueMetaDataTable != null)
            {
                _attributesList = _valueMetaDataTable.AsEnumerable()
                    .Select(r => r["Атрибут"]?.ToString())
                    .Where(a => !string.IsNullOrEmpty(a))
                    .Distinct()
                    .OrderBy(a => a)
                    .ToList()!;

                ValueMetaDataListBox.ItemsSource = _attributesList;
                if (_attributesList.Count > 0)
                {
                    ValueMetaDataListBox.SelectedIndex = 0;
                }

                _valueMetaDataView = _valueMetaDataTable.DefaultView;
                BindValueDataToGrid();
            }

        }
        catch (Exception ex)
        {
            if (ex.InnerException != null)
            {
            }
            ShowError($"Ошибка: {ex.Message}");
        }
        finally
        {
            LoadingOverlay.IsVisible = false;
            _isLoading = false;
        }
    }

    private void ValueMetaDataListBox_SelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (_isLoading || _valueMetaDataTable == null) return;

        var selectedItem = ValueMetaDataListBox.SelectedItem as string;
        if (string.IsNullOrEmpty(selectedItem)) return;

        var filtered = _valueMetaDataTable.AsEnumerable()
            .Where(r => r["Атрибут"]?.ToString() == selectedItem);

        var filteredTable = filtered.Count() > 0
            ? filtered.CopyToDataTable()
            : _valueMetaDataTable.Clone();

        _valueMetaDataView = filteredTable.DefaultView;
        BindValueDataToGrid();
    }

    private void AttributeFilter_TextChanged(object? sender, TextChangedEventArgs e)
    {
        if (_attributeMetaDataTable == null) return;

        var filter = AttributeFilterTextBox.Text ?? "";
        FilterAttributeData(filter);
    }

    private void ValueFilter_TextChanged(object? sender, TextChangedEventArgs e)
    {
        if (_valueMetaDataTable == null) return;

        var filter = ValueFilterTextBox.Text ?? "";
        FilterValueData(filter);
    }

    private void BindAttributeDataToGrid()
    {
        var table = _attributeMetaDataView?.ToTable() ?? _attributeMetaDataTable;
        var grid = this.FindControl<GridTable>("AttributeMetaDataGrid");
        if (table == null || grid == null) return;

        var headers = new ObservableCollection<string>();
        foreach (DataColumn col in table.Columns)
            headers.Add(col.ColumnName);

        var rows = new ObservableCollection<string[]>();
        foreach (DataRow row in table.Rows)
        {
            var rowData = table.Columns.Cast<DataColumn>()
                .Select(c => row[c]?.ToString() ?? "")
                .ToArray();
            rows.Add(rowData);
        }

        grid.ColumnHeaders = headers;
        grid.Rows = rows;
    }

    private void BindValueDataToGrid()
    {
        var table = _valueMetaDataView?.ToTable() ?? _valueMetaDataTable;
        var grid = this.FindControl<GridTable>("ValueMetaDataGrid");
        if (table == null || grid == null) return;

        var headers = new ObservableCollection<string>();
        foreach (DataColumn col in table.Columns)
            headers.Add(col.ColumnName);

        var rows = new ObservableCollection<string[]>();
        foreach (DataRow row in table.Rows)
        {
            var rowData = table.Columns.Cast<DataColumn>()
                .Select(c => row[c]?.ToString() ?? "")
                .ToArray();
            rows.Add(rowData);
        }

        grid.ColumnHeaders = headers;
        grid.Rows = rows;
    }

    private void FilterAttributeData(string filter)
    {
        if (_attributeMetaDataTable == null) return;

        if (string.IsNullOrWhiteSpace(filter))
        {
            _attributeMetaDataView = _attributeMetaDataTable.DefaultView;
        }
        else
        {
            var pattern = filter.Replace("*", ".*");
            var filtered = _attributeMetaDataTable.AsEnumerable()
                .Where(r =>
                {
                    var attr = r.Table.Columns.Contains("Атрибут") ? r["Атрибут"]?.ToString() ?? "" : "";
                    var dc = r.Table.Columns.Contains("Контроллер домена") ? r["Контроллер домена"]?.ToString() ?? "" : "";
                    var changed = r.Table.Columns.Contains("Изменён") ? r["Изменён"]?.ToString() ?? "" : "";
                    return TextMatcher.Matches(attr, pattern) ||
                           TextMatcher.Matches(dc, pattern) ||
                           System.Text.RegularExpressions.Regex.IsMatch(changed, $"(?i){pattern}");
                });

            if (filtered.Any())
            {
                var newTable = filtered.CopyToDataTable();
                _attributeMetaDataView = newTable.DefaultView;
            }
            else
            {
                _attributeMetaDataView = _attributeMetaDataTable.Clone().DefaultView;
            }
        }

        BindAttributeDataToGrid();
    }

    private void FilterValueData(string filter)
    {
        if (_valueMetaDataTable == null) return;

        var selectedItem = ValueMetaDataListBox.SelectedItem as string;
        if (string.IsNullOrEmpty(selectedItem)) return;

        var baseFiltered = _valueMetaDataTable.AsEnumerable()
            .Where(r => r["Атрибут"]?.ToString() == selectedItem);

        if (!baseFiltered.Any())
        {
            _valueMetaDataView = _valueMetaDataTable.Clone().DefaultView;
            BindValueDataToGrid();
            return;
        }

        if (string.IsNullOrWhiteSpace(filter))
        {
            var table = baseFiltered.CopyToDataTable();
            _valueMetaDataView = table.DefaultView;
        }
        else
        {
            var pattern = filter.Replace("*", ".*");
            var filtered = baseFiltered
                .Where(r =>
                {
                    var dn = r.Table.Columns.Contains("distinguishedName") ? r["distinguishedName"]?.ToString() ?? "" : "";
                    var cn = r.Table.Columns.Contains("cn") ? r["cn"]?.ToString() ?? "" : "";
                    var state = r.Table.Columns.Contains("Состояние") ? r["Состояние"]?.ToString() ?? "" : "";
                    return TextMatcher.Matches(dn, pattern) ||
                           TextMatcher.Matches(cn, pattern) ||
                           TextMatcher.Matches(state, pattern);
                });

            if (filtered.Any())
            {
                var newTable = filtered.CopyToDataTable();
                _valueMetaDataView = newTable.DefaultView;
            }
            else
            {
                _valueMetaDataView = _valueMetaDataTable.Clone().DefaultView;
            }
        }

        BindValueDataToGrid();
    }

    private async void Export_Click(object? sender, RoutedEventArgs e)
    {
        DataTable? exportTable = null;
        string tabName = MainTabControl.SelectedIndex == 0 ? "AttributeMetaData" : "ValueMetaData";

        if (tabName == "AttributeMetaData")
        {
            exportTable = _attributeMetaDataView?.ToTable();
        }
        else
        {
            exportTable = _valueMetaDataView?.ToTable();
        }

        if (exportTable == null || exportTable.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var topLevel = GetTopLevel(this);
        if (topLevel == null) return;

        exportTable.TableName = $"RepAdmin {_objectLogin}";

        IStorageFile? file = null;
        try
        {
            file = await topLevel.StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "Экспорт данных RepAdmin",
                SuggestedFileName = FileDialogHelper.SanitizeFileName($"RepAdmin {_objectLogin}"),
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
            var ex = await Task.Run(() => log.WriteXlsx(exportTable, new[] { "Атрибут", "Значение", "Описание" }));
            if (ex != null)
                await ShowMessageAsync(ex.Message);
            else
                await ShowMessageAsync("Успешно!");
        }
    }

    private async void CopyToClipboard_Click(object? sender, RoutedEventArgs e)
    {
        DataTable? table = MainTabControl.SelectedIndex == 0
            ? _attributeMetaDataView?.ToTable()
            : _valueMetaDataView?.ToTable();

        if (table == null || table.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для копирования.");
            return;
        }

        try
        {
            var sb = new System.Text.StringBuilder();
            
            for (int i = 0; i < table.Columns.Count; i++)
            {
                sb.Append(table.Columns[i].ColumnName);
                if (i < table.Columns.Count - 1)
                    sb.Append('\t');
            }
            sb.AppendLine();

            for (int row = 0; row < table.Rows.Count; row++)
            {
                for (int col = 0; col < table.Columns.Count; col++)
                {
                    var val = table.Rows[row][col]?.ToString()?.Replace("\r", "").Replace("\n", " ").Replace("\t", " ") ?? "";
                    sb.Append(val);
                    if (col < table.Columns.Count - 1)
                        sb.Append('\t');
                }
                sb.AppendLine();
            }

            var topLevel = GetTopLevel(this);
            if (topLevel?.Clipboard != null)
            {
                await topLevel.Clipboard.SetTextAsync(sb.ToString());
                await ShowMessageAsync($"Скопировано {table.Rows.Count} строк в буфер обмена!");
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

    private void ShowError(string message)
    {
        Dispatcher.UIThread.Post(async () =>
        {
            await ShowMessageAsync(message, "Ошибка");
        });
    }
}

public static class TextMatcher
{
    public static bool Matches(string text, string pattern)
    {
        if (string.IsNullOrEmpty(text)) return false;
        return System.Text.RegularExpressions.Regex.IsMatch(text, $"(?i){pattern}");
    }
}