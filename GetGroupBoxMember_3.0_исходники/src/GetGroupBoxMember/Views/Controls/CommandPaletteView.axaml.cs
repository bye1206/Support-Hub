using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using Avalonia.VisualTree;
using GetGroupBoxMember.Models;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views.Controls;

public partial class CommandPaletteView : UserControl
{
    public static readonly StyledProperty<bool> IsOpenProperty =
        AvaloniaProperty.Register<CommandPaletteView, bool>(nameof(IsOpen), defaultValue: false);

    public static readonly StyledProperty<string> SearchTextProperty =
        AvaloniaProperty.Register<CommandPaletteView, string>(nameof(SearchText), defaultValue: string.Empty);

    public bool IsOpen
    {
        get => GetValue(IsOpenProperty);
        set => SetValue(IsOpenProperty, value);
    }

    public string SearchText
    {
        get => GetValue(SearchTextProperty);
        set => SetValue(SearchTextProperty, value);
    }

    public ObservableCollection<CommandPaletteItem> FilteredItems { get; } = new();

    private CommandPaletteItem? _selectedItem;
    public CommandPaletteItem? SelectedItem
    {
        get => _selectedItem;
        set
        {
            if (_selectedItem != value)
            {
                _selectedItem = value;
                PropertyChanged?.Invoke(this, new System.ComponentModel.PropertyChangedEventArgs(nameof(SelectedItem)));
            }
        }
    }

    public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged;

    private bool _isSelectionProgrammatic;

    public event EventHandler<CommandPaletteItem>? ItemSelected;
    public event EventHandler<string>? SearchQueryChanged;
    public event EventHandler? Closed;

    private TextBox? _searchInput;
    private ListBox? _resultsList;
    private Button? _closeButton;
    private Border? _paletteContainer;
    private ScrollViewer? _listScrollViewer;

    private readonly List<CommandPaletteItem> _allItems = new();
    private readonly List<CommandPaletteItem> _recentItems = new();
    private readonly Dictionary<string, List<CommandPaletteItem>> _searchCache = new();
    private CancellationTokenSource? _searchCts;

    private Func<string, CancellationToken, Task<IEnumerable<CommandPaletteItem>>>? _searchProvider;
    private string? _textBeforeFocusChange;

    public CommandPaletteView()
    {
        InitializeComponent();

        _searchInput = this.FindControl<TextBox>("SearchInput");
        _resultsList = this.FindControl<ListBox>("ResultsList");
        _closeButton = this.FindControl<Button>("CloseButton");
        _paletteContainer = this.FindControl<Border>("PaletteContainer");

        _searchInput?.AddHandler(InputElement.KeyDownEvent, OnSearchInputKeyDown);
        _searchInput?.AddHandler(TextInputEvent, SearchInput_TextInput, RoutingStrategies.Bubble);
        _searchInput?.AddHandler(InputElement.GotFocusEvent, SearchInput_GotFocus, RoutingStrategies.Bubble);

        if (_resultsList != null)
        {
            _resultsList.LayoutUpdated += OnResultsListLayoutUpdated;
            _resultsList.SizeChanged += OnResultsListSizeChanged;
        }

        if (_paletteContainer != null)
        {
            _paletteContainer.LayoutUpdated += OnPaletteLayoutUpdated;
            _paletteContainer.SizeChanged += OnPaletteSizeChanged;
        }

        FilteredItems.CollectionChanged += OnFilteredItemsChanged;

    }

    private void OnFilteredItemsChanged(object? sender, System.Collections.Specialized.NotifyCollectionChangedEventArgs e)
    {
    }

    private void OnResultsListLayoutUpdated(object? sender, EventArgs e)
    {
        if (_listScrollViewer == null && _resultsList != null)
        {
            _listScrollViewer = _resultsList.FindDescendantOfType<ScrollViewer>();
            if (_listScrollViewer != null)
            {
                _listScrollViewer.ScrollChanged += OnScrollChanged;
            }
        }
    }

    private void OnScrollChanged(object? sender, ScrollChangedEventArgs e)
    {
    }

    private void OnResultsListSizeChanged(object? sender, SizeChangedEventArgs e)
    {
    }

    private void OnPaletteLayoutUpdated(object? sender, EventArgs e)
    {
    }

    private void OnPaletteSizeChanged(object? sender, SizeChangedEventArgs e)
    {
    }

    private void InitializeComponent()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public void SetSearchProvider(Func<string, CancellationToken, Task<IEnumerable<CommandPaletteItem>>> searchProvider)
    {
        _searchProvider = searchProvider;
    }

    public void RegisterActions(IEnumerable<CommandPaletteItem> actions)
    {
        _allItems.Clear();
        _allItems.AddRange(actions);
        UpdateFilteredItems();
    }

    public void AddRecentSearch(string query, string title, string? argument = null)
    {
        var existing = _recentItems.FirstOrDefault(r => r.SearchQuery == query);
        if (existing != null)
        {
            existing.LastUsed = DateTime.Now;
            existing.UseCount++;
        }
        else
        {
            _recentItems.Insert(0, new CommandPaletteItem
            {
                Title = title,
                Description = query,
                Category = "Недавние",
                Icon = "🕐",
                ActionType = CommandPaletteActionType.Recent,
                SearchQuery = query,
                Argument = argument,
                LastUsed = DateTime.Now,
                UseCount = 1
            });
        }

        while (_recentItems.Count > 5)
        {
            _recentItems.RemoveAt(_recentItems.Count - 1);
        }

        UpdateFilteredItems();
    }

    public async Task ShowAsync()
    {
        IsOpen = true;
        SearchText = string.Empty;
        UpdateFilteredItems();


        await Task.Delay(50);
        _searchInput?.Focus();

        if (_searchInput != null)
        {
            _searchInput.CaretIndex = _searchInput.Text?.Length ?? 0;
        }

    }

    public void Hide()
    {
        IsOpen = false;
        _searchCts?.Cancel();
        Closed?.Invoke(this, EventArgs.Empty);
    }

    private void UpdateFilteredItems()
    {
        FilteredItems.Clear();

        var query = SearchText?.Trim() ?? string.Empty;

        if (string.IsNullOrEmpty(query))
        {
            foreach (var item in _allItems.Where(i => i.ActionType == CommandPaletteActionType.Action || i.ActionType == CommandPaletteActionType.Navigation))
            {
                FilteredItems.Add(item);
            }

            foreach (var recent in _recentItems.OrderByDescending(r => r.LastUsed).Take(3))
            {
                if (!FilteredItems.Any(i => i.Id == recent.Id))
                {
                    FilteredItems.Add(recent);
                }
            }
        }
        else
        {
            var matchingActions = _allItems
                .Where(i => (i.ActionType == CommandPaletteActionType.Action || i.ActionType == CommandPaletteActionType.Navigation) &&
                            (i.Title.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                             i.Description.Contains(query, StringComparison.OrdinalIgnoreCase)))
                .ToList();

            foreach (var item in matchingActions)
            {
                FilteredItems.Add(item);
            }
        }

        if (FilteredItems.Count > 0 && _resultsList != null)
        {
            _resultsList.SelectedIndex = 0;
        }
    }

    private async void OnSearchTextChanged()
    {
        _searchCts?.Cancel();
        _searchCts = new CancellationTokenSource();
        var token = _searchCts.Token;

        var query = (_searchInput?.Text ?? SearchText)?.Trim() ?? string.Empty;

        UpdateFilteredItems();

        if (!string.IsNullOrEmpty(query) && query.Length >= 2)
        {
            SearchQueryChanged?.Invoke(this, query);

            if (_searchProvider != null)
            {
                try
                {
                    var results = await _searchProvider(query, token);
                    if (!token.IsCancellationRequested)
                    {
                        foreach (var item in results)
                        {
                            if (!FilteredItems.Any(i => i.Matches(item)))
                            {
                                FilteredItems.Add(item);
                            }
                        }
                    }
                }
                catch (OperationCanceledException) { }
            }
            else if (_searchCache.TryGetValue(query.ToLower(), out var cached))
            {
                foreach (var item in cached)
                {
                    if (!FilteredItems.Any(i => i.Matches(item)))
                    {
                        FilteredItems.Add(item);
                    }
                }
            }
        }

        if (_resultsList != null && FilteredItems.Count > 0)
        {
            _resultsList.SelectedIndex = 0;
        }
    }

    private void ExecuteSelectedItem(CommandPaletteItem item)
    {
        ItemSelected?.Invoke(this, item);
        AddRecentSearch(item.SearchQuery ?? item.Title, item.Title, item.Argument);
        Hide();
    }

    private void SearchInput_KeyDown(object? sender, KeyEventArgs e)
    {
        switch (e.Key)
        {
            case Key.Escape:
                Hide();
                e.Handled = true;
                break;

            case Key.Enter:
                if (_resultsList?.SelectedItem is CommandPaletteItem selected)
                {
                    ExecuteSelectedItem(selected);
                    e.Handled = true;
                }
                break;

            case Key.Down:
            case Key.Up:
                if (_resultsList != null && FilteredItems.Count > 0)
                {
                    _isSelectionProgrammatic = true;
                    _resultsList.SelectedIndex = e.Key == Key.Down
                        ? Math.Min(_resultsList.SelectedIndex + 1, FilteredItems.Count - 1)
                        : Math.Max(_resultsList.SelectedIndex - 1, 0);
                    ScrollToSelected();
                    _isSelectionProgrammatic = false;
                }
                e.Handled = true;
                break;
        }
    }

    private void ResultsList_KeyDown(object? sender, KeyEventArgs e)
    {
        SearchInput_KeyDown(sender, e);
    }

    private void OnSearchInputKeyDown(object? sender, KeyEventArgs e)
    {
        SearchInput_KeyDown(sender, e);
    }

    private void ScrollToSelected()
    {
        if (_resultsList?.SelectedItem != null)
        {
            _resultsList.ScrollIntoView(_resultsList.SelectedItem);
        }
    }

    private void SearchInput_TextChanged(object? sender, RoutedEventArgs e)
    {
        OnSearchTextChanged();
    }

    private void SearchInput_TextInput(object? sender, TextInputEventArgs e)
    {
        Dispatcher.UIThread.Post(() => OnSearchTextChanged());
    }

    private void SearchInput_GotFocus(object? sender, RoutedEventArgs e)
    {
        _textBeforeFocusChange = _searchInput?.Text;
        Dispatcher.UIThread.Post(async () =>
        {
            await Task.Delay(150);
            if (_searchInput != null && _searchInput.Text != _textBeforeFocusChange)
            {
                OnSearchTextChanged();
            }
        });
    }

    private void ResultsList_SelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (_isSelectionProgrammatic) return;

        if (sender is ListBox listBox && listBox.SelectedItem is CommandPaletteItem item)
        {
            ExecuteSelectedItem(item);
        }
    }

    private void CloseButton_Click(object? sender, RoutedEventArgs e)
    {
        Hide();
    }
}

public static class CommandPaletteItemExtensions
{
    public static bool Matches(this CommandPaletteItem a, CommandPaletteItem b)
    {
        return a.ActionType == b.ActionType &&
               a.Title == b.Title &&
               a.Argument == b.Argument;
    }

    public static bool MatchesId(this CommandPaletteItem a, CommandPaletteItem b)
    {
        return a.Id == b.Id;
    }
}