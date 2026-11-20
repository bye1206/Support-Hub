using Avalonia.Controls;
using Avalonia.Interactivity;
using GetGroupBoxMember.Services;
using GetGroupBoxMember.Views.Controls;
using System.Collections.ObjectModel;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views;

public partial class VdiFoldersWindow : WindowBase
{
    private string _login = "";

    public VdiFoldersWindow()
    {
        InitializeComponent();
    }

    public VdiFoldersWindow(string login) : this()
    {
        _login = login;
        Loaded += OnLoaded;
    }

    private async void OnLoaded(object? sender, RoutedEventArgs e)
    {
        Loaded -= OnLoaded;
        await LoadDataAsync();
    }

    private async Task LoadDataAsync()
    {
        if (string.IsNullOrEmpty(_login))
        {
            LoadingText.Text = "Логин не указан";
            return;
        }

        LoadingOverlay.IsVisible = true;
        LoadingText.Text = "Проверка наличия VDI папок...";

        await Task.Run(() => { });

        var vdiInfo = await Task.Run(() => Helpers.CheckVdiFolders(_login));

        var headers = new ObservableCollection<string> { "Имя", "UNC путь", "Статус", "Размер" };
        var rows = new ObservableCollection<string[]>();

        MainGridTable.SetUncColumn(1);

        foreach (var item in vdiInfo)
        {
            rows.Add(new[] {
                item.DisplayName,
                item.UncPath,
                item.Status,
                item.Exists ? $"{item.SizeGb:F2} ГБ" : "—"
            });
        }

        MainGridTable.ColumnHeaders = headers;
        MainGridTable.Rows = rows;
        MainGridTable.RebuildTable();

        LoadingOverlay.IsVisible = false;
    }

    private void Close_Click(object? sender, RoutedEventArgs e)
    {
        Close();
    }
}
