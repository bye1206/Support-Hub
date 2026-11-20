using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Platform;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using GetGroupBoxMember.Services;
using GetGroupBoxMember.Views.Controls;
using System;
using System.Collections.ObjectModel;
using System.Data;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views;

public partial class ShowEximExchangeWindow : WindowBase
{
    private const int PageSize = 500;

    private DataTable? _originalData;
    private DataTable? _currentData;
    private int _currentPage = 1;
    private int _totalPages = 1;
    private int _totalRows = 0;
    private bool _isLoading = false;
    private List<(string dn, string cn, string description)>? _groupDetails;
    private List<(string dn, string cn, string description)>? _filteredGroupDetails;
    private HashSet<string>? _filteredAttributes;
    private bool _positionInitialized = false;
    private bool _isHierarchyMode = false;
    private bool _hideFilters = false;
    private bool _hideSearchBar = false;

    public DataTable? DataSource
    {
        get => _originalData;
        set
        {
            _groupDetails = null;

            if (value != null)
            {
            }

            if (value != null && value.ExtendedProperties.ContainsKey("GroupDetails"))
            {
                _groupDetails = value.ExtendedProperties["GroupDetails"] as List<(string dn, string cn, string description)>;
                if (_groupDetails != null && _groupDetails.Count > 0)
                {
                }
            }
            else
            {
            }

            _originalData = value;
            _currentData = value;
            Title = value?.TableName ?? "Список участников";

            if (!_dataLoaded)
            {
                LoadingOverlay.IsVisible = true;
                LoadingTextBlock.Text = "Загрузка данных...";
                MainGridTable.IsVisible = false;

                if (_positionInitialized)
                {
                    _dataLoaded = true;
                    ApplyDataWithPagination();
                }
            }
        }
    }

    private bool _dataLoaded = false;

    public ShowEximExchangeWindow(bool hideFilters = false)
    {
        InitializeComponent();
        _hideFilters = hideFilters;

        Opened += OnWindowOpened;
    }

    private async void OnWindowOpened(object? sender, EventArgs e)
    {
        if (_positionInitialized) return;
        _positionInitialized = true;
        
        if (_hideFilters)
        {
            HideGroupFilters();
        }
        

        EnsureWindowWithinScreen();

        LoadingOverlay.IsVisible = true;
        LoadingTextBlock.Text = "Загрузка данных...";
        MainGridTable.IsVisible = false;

        if (_originalData != null && !_dataLoaded)
        {
            _dataLoaded = true;
            await ApplyDataWithPagination();
        }
    }

    private void GroupSearchBox_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            GroupSearch_Click(sender, e);
            e.Handled = true;
        }
    }

    public ShowEximExchangeWindow(DataTable dataSource) : this()
    {
        DataSource = dataSource;
    }

    public ShowEximExchangeWindow(DataTable dataSource, bool isHierarchy) : this()
    {
        _isHierarchyMode = isHierarchy;
        DataSource = dataSource;

        if (_isHierarchyMode)
        {
            HideGroupFilters();
        }
    }

    public ShowEximExchangeWindow(DataTable dataSource, bool isHierarchy, bool hideFilters) : this()
    {
        _isHierarchyMode = isHierarchy;
        _hideFilters = hideFilters;
        _hideSearchBar = hideFilters;
        DataSource = dataSource;

        if (_isHierarchyMode || _hideFilters)
        {
            HideGroupFilters();
        }
        if (_hideSearchBar)
        {
            HideSearchBar();
        }
    }

    private void HideSearchBar()
    {
        if (this.FindControl<Border>("SearchBorder") is Border searchBorder)
        {
            searchBorder.IsVisible = false;
        }
    }

    private void HideGroupFilters()
    {
        if (this.FindControl<Menu>("MainMenu") is Menu menu)
        {
            foreach (var item in menu.Items)
            {
                if (item is MenuItem mi)
                {
                    var header = mi.Header?.ToString() ?? "";
                    if (header.Contains("VDI") || header.Contains("VPN") || header.Contains("Confluence") ||
                        header.Contains("T-APP") || header.Contains("INET") || header.Contains("Filenet") ||
                        header.Contains("HNAS") || header.Contains("Tag") || header.Contains("Статус пароля") ||
                        header.Contains("Убрать рассылки") || header.Contains("Сброс"))
                    {
                        mi.IsVisible = false;
                    }
                }
            }
        }
    }

    public void HideGroupFiltersMenu()
    {
        HideGroupFilters();
    }

    public async Task LoadDataAsync(Func<Action<string>, Task<DataTable>> dataLoader)
    {
        MainGridTable.IsVisible = false;
        LoadingOverlay.IsVisible = true;
        NavigationMenu.IsVisible = false;
        LoadingProgressBar.IsIndeterminate = true;

        void UpdateLoadingText(string text)
        {
            Dispatcher.UIThread.Post(() =>
            {
                if (LoadingTextBlock != null)
                    LoadingTextBlock.Text = text;
            });
        }

        try
        {
            var dt = await dataLoader(UpdateLoadingText);
            DataSource = dt;
            if (!_dataLoaded)
            {
                await ApplyDataWithPagination();
            }
        }
        finally
        {
            await Dispatcher.UIThread.InvokeAsync(() =>
            {
                LoadingOverlay.IsVisible = false;
                MainGridTable.IsVisible = true;
            });
            await Task.Delay(100);
            Dispatcher.UIThread.Post(() =>
            {
                GroupSearchBox?.Focus();
            });
        }
    }

    public async Task<DataTable?> LoadFromServiceAsync(Func<Task<DataTable>> loader)
    {
        MainGridTable.IsVisible = false;
        LoadingOverlay.IsVisible = true;
        LoadingTextBlock.Text = "Загрузка данных...";

        try
        {
            var dt = await loader();
            DataSource = dt;
            if (!_dataLoaded)
            {
                await ApplyDataWithPagination();
            }
            return dt;
        }
        finally
        {
            LoadingOverlay.IsVisible = false;
            MainGridTable.IsVisible = true;
            await Task.Delay(100);
            GroupSearchBox?.Focus();
        }
    }

    private void EnsureWindowWithinScreen()
    {
        try
        {
            var screen = Screens?.ScreenFromPoint(new PixelPoint(Position.X, Position.Y));
            if (screen == null) return;

            var bounds = screen.WorkingArea;

            double newX = Position.X;
            double newY = Position.Y;

            if (Position.X + Width > bounds.Right)
                newX = bounds.Right - Width;
            if (Position.Y + Height > bounds.Bottom)
                newY = bounds.Bottom - Height;
            if (newX < bounds.X)
                newX = bounds.X;
            if (newY < bounds.Y)
                newY = bounds.Y;

            if (Math.Abs(newX - Position.X) > 1 || Math.Abs(newY - Position.Y) > 1)
            {
                Position = new PixelPoint((int)newX, (int)newY);
            }
        }
        catch (Exception ex)
        {
        }
    }

    private async Task ApplyDataWithPagination()
    {
        
        if (_currentData == null)
        {
            MainGridTable.ColumnHeaders?.Clear();
            MainGridTable.Rows?.Clear();
            MainGridTable.RebuildTable();
            NavigationMenu.IsVisible = false;
            return;
        }

        _totalRows = _currentData.Rows.Count;
        _totalPages = Math.Max(1, (int)Math.Ceiling((double)_totalRows / PageSize));

        Dispatcher.UIThread.Post(() =>
        {
            LoadingOverlay.IsVisible = true;
            LoadingTextBlock.Text = "Загрузка данных...";
        });

        if (_totalPages > 1)
        {
            NavigationMenu.IsVisible = true;
            UpdatePageInfo();
            await ApplyPageAsync(1);
        }
        else
        {
            NavigationMenu.IsVisible = false;
            await LoadDataToGridAsync(_currentData);
        }
    }

    private async Task LoadDataToGridAsync(DataTable dt)
    {
        
        if (MainGridTable == null)
        {
            return;
        }

        var (headers, rows) = await Task.Run(() => PrepareGridData(dt));

        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            MainGridTable.ColumnHeaders = headers;
            MainGridTable.Rows = rows;
            LoadingOverlay.IsVisible = false;
            MainGridTable.IsVisible = true;
            MainGridTable.RebuildTable();
            GroupSearchBox?.Focus();
        });
    }

    private (ObservableCollection<string> headers, ObservableCollection<string[]> rows) PrepareGridData(DataTable dt)
    {
        var headers = new ObservableCollection<string>();
        var rows = new ObservableCollection<string[]>();

        bool isMailboxOrGroupBox = dt.TableName?.StartsWith("Доступ к ящикам:") == true || 
                                   dt.TableName?.StartsWith("Рассылки:") == true ||
                                   dt.TableName?.StartsWith("Участники группы:") == true;
        bool isMembersList = dt.TableName?.StartsWith("Exim:") == true || 
                             dt.TableName?.StartsWith("Exchange:") == true;
        bool isEximExchangeDiff = dt.TableName?.Contains("разница в членах") == true;
        bool isHierarchy = dt.Columns.Contains("Уровень");
        bool isVladenieIS = dt.TableName?.StartsWith("Владельцы ИС:") == true;
        bool isHistory = dt.TableName == "История запросов" && dt.Columns.Contains("Дата") && dt.Columns.Contains("Запрос");

        if (isEximExchangeDiff)
        {
            headers.Add("Присутствует в системе");
            headers.Add("Логин");
            headers.Add("ФИО");
            headers.Add("Почта");
            headers.Add("Статус УЗ");

            foreach (DataRow row in dt.Rows)
            {
                rows.Add(new string[] {
                    row["Присутствует в системе"]?.ToString() ?? "",
                    row["Логин"]?.ToString() ?? "",
                    row["ФИО"]?.ToString() ?? "",
                    row["Почта"]?.ToString() ?? "",
                    row["Статус УЗ"]?.ToString() ?? ""
                });
            }
        }
        else if (isMembersList)
        {
            headers.Add("Присутствует в системе");
            headers.Add("Логин");
            headers.Add("ФИО");
            headers.Add("Почта");
            headers.Add("Статус УЗ");

            foreach (DataRow row in dt.Rows)
            {
                rows.Add(new string[] {
                    row["Присутствует в системе"]?.ToString() ?? "",
                    row["Логин"]?.ToString() ?? "",
                    row["ФИО"]?.ToString() ?? "",
                    row["Почта"]?.ToString() ?? "",
                    row["Статус УЗ"]?.ToString() ?? ""
                });
            }
        }
        else if (isMailboxOrGroupBox)
        {
            foreach (DataColumn col in dt.Columns)
            {
                headers.Add(col.ColumnName);
            }

            foreach (DataRow row in dt.Rows)
            {
                var rowData = new List<string>();
                for (int i = 0; i < dt.Columns.Count; i++)
                {
                    rowData.Add(row[i] == DBNull.Value ? "" : row[i]?.ToString() ?? "");
                }
                rows.Add(rowData.ToArray());
            }
        }
        else if (isVladenieIS)
        {
            headers.Add("Тип");
            headers.Add("Объект");
            headers.Add("Вывод. имя");
            headers.Add("Описание");

            foreach (DataRow row in dt.Rows)
            {
                rows.Add(new string[] {
                    row["Тип"]?.ToString() ?? "",
                    row["Объект"]?.ToString() ?? "",
                    row["Вывод. имя"]?.ToString() ?? "",
                    row["Описание"]?.ToString() ?? ""
                });
            }
        }
        else if (isHierarchy)
        {
            headers.Add("Уровень");
            headers.Add("Имя");
            headers.Add("Должность");
            headers.Add("Почта");
            headers.Add("Тип");
            headers.Add("Моб. телефон");

            foreach (DataRow row in dt.Rows)
            {
                var rowData = new List<string>();
                rowData.Add(row["Уровень"]?.ToString() ?? "");
                rowData.Add(row["Имя"]?.ToString() ?? "");
                rowData.Add(row["Должность"]?.ToString() ?? "");
                rowData.Add(row["Почта"]?.ToString() ?? "");
                rowData.Add(row["Тип"]?.ToString() ?? "");
                rowData.Add(row["Моб. телефон"]?.ToString() ?? "");
                rows.Add(rowData.ToArray());
            }
        }
        else if (isHistory)
        {
            foreach (DataColumn col in dt.Columns)
            {
                headers.Add(col.ColumnName);
            }

            foreach (DataRow row in dt.Rows)
            {
                var rowData = new List<string>();
                for (int i = 0; i < dt.Columns.Count; i++)
                {
                    rowData.Add(row[i] == DBNull.Value ? "" : row[i]?.ToString() ?? "");
                }
                rows.Add(rowData.ToArray());
            }
        }
        else
        {
            headers.Add("Атрибут");
            headers.Add("Значение");
            headers.Add("Описание");

            bool groupFilterApplied = _filteredGroupDetails != null;
            bool attrFilterApplied = _filteredAttributes != null;
            string[] attrsToShowWhenGroupFiltered = { "Вывод. имя", "Логин" };

            foreach (DataRow row in dt.Rows)
            {
                for (int i = 0; i < dt.Columns.Count; i++)
                {
                    var attrName = dt.Columns[i].ColumnName;
                    var attrValue = row[i] == DBNull.Value ? "" : row[i]?.ToString() ?? "";

                    if (attrName == "Состоит в группах")
                    {
                        if (groupFilterApplied)
                        {
                            if (_filteredGroupDetails != null && _filteredGroupDetails.Count > 0)
                            {
                                foreach (var group in _filteredGroupDetails)
                                {
                                    if (attrFilterApplied && !_filteredAttributes!.Contains("Состоит в группах"))
                                        continue;
                                    rows.Add(new string[] { "Состоит в группах", group.cn, group.description ?? "" });
                                }
                            }
                        }
                        else
                        {
                            var groupsToShow = _groupDetails;
                            if (groupsToShow != null && groupsToShow.Count > 0)
                            {
                                foreach (var group in groupsToShow)
                                {
                                    if (attrFilterApplied && !_filteredAttributes!.Contains("Состоит в группах"))
                                        continue;
                                    rows.Add(new string[] { "Состоит в группах", group.cn, group.description ?? "" });
                                }
                            }
                        }
                    }
                    else
                    {
                        if (attrName.Equals("Photo", StringComparison.OrdinalIgnoreCase)) continue;

                        if (attrFilterApplied)
                        {
                            if (_filteredAttributes!.Contains(attrName) && !string.IsNullOrWhiteSpace(attrValue))
                            {
                                rows.Add(new string[] { attrName, attrValue, "" });
                            }
                        }
                        else if (groupFilterApplied)
                        {
                            if (attrsToShowWhenGroupFiltered.Contains(attrName) && !string.IsNullOrWhiteSpace(attrValue))
                            {
                                rows.Add(new string[] { attrName, attrValue, "" });
                            }
                        }
                        else
                        {
                            rows.Add(new string[] { attrName, attrValue, "" });
                        }
                    }
                }
            }
        }
        
        return (headers, rows);
    }

    private async Task ApplyPageAsync(int page)
    {
        if (_currentData == null) return;

        _currentPage = Math.Max(1, Math.Min(page, _totalPages));

        int startIndex = (_currentPage - 1) * PageSize;
        int count = Math.Min(PageSize, _totalRows - startIndex);

        var pageData = _currentData.Clone();

        for (int i = startIndex; i < startIndex + count && i < _currentData.Rows.Count; i++)
        {
            pageData.ImportRow(_currentData.Rows[i]);
        }

        await LoadDataToGridAsync(pageData);
        UpdatePageInfo();
    }

    private void ApplyPage(int page)
    {
        _ = ApplyPageAsync(page);
    }

    private void UpdatePageInfo()
    {
        int startRow = (_currentPage - 1) * PageSize + 1;
        int endRow = Math.Min(_currentPage * PageSize, _totalRows);
        PageInfoMenuItem.Header = $"Страница {_currentPage} из {_totalPages} ({startRow}-{endRow} из {_totalRows})";
    }

    private void ApplyFilter(string filterType)
    {
        if (_originalData == null || _originalData.Rows.Count == 0) return;

        bool isInfoWindow = _originalData.Rows.Count == 1 && !_originalData.Columns.Contains("Уровень");

        if (isInfoWindow)
        {
            if (filterType == "PasswordStatus")
            {
                ApplyPasswordStatusFilterForInfo();
                return;
            }
            else if (filterType == "RemoveDistribution")
            {
                ApplyRemoveDistributionFilterForInfo();
                return;
            }
        }

        if (!_originalData.Columns.Contains("Атрибут") || !_originalData.Columns.Contains("Значение"))
        {
            return;
        }

        DataRow[] filteredRows = filterType switch
        {
            "VDI" => FilterByGroupPrefix(new[] { "VDI_" }),
            "VPN" => FilterByGroupPrefix(new[] { "vpn_", "VPN_" }),
            "Confluence" => FilterByGroupPrefix(new[] { "confl_" }),
            "TAPP" => FilterByGroupPrefix(new[] { "T-APP_" }),
            "INET" => FilterByGroupPrefix(new[] { "inet_", "INET_" }),
            "Filenet" => FilterByGroupPrefix(new[] { "filenet_", "Filenet_" }),
            "HNAS" => FilterByGroupPrefix(new[] { "NAS_" }),
            "TAG" => FilterByGroupPrefix(new[] { "tag_", "TAG_" }),
            "PasswordStatus" => FilterByPasswordStatus(),
            "RemoveDistribution" => FilterRemoveDistribution(),
            _ => Array.Empty<DataRow>()
        };

        if (filteredRows.Length > 0)
        {
            var headerRows = _originalData.AsEnumerable()
                .Where(r => {
                    var attr = r["Атрибут"]?.ToString();
                    return !string.IsNullOrEmpty(attr) &&
                           (attr.Equals("Логин", StringComparison.OrdinalIgnoreCase) ||
                            attr.Equals("Вывод. имя", StringComparison.OrdinalIgnoreCase));
                }).ToList();

            var filteredDT = filteredRows.CopyToDataTable();

            if (headerRows.Count > 0)
            {
                var resultDT = _originalData.Clone();
                foreach (var row in headerRows)
                {
                    resultDT.ImportRow(row);
                }
                foreach (DataRow row in filteredDT.Rows)
                {
                    resultDT.ImportRow(row);
                }
                _currentData = resultDT;
            }
            else
            {
                _currentData = filteredDT;
            }
            _currentData.TableName = _originalData.TableName + $" ({GetFilterName(filterType)})";
        }
        else
        {
            _currentData = _originalData.Clone();
        }
        ApplyDataWithPagination();
    }

    private void ApplyPasswordStatusFilterForInfo()
    {
        _filteredAttributes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Логин",
            "Вывод. имя",
            "Пароль изменён",
            "Пароль истекает",
            "Требовать смену пароля"
        };

        _filteredGroupDetails = null;


        _currentData = _originalData;
        _currentData.TableName = (_originalData.TableName ?? "Данные") + " (Статус пароля)";
        ApplyDataWithPagination();
    }

    private void ApplyRemoveDistributionFilterForInfo()
    {
        _filteredAttributes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Логин",
            "Вывод. имя",
            "Состоит в группах"
        };

        _filteredGroupDetails = _groupDetails?
            .Where(g => !g.cn.EndsWith("_dg", StringComparison.OrdinalIgnoreCase))
            .ToList();


        _currentData = _originalData;
        _currentData.TableName = (_originalData.TableName ?? "Данные") + " (Без рассылок)";
        ApplyDataWithPagination();
    }

    private void ApplyNameFilter(string groupName)
    {
        if (_originalData == null || _originalData.Rows.Count == 0) return;

        bool isInfoWindow = _originalData.Rows.Count == 1 && !_originalData.Columns.Contains("Уровень");

        if (isInfoWindow && _groupDetails != null)
        {
            _filteredGroupDetails = _groupDetails
                .Where(g => g.cn.IndexOf(groupName, StringComparison.OrdinalIgnoreCase) >= 0)
                .ToList();


            _currentData = _originalData;
            _currentData.TableName = (_originalData.TableName ?? "Данные") + $" (Поиск: {groupName})";
            ApplyDataWithPagination();
            return;
        }

        if (!_originalData.Columns.Contains("Атрибут") || !_originalData.Columns.Contains("Значение"))
        {
            return;
        }

        var filteredRows = _originalData.AsEnumerable()
            .Where(r => {
                var attr = r["Атрибут"]?.ToString();
                if (string.IsNullOrEmpty(attr) || !attr.Equals("состоит в группах", StringComparison.OrdinalIgnoreCase))
                    return false;
                var value = r["Значение"]?.ToString();
                if (string.IsNullOrEmpty(value)) return false;
                string[] groupList = value.Split('|');
                return groupList.Any(g => g.Trim().IndexOf(groupName, StringComparison.OrdinalIgnoreCase) >= 0);
            }).ToArray();

        if (filteredRows.Length > 0)
        {
            _currentData = filteredRows.CopyToDataTable();
            _currentData.TableName = _originalData.TableName + $" (Поиск: {groupName})";
        }
        else
        {
            _currentData = _originalData.Clone();
        }
        ApplyDataWithPagination();
    }

    private string[] GetPrefixesForFilter(string filterType) => filterType switch
    {
        "VDI" => new[] { "VDI_" },
        "VPN" => new[] { "vpn_", "VPN_" },
        "Confluence" => new[] { "confl_" },
        "TAPP" => new[] { "T-APP_" },
        "INET" => new[] { "inet_", "INET_" },
        "Filenet" => new[] { "filenet_", "Filenet_" },
        "HNAS" => new[] { "NAS_" },
        "TAG" => new[] { "tag_", "TAG_" },
        _ => Array.Empty<string>()
    };

    private DataRow[] FilterByGroupPrefix(string[] prefixes)
    {
        var result = new List<DataRow>();

        foreach (DataRow row in _originalData!.Rows)
        {
            var attr = row["Атрибут"]?.ToString();
            if (string.IsNullOrEmpty(attr) || !attr.Equals("состоит в группах", StringComparison.OrdinalIgnoreCase))
                continue;

            var value = row["Значение"]?.ToString() ?? "";
            if (string.IsNullOrEmpty(value)) continue;

            var groupDns = value.Split('|', StringSplitOptions.RemoveEmptyEntries);
            foreach (var groupDn in groupDns)
            {
                var cn = GetCNFromDN(groupDn);
                if (prefixes.Any(p => cn.StartsWith(p, StringComparison.OrdinalIgnoreCase)))
                {
                    result.Add(row);
                    break;
                }
            }
        }

        return result.ToArray();
    }

    private DataRow[] FilterByPasswordStatus()
    {
        var result = new List<DataRow>();
        var attrColumn = "Атрибут";

        foreach (DataRow row in _originalData!.Rows)
        {
            var attr = row[attrColumn]?.ToString();
            if (string.IsNullOrEmpty(attr)) continue;

            if (attr.Equals("Требовать смену пароля", StringComparison.OrdinalIgnoreCase) ||
                attr.Equals("Пароль изменён", StringComparison.OrdinalIgnoreCase) ||
                attr.Equals("Пароль истекает", StringComparison.OrdinalIgnoreCase))
            {
                var value = row["Значение"]?.ToString() ?? "";
                if (!string.IsNullOrEmpty(value) && !result.Contains(row))
                {
                    result.Add(row);
                }
            }
        }

        return result.ToArray();
    }

    private DataRow[] FilterRemoveDistribution()
    {
        var result = new List<DataRow>();

        foreach (DataRow row in _originalData!.Rows)
        {
            var attr = row["Атрибут"]?.ToString();
            if (string.IsNullOrEmpty(attr) || !attr.Equals("состоит в группах", StringComparison.OrdinalIgnoreCase))
                continue;

            var value = row["Значение"]?.ToString() ?? "";
            if (string.IsNullOrEmpty(value)) continue;

            var groupDns = value.Split('|', StringSplitOptions.RemoveEmptyEntries);
            bool hasDistributionGroup = false;

            foreach (var groupDn in groupDns)
            {
                var cn = GetCNFromDN(groupDn);
                if (cn.EndsWith("_dg", StringComparison.OrdinalIgnoreCase) ||
                    System.Text.RegularExpressions.Regex.IsMatch(cn, @"_dg-.+$", System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                {
                    hasDistributionGroup = true;
                    break;
                }
            }

            if (!hasDistributionGroup)
            {
                result.Add(row);
            }
        }

        return result.ToArray();
    }

    private string GetCNFromDN(string dn)
    {
        if (string.IsNullOrEmpty(dn)) return "";

        var parts = dn.Split(',');
        foreach (var part in parts)
        {
            if (part.Trim().StartsWith("CN=", StringComparison.OrdinalIgnoreCase))
            {
                return part.Trim().Substring(3);
            }
        }
        return dn;
    }

    private string GetFilterName(string filterType)
    {
        return filterType switch
        {
            "VDI" => "VDI",
            "VPN" => "VPN",
            "Confluence" => "Confluence",
            "TAPP" => "T-APP",
            "INET" => "INET",
            "Filenet" => "Filenet",
            "HNAS" => "HNAS",
            "TAG" => "Тег",
            "PasswordStatus" => "Статус пароля",
            "RemoveDistribution" => "Без рассылок",
            _ => filterType
        };
    }

    private void Search_Click(object? sender, RoutedEventArgs e)
    {
    }

    private void GroupSearch_Click(object? sender, RoutedEventArgs e)
    {
        if (_originalData == null || GroupSearchBox == null) return;

        var inputText = GroupSearchBox.Text ?? string.Empty;
        if (!string.IsNullOrWhiteSpace(inputText))
        {
            ApplySearchFilter(inputText);
        }
    }

    private void ApplySearchFilter(string filter)
    {
        if (_originalData == null) return;


        var filtered = _originalData.AsEnumerable()
            .Where(r =>
            {
                foreach (DataColumn col in _originalData.Columns)
                {
                    var val = r[col]?.ToString() ?? "";
                    if (val.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0)
                        return true;
                }
                return false;
            }).ToList();


        if (filtered.Any())
        {
            _currentData = filtered.CopyToDataTable();
            _currentData.TableName = _originalData.TableName + " (Поиск)";
        }
        else
        {
            _currentData = _originalData.Clone();
        }
        ApplyDataWithPagination();
    }

    private void ClearSearch_Click(object? sender, RoutedEventArgs e)
    {
        _currentData = _originalData;
        if (_currentData != null)
        {
            _currentData.TableName = _originalData?.TableName ?? "Данные";
        }
        ApplyDataWithPagination();
    }

    private void FilterVDI_Click(object? sender, RoutedEventArgs e) => ApplyFilter("VDI");
    private void FilterVPN_Click(object? sender, RoutedEventArgs e) => ApplyFilter("VPN");
    private void FilterConfluence_Click(object? sender, RoutedEventArgs e) => ApplyFilter("Confluence");
    private void FilterTAPP_Click(object? sender, RoutedEventArgs e) => ApplyFilter("TAPP");
    private void FilterINET_Click(object? sender, RoutedEventArgs e) => ApplyFilter("INET");
    private void FilterFilenet_Click(object? sender, RoutedEventArgs e) => ApplyFilter("Filenet");
    private void FilterHNAS_Click(object? sender, RoutedEventArgs e) => ApplyFilter("HNAS");
    private void FilterTag_Click(object? sender, RoutedEventArgs e) => ApplyFilter("TAG");
    private void FilterPassword_Click(object? sender, RoutedEventArgs e) => ApplyFilter("PasswordStatus");

    private void FilterInfoVDI_Click(object? sender, RoutedEventArgs e) => ApplyInfoGroupFilter("VDI");
    private void FilterInfoVPN_Click(object? sender, RoutedEventArgs e) => ApplyInfoGroupFilter("VPN");
    private void FilterInfoConfluence_Click(object? sender, RoutedEventArgs e) => ApplyInfoGroupFilter("Confluence");
    private void FilterInfoTAPP_Click(object? sender, RoutedEventArgs e) => ApplyInfoGroupFilter("TAPP");
    private void FilterInfoINET_Click(object? sender, RoutedEventArgs e) => ApplyInfoGroupFilter("INET");
    private void FilterInfoFilenet_Click(object? sender, RoutedEventArgs e) => ApplyInfoGroupFilter("Filenet");
    private void FilterInfoHNAS_Click(object? sender, RoutedEventArgs e) => ApplyInfoGroupFilter("HNAS");
    private void FilterInfoTag_Click(object? sender, RoutedEventArgs e) => ApplyInfoGroupFilter("TAG");

    private void ApplyInfoGroupFilter(string filterType)
    {
        if (_originalData == null || _groupDetails == null) return;

        var prefixes = GetPrefixesForFilter(filterType);
        if (prefixes.Length == 0) return;

        _filteredGroupDetails = _groupDetails
            .Where(g => prefixes.Any(p => g.cn.StartsWith(p, StringComparison.OrdinalIgnoreCase)))
            .ToList();


        _currentData = _originalData;
        _currentData.TableName = (_originalData.TableName ?? "Данные") + $" ({GetFilterName(filterType)})";
        ApplyDataWithPagination();
    }
    private void FilterRemoveDistribution_Click(object? sender, RoutedEventArgs e) => ApplyFilter("RemoveDistribution");

    private void ResetFilter_Click(object? sender, RoutedEventArgs e)
    {
        _filteredGroupDetails = null;
        _filteredAttributes = null;
        _currentData = _originalData;
        if (_currentData != null)
        {
            _currentData.TableName = _originalData?.TableName ?? "Данные";
        }
        ApplyDataWithPagination();
    }

    private void PrevPage_Click(object? sender, RoutedEventArgs e)
    {
        if (_currentPage > 1)
            ApplyPage(_currentPage - 1);
    }

    private void NextPage_Click(object? sender, RoutedEventArgs e)
    {
        if (_currentPage < _totalPages)
            ApplyPage(_currentPage + 1);
    }

    private string[] GetExportHeaders(DataTable dt)
    {
        bool isMailboxOrGroupBox = dt.TableName?.StartsWith("Доступ к ящикам:") == true || 
                                   dt.TableName?.StartsWith("Рассылки:") == true ||
                                   dt.TableName?.StartsWith("Участники группы:") == true;
        bool isMembersList = dt.TableName?.StartsWith("Exim:") == true || 
                             dt.TableName?.StartsWith("Exchange:") == true;
        bool isHierarchy = dt.Columns.Contains("Уровень");
        bool isVladenieIS = dt.TableName?.StartsWith("Владельцы ИС:") == true;
        bool isHistory = dt.TableName == "История запросов" && dt.Columns.Contains("Дата") && dt.Columns.Contains("Запрос");

        if (isMembersList)
            return new[] { "Присутствует в системе", "Логин", "ФИО", "Почта", "Статус УЗ" };
        if (isMailboxOrGroupBox || isHistory)
            return dt.Columns.Cast<DataColumn>().Select(c => c.ColumnName).ToArray();
        if (isVladenieIS)
            return new[] { "Тип", "Объект", "Вывод. имя", "Описание" };
        if (isHierarchy)
            return new[] { "Уровень", "Имя", "Должность", "Почта", "Тип", "Моб. телефон" };
        return new[] { "Атрибут", "Значение", "Описание" };
    }

    private async void ExportXlsx_Click(object? sender, RoutedEventArgs e)
    {
        var exportData = _currentData ?? _originalData;
        if (exportData == null || exportData.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var filteredExport = exportData.AsEnumerable()
            .Where(r =>
            {
                if (exportData.Columns.Contains("Атрибут"))
                {
                    var attr = r["Атрибут"]?.ToString();
                    return attr != "@black@";
                }
                return true;
            }).ToList();

        if (!filteredExport.Any())
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var topLevel = GetTopLevel(this);
        if (topLevel == null) return;

        var fileName = exportData.TableName ?? "Export";
        if (fileName.Contains(":"))
            fileName = fileName.Remove(fileName.IndexOf(":"));

        var entityName = filteredExport
            .Select(r => r["Логин"]?.ToString() ?? r["Вывод. имя"]?.ToString())
            .FirstOrDefault(n => !string.IsNullOrWhiteSpace(n));
        if (!string.IsNullOrWhiteSpace(entityName))
            fileName = $"{fileName} {entityName}";

        IStorageFile? file = null;
        try
        {
            file = await topLevel.StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "Экспорт в Excel",
                SuggestedFileName = FileDialogHelper.SanitizeFileName(fileName),
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
            var exportTable = filteredExport.CopyToDataTable();
            var log = new ExcelLog(file.Path.LocalPath);
            var ex = await Task.Run(() => log.WriteXlsx(exportTable, GetExportHeaders(exportTable)));
            if (ex != null)
                await ShowMessageAsync(ex.Message);
            else
                await ShowMessageAsync("Успешно!");
        }
    }

    private async void ExportTxt_Click(object? sender, RoutedEventArgs e)
    {
        var exportData = _currentData ?? _originalData;
        if (exportData == null || exportData.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var filteredExport = exportData.AsEnumerable()
            .Where(r =>
            {
                if (exportData.Columns.Contains("Атрибут"))
                {
                    var attr = r["Атрибут"]?.ToString();
                    return attr != "@black@";
                }
                return true;
            }).ToList();

        if (!filteredExport.Any())
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var exportTable = filteredExport.CopyToDataTable();
        var topLevel = GetTopLevel(this);
        if (topLevel == null) return;

        var fileName = exportData.TableName ?? "Export";
        if (fileName.Contains(":"))
            fileName = fileName.Remove(fileName.IndexOf(":"));

        IStorageFile? file = null;
        try
        {
            file = await topLevel.StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "Экспорт в текст",
                SuggestedFileName = FileDialogHelper.SanitizeFileName(fileName),
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
            var ex = await Task.Run(() => log.WriteTxt(exportTable));
            if (ex != null)
                await ShowMessageAsync(ex.Message);
            else
                await ShowMessageAsync("Успешно!");
        }
    }

    protected override void OnClosing(WindowClosingEventArgs e)
    {
        _originalData?.Dispose();
        _currentData?.Dispose();
        base.OnClosing(e);
    }

    private async void CopyToClipboard_Click(object? sender, RoutedEventArgs e)
    {
        if (MainGridTable?.ColumnHeaders == null || MainGridTable?.Rows == null || 
            MainGridTable.ColumnHeaders.Count == 0 || MainGridTable.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для копирования.");
            return;
        }

        try
        {
            var sb = new System.Text.StringBuilder();
            
            for (int i = 0; i < MainGridTable.ColumnHeaders.Count; i++)
            {
                sb.Append(MainGridTable.ColumnHeaders[i]);
                if (i < MainGridTable.ColumnHeaders.Count - 1)
                    sb.Append('\t');
            }
            sb.AppendLine();

            foreach (var row in MainGridTable.Rows)
            {
                for (int i = 0; i < row.Length; i++)
                {
                    var val = row[i]?.Replace("\r", "").Replace("\n", " ").Replace("\t", " ") ?? "";
                    sb.Append(val);
                    if (i < row.Length - 1)
                        sb.Append('\t');
                }
                sb.AppendLine();
            }

            var topLevel = GetTopLevel(this);
            if (topLevel?.Clipboard != null)
            {
                await topLevel.Clipboard.SetTextAsync(sb.ToString());
                await ShowMessageAsync($"Скопировано {MainGridTable.Rows.Count} строк в буфер обмена!");
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
            Content = new StackPanel
            {
                Spacing = 16,
                Margin = new Thickness(20),
                VerticalAlignment = VerticalAlignment.Center,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap, HorizontalAlignment = HorizontalAlignment.Center },
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