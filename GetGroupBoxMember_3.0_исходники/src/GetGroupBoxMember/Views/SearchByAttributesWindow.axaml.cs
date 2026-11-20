using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using GetGroupBoxMember.Services;
using GetGroupBoxMember.Views.Controls;
using System;
using System.Collections.ObjectModel;
using System.Data;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views;

public partial class SearchByAttributesWindow : WindowBase
{
    private readonly IADService _adService;
    private CancellationTokenSource? _cts;
    private DataTable? _fullResult;
    private const int PageSize = 500;
    private int _currentPage = 1;
    private int _totalPages = 1;
    private bool _schemaLoaded = false;

    public SearchByAttributesWindow()
    {
        InitializeComponent();
        _adService = new ADService();
        Opened += OnWindowOpened;
    }

    private async void OnWindowOpened(object? sender, EventArgs e)
    {
        AttributeValueBox?.Focus();
        if (!_schemaLoaded)
        {
            _schemaLoaded = true;
            try
            {
                var attributes = await _adService.GetSchemaAttributesAsync();
                await Dispatcher.UIThread.InvokeAsync(() =>
                {
                    AttributeComboBox.ItemsSource = attributes;
                    if (attributes.Count > 0)
                    {
                        var common = new[] { "name", "sAMAccountName", "mail", "displayName", "description",
                            "objectCategory", "objectClass", "cn", "sn", "givenName", "department",
                            "company", "title", "telephoneNumber", "mobile", "physicalDeliveryOfficeName",
                            "distinguishedName", "userPrincipalName", "objectGUID", "whenCreated", "whenChanged",
                            "lastLogon", "lastLogonTimestamp", "pwdLastSet", "userAccountControl", "operatingSystem",
                            "operatingSystemVersion", "ipv4Address", "location", "managedBy", "memberOf" };
                        var preferred = common.FirstOrDefault(c => attributes.Contains(c, StringComparer.OrdinalIgnoreCase));
                        if (preferred != null)
                            AttributeComboBox.SelectedItem = attributes.First(a => string.Equals(a, preferred, StringComparison.OrdinalIgnoreCase));
                    }
                });
            }
            catch { }
        }
    }

    private async void SearchButton_Click(object? sender, RoutedEventArgs e)
    {
        var selectedAttr = AttributeComboBox.SelectedItem?.ToString() ?? "";
        string attrValue = AttributeValueBox.Text?.Trim() ?? "";

        if (string.IsNullOrWhiteSpace(selectedAttr))
        {
            StatusText.Text = "Выберите атрибут из списка.";
            StatusText.IsVisible = true;
            return;
        }

        _cts?.Cancel();
        _cts = new CancellationTokenSource();

        LoadingOverlay.IsVisible = true;
        EmptyStateBorder.IsVisible = false;
        NoResultsText.IsVisible = false;
        MainGridTable.SetDataSource(null);
        StatusText.IsVisible = false;
        PaginationPanel.IsVisible = false;

        try
        {
            var result = await _adService.SearchByAttributeAsync(selectedAttr, attrValue, _cts.Token);

            LoadingOverlay.IsVisible = false;

            if (result.ExtendedProperties.Contains("Error"))
            {
                StatusText.Text = "Ошибка: " + result.ExtendedProperties["Error"]?.ToString();
                StatusText.IsVisible = true;
                return;
            }

            _fullResult = result;
            _currentPage = 1;

            if (result.Rows.Count == 0)
            {
                NoResultsText.IsVisible = true;
                MainGridTable.IsVisible = false;
                StatusText.Text = "Найдено записей: 0";
                StatusText.IsVisible = true;
                return;
            }

            LoadPage();
        }
        catch (OperationCanceledException)
        {
            LoadingOverlay.IsVisible = false;
        }
        catch (Exception ex)
        {
            LoadingOverlay.IsVisible = false;
            StatusText.Text = "Ошибка: " + ex.Message;
            StatusText.IsVisible = true;
        }
    }

    private void LoadPage()
    {
        if (_fullResult == null || _fullResult.Rows.Count == 0) return;

        _totalPages = (_fullResult.Rows.Count + PageSize - 1) / PageSize;
        if (_currentPage < 1) _currentPage = 1;
        if (_currentPage > _totalPages) _currentPage = _totalPages;

        int start = (_currentPage - 1) * PageSize;
        int count = Math.Min(PageSize, _fullResult.Rows.Count - start);

        var pageDt = _fullResult.Clone();
        for (int i = start; i < start + count; i++)
        {
            pageDt.ImportRow(_fullResult.Rows[i]);
        }

        MainGridTable.IsVisible = true;
        MainGridTable.SetDataSource(pageDt);
        MainGridTable.RebuildTable();

        int fromRow = start + 1;
        int toRow = start + count;
        StatusText.Text = $"Найдено записей: {_fullResult.Rows.Count} | Страница {_currentPage}/{_totalPages} ({fromRow}-{toRow})";
        StatusText.IsVisible = true;

        PaginationPanel.IsVisible = _totalPages > 1;
        PageInfoText.Text = $"Страница {_currentPage} из {_totalPages}";
        PrevPageBtn.IsEnabled = _currentPage > 1;
        NextPageBtn.IsEnabled = _currentPage < _totalPages;
    }

    private void PrevPage_Click(object? sender, RoutedEventArgs e)
    {
        if (_currentPage > 1)
        {
            _currentPage--;
            LoadPage();
        }
    }

    private void NextPage_Click(object? sender, RoutedEventArgs e)
    {
        if (_currentPage < _totalPages)
        {
            _currentPage++;
            LoadPage();
        }
    }
}
