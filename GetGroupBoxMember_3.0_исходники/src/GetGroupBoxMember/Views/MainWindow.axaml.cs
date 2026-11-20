using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Threading;
using Avalonia.VisualTree;
using GetGroupBoxMember.ViewModels;
using GetGroupBoxMember.Views.Controls;
using Avalonia.Platform;
using Avalonia;
using GetGroupBoxMember.Models;
using GetGroupBoxMember.Services;
using System.Diagnostics;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views;

public partial class MainWindow : WindowBase
{
    protected override bool CloseOnCtrlW => false;

    private TextBox? _searchBox;
    private Panel? _commandPaletteOverlay;
    private CommandPaletteView? _commandPalette;
    private ListBox? _searchResultsListBox;

    public MainWindow()
    {
        InitializeComponent();

        DataContext = new MainWindowViewModel();

        AddHandler(KeyDownEvent, OnKeyDown, RoutingStrategies.Tunnel);

        _searchBox = this.FindControl<TextBox>("SearchBox");
        _commandPaletteOverlay = this.FindControl<Panel>("CommandPaletteOverlay");
        _commandPalette = this.FindControl<CommandPaletteView>("CommandPalette");
        _searchResultsListBox = this.FindControl<ListBox>("SearchResultsListBox");

        if (_commandPalette != null)
        {
            _commandPalette.SetSearchProvider(async (query, token) =>
            {
                var result = await SearchUsersAsync(query, token);
                return result.AsEnumerable();
            });
            _commandPalette.RegisterActions(GetDefaultActions());
            _commandPalette.Closed += (s, e) => IsCommandPaletteOpen = false;
        }

        if (DataContext is MainWindowViewModel vm)
        {
            vm.PropertyChanged += (s, e) =>
            {
                if (e.PropertyName == nameof(MainWindowViewModel.IsCommandPaletteOpen))
                {
                    if (vm.IsCommandPaletteOpen)
                    {
                        _ = ShowCommandPaletteAsync();
                    }
                    else
                    {
                        HideCommandPalette();
                    }
                }
            };
        }

        Opened += (_, _) =>
        {
            ApplyThemeColors();
            _searchBox?.Focus();
        };

        ThemeService.Instance.ThemeChanged += OnMainWindowThemeChanged;
    }

    private void OnMainWindowThemeChanged(object? sender, (AppTheme Theme, ThemeColors Colors) args)
    {
        UpdateControlColors(this);
    }

    private bool _isCommandPaletteOpen;
    public bool IsCommandPaletteOpen
    {
        get => _isCommandPaletteOpen;
        set
        {
            if (_isCommandPaletteOpen != value)
            {
                _isCommandPaletteOpen = value;
                if (_commandPaletteOverlay != null)
                    _commandPaletteOverlay.IsVisible = value;
            }
        }
    }

    private List<Models.CommandPaletteItem> GetDefaultActions()
    {
        return new List<Models.CommandPaletteItem>
        {
            new Models.CommandPaletteItem
            {
                Title = "Быстрый поиск пользователей",
                Description = "Найти пользователя по логину, почте, телефону...",
                Category = "Поиск",
                Icon = "🔍",
                ActionType = Models.CommandPaletteActionType.Action,
                Argument = "search"
            },
            new Models.CommandPaletteItem
            {
                Title = "Открыть настройки",
                Description = "Настройки приложения",
                Category = "Действия",
                Icon = "⚙",
                ActionType = Models.CommandPaletteActionType.Action,
                Argument = "settings"
            },
            new Models.CommandPaletteItem
            {
                Title = "История поиска",
                Description = "Просмотр истории поисковых запросов",
                Category = "Действия",
                Icon = "📜",
                ActionType = Models.CommandPaletteActionType.Action,
                Argument = "history"
            },
            new Models.CommandPaletteItem
            {
                Title = "Сравнение групп",
                Description = "Сравнить содержимое двух групп",
                Category = "Действия",
                Icon = "🔄",
                ActionType = Models.CommandPaletteActionType.Action,
                Argument = "compare"
            },
            new Models.CommandPaletteItem
            {
                Title = "Exchange меню",
                Description = "Операции с Exchange",
                Category = "Действия",
                Icon = "📬",
                ActionType = Models.CommandPaletteActionType.Action,
                Argument = "exchange"
            },
            new Models.CommandPaletteItem
            {
                Title = "О программе",
                Description = "Информация о приложении",
                Category = "Действия",
                Icon = "ℹ",
                ActionType = Models.CommandPaletteActionType.Action,
                Argument = "about"
            }
        };
    }

    private async Task<List<Models.CommandPaletteItem>> SearchUsersAsync(string query, CancellationToken token)
    {
        var results = new List<Models.CommandPaletteItem>();

        if (DataContext is MainWindowViewModel vm)
        {
            try
            {
                var searchResults = await vm.PerformQuickSearchAsync(query, token);
                foreach (var item in searchResults)
                {
                    results.Add(new Models.CommandPaletteItem
                    {
                        Title = item.Login ?? string.Empty,
                        Description = $"{item.DisplayName} | {item.Email}",
                        Category = "Пользователи",
                        Icon = "👤",
                        ActionType = Models.CommandPaletteActionType.Search,
                        SearchQuery = item.Login,
                        Argument = item.Login
                    });
                }
            }
            catch (OperationCanceledException) { }
        }

        return results;
    }

    private async Task ShowCommandPaletteAsync()
    {
        if (_commandPalette != null)
        {
            _commandPalette.RegisterActions(GetDefaultActions());
            await _commandPalette.ShowAsync();
        }
    }

    private void HideCommandPalette()
    {
        if (_commandPalette != null)
        {
            _commandPalette.Hide();
        }
    }

    private void SearchResultsOverlay_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (DataContext is MainWindowViewModel vm && _searchResultsListBox != null)
        {
            var src = e.Source as Control;
            bool isOnList = false;
            while (src != null)
            {
                if (src == _searchResultsListBox)
                {
                    isOnList = true;
                    break;
                }
                src = src.Parent as Control;
            }
            if (!isOnList)
            {
                vm.IsListVisible = false;
            }
        }
    }

    private void SearchResultsListBox_OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (_searchResultsListBox?.SelectedItem is Models.SearchResultItem item)
        {
            if (item.IsPlaceholder)
            {
                _searchResultsListBox.SelectedIndex = -1;
                if (DataContext is MainWindowViewModel vm)
                {
                    vm.SelectedSearchResult = null;
                    vm.ClearForm();
                }
            }
            else if (DataContext is MainWindowViewModel vm)
            {
                vm.SelectedSearchResult = item;
            }
        }
    }

    private void SearchResultsListBox_OnDoubleTapped(object? sender, TappedEventArgs e)
    {
        if (_searchResultsListBox?.SelectedItem is Models.SearchResultItem item && !item.IsPlaceholder)
        {
            if (DataContext is MainWindowViewModel vm)
            {
                _ = vm.OpenSelectedUserInfoAsync();
            }
        }
    }

    private void SearchBox_TextChanged(object? sender, RoutedEventArgs e)
    {
    }

    private void SearchBox_GotFocus(object? sender, RoutedEventArgs e)
    {
        var text = _searchBox?.Text ?? "";
        Dispatcher.UIThread.Post(async () =>
        {
            await Task.Delay(150);
            if (_searchBox != null && DataContext is MainWindowViewModel vm)
            {
                var currentText = _searchBox.Text ?? "";
                if (currentText != text && vm.SearchText != currentText)
                {
                    vm.SearchText = currentText;
                }
            }
        });
    }

    private void SearchBox_LostFocus(object? sender, RoutedEventArgs e)
    {
    }

    private void OnKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.K && (e.KeyModifiers & KeyModifiers.Control) != 0)
        {
            if (DataContext is MainWindowViewModel mainVm)
            {
                mainVm.IsCommandPaletteOpen = true;
            }
            e.Handled = true;
            return;
        }

        if (IsCommandPaletteOpen)
        {
            if (e.Key == Key.Escape)
            {
                IsCommandPaletteOpen = false;
                e.Handled = true;
            }
            return;
        }

        if (e.Key == Key.System && (e.KeyModifiers & KeyModifiers.Shift) != 0 && (e.KeyModifiers & KeyModifiers.Alt) != 0)
        {
            if (_searchBox != null && _searchBox.IsFocused)
            {
                Dispatcher.UIThread.Post(() =>
                {
                    _searchBox.Focus();
                    _searchBox.CaretIndex = _searchBox.Text?.Length ?? 0;
                }, DispatcherPriority.Input + 1);
            }
            return;
        }

        if (DataContext is not MainWindowViewModel viewModel) return;

        switch (e.Key)
        {
            case Key.Escape:
                viewModel.IsListVisible = false;
                e.Handled = true;
                break;

            case Key.Enter:
                if (viewModel.IsListVisible)
                {
                    if (viewModel.SelectedSearchResult != null && !viewModel.SelectedSearchResult.IsPlaceholder)
                    {
                        viewModel.SelectedUser = null;
                    }
                    else if (_searchResultsListBox?.ItemCount > 0)
                    {
                        _searchResultsListBox.Focus();
                        _searchResultsListBox.SelectedIndex = 0;
                    }
                }
                e.Handled = true;
                break;

            case Key.Down:
                if (viewModel.IsListVisible)
                {
                    _searchResultsListBox?.Focus();
                    if (_searchResultsListBox?.SelectedIndex < 0 && _searchResultsListBox?.ItemCount > 0)
                        _searchResultsListBox.SelectedIndex = 0;
                    e.Handled = true;
                }
                break;

            case Key.Up:
                if (viewModel.IsListVisible)
                {
                    _searchResultsListBox?.Focus();
                    e.Handled = true;
                }
                break;
        }
    }

    private void OnBoxesClick(object? sender, RoutedEventArgs e)
    {
        if (DataContext is MainWindowViewModel clickVm)
        {
            clickVm.GetGroupAccessCommand.Execute(null);
        }
    }

    private void OnMailingsClick(object? sender, RoutedEventArgs e)
    {
        if (DataContext is MainWindowViewModel clickVm)
        {
            clickVm.GetMailboxAccessCommand.Execute(null);
        }
    }

    private void OnBoxesPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (DataContext is MainWindowViewModel clickVm)
        {
            clickVm.GetGroupAccessCommand.Execute(null);
        }
    }

    private void OnMailingsPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (DataContext is MainWindowViewModel clickVm)
        {
            clickVm.GetMailboxAccessCommand.Execute(null);
        }
    }

    private void OnTestClick(object? sender, RoutedEventArgs e)
    {
    }

    private void AvatarBorder_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (DataContext is MainWindowViewModel vm && !string.IsNullOrWhiteSpace(vm.Mail))
        {
            var url = $"https://mail.magnit.ru/owa/service.svc/s/GetPersonaPhoto?email={Uri.EscapeDataString(vm.Mail)}&size=HR648x648";
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = url,
                    UseShellExecute = true
                };
                Process.Start(psi);
            }
            catch { }
        }
    }

    private DispatcherTimer? _copyFeedbackTimer;

    private async void TextBlock_CopyToClipboard(object? sender, PointerPressedEventArgs e)
    {
        e.Handled = true;

        string? textToCopy = null;

        if (sender is TextBlock tb && !string.IsNullOrWhiteSpace(tb.Text))
        {
            textToCopy = tb.Text;
        }
        else if (sender is Border border)
        {
            if (border.Child is TextBlock childTb && !string.IsNullOrWhiteSpace(childTb.Text))
            {
                textToCopy = childTb.Text;
            }
        }

        if (string.IsNullOrWhiteSpace(textToCopy))
            return;

        try
        {
            var topLevel = TopLevel.GetTopLevel(sender as Control);
            if (topLevel?.Clipboard is { } clipboard)
            {
                await clipboard.SetTextAsync(textToCopy);
                ShowCopyFeedback(true);
            }
            else
            {
                ShowCopyFeedback(false);
            }
        }
        catch
        {
            ShowCopyFeedback(false);
        }
    }

    private void ShowCopyFeedback(bool success)
    {
        if (CopyFeedbackText == null || CopyFeedbackBorder == null)
            return;

        CopyFeedbackText.Text = success ? "Скопировано" : "Ошибка копирования";

        if (success)
        {
            CopyFeedbackBorder.ClearValue(Border.BackgroundProperty);
        }
        else
        {
            CopyFeedbackBorder.Background = new SolidColorBrush(Colors.Firebrick);
        }

        CopyFeedbackBorder.IsVisible = true;
        CopyFeedbackBorder.Opacity = 1;

        _copyFeedbackTimer?.Stop();
        _copyFeedbackTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1800) };
        _copyFeedbackTimer.Tick += (s, args) =>
        {
            _copyFeedbackTimer?.Stop();
            _copyFeedbackTimer = null;
            CopyFeedbackBorder.Opacity = 0;
            DispatcherTimer.RunOnce(() =>
            {
                if (CopyFeedbackBorder != null)
                    CopyFeedbackBorder.IsVisible = false;
            }, TimeSpan.FromMilliseconds(250));
        };
        _copyFeedbackTimer.Start();
    }

    protected override void ApplyThemeColors()
    {
        base.ApplyThemeColors();
        UpdateControlColors(this);
    }

    private void UpdateControlColors(Control control)
    {
        if (control is Border border)
        {
            var bgColor = border.Background as SolidColorBrush;
            if (bgColor != null)
            {
                var colorStr = bgColor.Color.ToString();
                if (colorStr == "#161B22" || colorStr == "#FF161B22")
                    border.Background = (Brush)Application.Current?.FindResource("ThemeCardBackground") 
                        ?? new SolidColorBrush(Color.Parse(_themeService.CurrentColors.CardBackground));
            }
        }

        if (control is Panel panel)
        {
            foreach (var child in panel.Children)
            {
                UpdateControlColors(child);
            }
        }

        if (control is StackPanel stackPanel)
        {
            foreach (var child in stackPanel.Children)
            {
                UpdateControlColors(child);
            }
        }
    }

    private async void CommandPalette_ItemSelected(object? sender, Models.CommandPaletteItem item)
    {
        if (item == null || DataContext is not MainWindowViewModel paletteVm) return;

        switch (item.Argument)
        {
            case "search":
                IsCommandPaletteOpen = false;
                _searchBox?.Focus();
                break;

            case "settings":
                IsCommandPaletteOpen = false;
                paletteVm.OpenSettingsCommand.Execute(null);
                break;

            case "history":
                IsCommandPaletteOpen = false;
                paletteVm.HistoryCommand.Execute(null);
                break;

            case "compare":
                IsCommandPaletteOpen = false;
                paletteVm.CompareGroupsCommand.Execute(null);
                break;

            case "exchange":
                IsCommandPaletteOpen = false;
                paletteVm.ExchangeMenuCommand.Execute(null);
                break;

            case "about":
                IsCommandPaletteOpen = false;
                paletteVm.AboutCommand.Execute(null);
                break;

            default:
                if (item.ActionType == Models.CommandPaletteActionType.Search && !string.IsNullOrEmpty(item.Argument))
                {
                    IsCommandPaletteOpen = false;
                    paletteVm.SearchText = item.Argument;
                    await Task.Delay(100);
                    _searchBox?.Focus();
                }
                break;
        }
    }

    private void CommandPalette_Closed(object? sender, EventArgs e)
    {
        IsCommandPaletteOpen = false;
    }

    private void CommandPaletteOverlay_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        IsCommandPaletteOpen = false;
    }
}
