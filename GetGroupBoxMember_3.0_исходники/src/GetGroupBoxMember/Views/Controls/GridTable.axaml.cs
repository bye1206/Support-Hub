using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Threading;
using Avalonia.VisualTree;
using GetGroupBoxMember.Services;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Data;
using System.IO;
using System.Text;
using System.Linq;

namespace GetGroupBoxMember.Views.Controls;

public partial class GridTable : UserControl
{

    public static readonly StyledProperty<ObservableCollection<string>?> ColumnHeadersProperty =
        AvaloniaProperty.Register<GridTable, ObservableCollection<string>?>(nameof(ColumnHeaders));

    public static readonly StyledProperty<ObservableCollection<string[]>?> RowsProperty =
        AvaloniaProperty.Register<GridTable, ObservableCollection<string[]>?>(nameof(Rows));

    public ObservableCollection<string>? ColumnHeaders
    {
        get => GetValue(ColumnHeadersProperty);
        set => SetValue(ColumnHeadersProperty, value);
    }

    public ObservableCollection<string[]>? Rows
    {
        get => GetValue(RowsProperty);
        set => SetValue(RowsProperty, value);
    }

    private const int MinColumnWidth = 80;
    private const int MaxColumnWidth = 350;
    private const int UncColumnMaxWidth = 500;
    private int? _uncColumnIndex;
    private const int PaddingHorizontal = 30;
    private const double HeaderFontSize = 12.0;
    private const double CellFontSize = 13.0;

    private int[]? _cachedColumnWidths;
    private bool _isRebuilding = false;
    private bool _rebuildPending = false;
    private DateTime _lastResizeTime = DateTime.MinValue;
    private double _lastWidth = 0;
    private int _sortColumn = -1;
    private bool _sortAscending = true;
    private DataTable? _dataSource;
    private Dictionary<string, string>? _headerTranslationMap;

    private readonly HashSet<(int row, int col)> _selectedCells = new();
    private int? _selectionStartRow;
    private int? _selectionStartCol;
    private (int row, int col)? _currentCell;
    private bool _isSelecting;

    private Border? _currentCellBorder;
    private ObservableCollection<GridRowWrapper>? _wrappers;

    private TranslateTransform? _headerTranslate;
    private DispatcherTimer? _autoScrollTimer;
    private double _autoScrollDirection;

    private Color _themeCardBackground;
    private Color _themeBorder;
    private Color _themeTextPrimary;
    private Color _linkColor;
    private Color _textSecondary;
    private Color _selectionColor;
    private Color _elevatedSurface;

    private Color GetResourceColor(string key, Color fallback)
    {
        if (Application.Current?.Resources.TryGetValue(key, out var value) == true && value is Color c)
            return c;
        return fallback;
    }

    private void LoadColors()
    {
        _themeCardBackground = GetResourceColor("ThemeCardBackground", Color.Parse("#1A1A1A"));
        _themeBorder = GetResourceColor("ThemeBorderAlt", Color.Parse("#30363D"));
        _themeTextPrimary = GetResourceColor("ThemeTextPrimary", Color.Parse("#FFFFFF"));
        _linkColor = GetResourceColor("LinkColor", Color.Parse("#58A6FF"));
        _textSecondary = GetResourceColor("ThemeTextSecondary", Color.Parse("#9E9E9E"));
        _selectionColor = GetResourceColor("ThemeAccent", Color.Parse("#264F78"));
        _elevatedSurface = GetResourceColor("ThemeElevatedSurface", Color.Parse("#21262D"));
    }

    public void ReloadColors()
    {
        LoadColors();
        if (HeaderGrid != null)
        {
            HeaderGrid.Background = new SolidColorBrush(_themeCardBackground);
            foreach (var child in HeaderGrid.Children)
            {
                if (child is Border border)
                {
                    border.Background = new SolidColorBrush(_themeCardBackground);
                    if (border.Child is TextBlock tb)
                    {
                        tb.Foreground = new SolidColorBrush(_sortColumn == (int?)border.Tag ? _linkColor : _textSecondary);
                    }
                }
            }
        }
        if (_wrappers != null)
        {
            foreach (var wrapper in _wrappers)
            {
                wrapper.ReloadColors(_themeBorder, _themeTextPrimary, _selectionColor, _elevatedSurface);
            }
        }
        ScheduleRebuild();
    }

    public GridTable()
    {
        InitializeComponent();

        Focusable = true;

        LoadColors();

        if (Application.Current != null)
        {
            ThemeService.Instance.ThemeChanged += (s, e) => ReloadColors();
        }

        this.AddHandler(PointerPressedEvent, OnTablePointerPressed, RoutingStrategies.Bubble, handledEventsToo: true);
        this.AddHandler(PointerMovedEvent, OnTablePointerMoved, RoutingStrategies.Bubble);
        this.AddHandler(PointerReleasedEvent, OnTablePointerReleased, RoutingStrategies.Bubble);
        this.AddHandler(PointerWheelChangedEvent, OnTablePointerWheelChanged, RoutingStrategies.Bubble);

        _headerTranslate = new TranslateTransform();
        HeaderGrid.RenderTransform = _headerTranslate;

        DataScrollViewer.PropertyChanged += (s, e) =>
        {
            if (e.Property == ScrollViewer.OffsetProperty && _headerTranslate != null)
                _headerTranslate.X = -DataScrollViewer.Offset.X;
        };

        _autoScrollTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(50) };
        _autoScrollTimer.Tick += OnAutoScrollTick;
    }

    private void OnTablePointerPressed(object? sender, PointerPressedEventArgs e)
    {
    }

    private void OnTablePointerMoved(object? sender, PointerEventArgs e)
    {
        if (!_isSelecting || _selectionStartRow == null || _selectionStartCol == null) return;
        if (Rows == null || ColumnHeaders == null || _wrappers == null || DataRows == null) return;

        var pos = e.GetPosition(DataRows);
        var wrapper = FindWrapperAtPosition(pos);
        if (wrapper == null) return;

        int col = FindColumnAtPosition(pos);
        if (col < 0) return;
        UpdateSelection(wrapper.RowIndex, col);

        var viewportPos = e.GetPosition(DataScrollViewer);
        var viewportHeight = DataScrollViewer.Viewport.Height;
        double edgeZone = 40;

        if (viewportPos.Y < edgeZone)
        {
            _autoScrollDirection = -1;
            _autoScrollTimer?.Start();
        }
        else if (viewportPos.Y > viewportHeight - edgeZone)
        {
            _autoScrollDirection = 1;
            _autoScrollTimer?.Start();
        }
        else
        {
            _autoScrollTimer?.Stop();
        }
    }

    private void OnTablePointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (_isSelecting)
        {
            _isSelecting = false;
        }
        _autoScrollTimer?.Stop();
    }

    private void OnAutoScrollTick(object? sender, EventArgs e)
    {
        if (!_isSelecting || _selectionStartRow == null || _selectionStartCol == null)
        {
            _autoScrollTimer?.Stop();
            return;
        }

        double scrollAmount = _autoScrollDirection * 30;
        DataScrollViewer.Offset = new Vector(DataScrollViewer.Offset.X, DataScrollViewer.Offset.Y + scrollAmount);

        if (_wrappers == null || DataRows == null || ColumnHeaders == null) return;

        var pointInData = this.PointToClient(DataScrollViewer.PointToScreen(new Point(DataScrollViewer.Viewport.Width / 2, DataScrollViewer.Viewport.Height / 2)));
        var wrapper = FindWrapperAtPosition(pointInData);
        if (wrapper != null)
        {
            int col = _selectionStartCol ?? 0;
            UpdateSelection(wrapper.RowIndex, col);
        }
    }

    private void OnTablePointerWheelChanged(object? sender, PointerWheelEventArgs e)
    {
        e.Handled = false;
    }

    private GridRowWrapper? FindWrapperAtPosition(Point pos)
    {
        if (_wrappers == null) return null;
        foreach (var wrapper in _wrappers)
        {
            var bounds = wrapper.Bounds;
            if (bounds.Width == 0 && bounds.Height == 0) continue;
            if (pos.Y < bounds.Y) break;
            if (pos.Y >= bounds.Y && pos.Y < bounds.Y + bounds.Height)
                return wrapper;
        }
        return null;
    }

    private int FindColumnAtPosition(Point pos)
    {
        if (ColumnHeaders == null) return 0;
        if (_cachedColumnWidths == null)
        {
            ScheduleRebuild();
            return -1;
        }
        double x = pos.X;
        for (int col = 0; col < ColumnHeaders.Count - 1; col++)
        {
            int width = col < _cachedColumnWidths.Length ? _cachedColumnWidths[col] : 100;
            if (x <= width)
                return col;
            x -= width;
        }
        return ColumnHeaders.Count - 1;
    }

    private void RebuildTimerTick()
    {
        if (_isRebuilding)
        {
            _rebuildPending = true;
            return;
        }

        if (ColumnHeaders == null || HeaderGrid == null || DataRows == null)
        {
            return;
        }

        _isRebuilding = true;
        try
        {
            var widths = MeasureColumnWidthsInternal();
            RebuildTableInternal(widths);
        }
        catch (Exception ex)
        {
        }
        finally
        {
            _isRebuilding = false;
            if (_rebuildPending)
            {
                _rebuildPending = false;
                Dispatcher.UIThread.Post(() => RebuildTimerTick());
            }
        }
    }

    private int[] MeasureColumnWidthsInternal()
    {
        if (ColumnHeaders == null) return Array.Empty<int>();
        int count = ColumnHeaders.Count;
        var widths = new int[count];

        if (Rows != null)
        {
            for (int col = 0; col < count; col++)
            {
                var maxWidth = 0;
                foreach (var row in Rows)
                {
                    if (col < row.Length)
                    {
                        var text = row[col] ?? "";
                        var width = MeasureTextWidth(text, CellFontSize, col);
                        maxWidth = Math.Max(maxWidth, width);
                    }
                }
                widths[col] = Math.Max(MinColumnWidth, maxWidth + PaddingHorizontal);
            }
        }

        for (int col = 0; col < count; col++)
        {
            if (ColumnHeaders != null && col < ColumnHeaders.Count)
            {
                var headerWidth = MeasureTextWidth(GetDisplayHeader(ColumnHeaders[col] ?? ""), HeaderFontSize, col);
                widths[col] = Math.Max(widths[col], headerWidth + PaddingHorizontal);
            }
        }

        return widths;
    }

    private void RebuildTableInternal(int[] widths)
    {
        if (ColumnHeaders == null || HeaderGrid == null || DataRows == null)
        {
            return;
        }

        int count = ColumnHeaders.Count;
        _cachedColumnWidths = widths;

        BuildHeaderGrid(count, widths);
        BuildVirtualizedRows(count, widths);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);

        if (e.Key == Key.C && (e.KeyModifiers.HasFlag(KeyModifiers.Control) || e.KeyModifiers.HasFlag(KeyModifiers.Meta)))
        {
            CopySelectedCells();
            e.Handled = true;
        }
        else if (e.Key == Key.A && (e.KeyModifiers.HasFlag(KeyModifiers.Control) || e.KeyModifiers.HasFlag(KeyModifiers.Meta)))
        {
            SelectAll();
            e.Handled = true;
        }
    }

    private async void CopySelectedCells()
    {
        if (_selectedCells.Count == 0) return;

        var sortedCells = _selectedCells.OrderBy(c => c.row).ThenBy(c => c.col).ToList();
        if (sortedCells.Count == 0) return;

        var minRow = sortedCells.Min(c => c.row);
        var maxRow = sortedCells.Max(c => c.row);
        var minCol = sortedCells.Min(c => c.col);
        var maxCol = sortedCells.Max(c => c.col);

        if (Rows == null || ColumnHeaders == null) return;

        var sb = new StringBuilder();

        for (int r = minRow; r <= maxRow; r++)
        {
            var rowCells = new List<string>();
            for (int c = minCol; c <= maxCol; c++)
            {
                if (r < Rows.Count && c < Rows[r].Length)
                {
                    rowCells.Add(Rows[r][c]);
                }
                else
                {
                    rowCells.Add("");
                }
            }
            sb.AppendLine(string.Join("\t", rowCells));
        }

        try
        {
            var topLevel = TopLevel.GetTopLevel(this);
            if (topLevel?.Clipboard != null)
            {
                await topLevel.Clipboard.SetTextAsync(sb.ToString().TrimEnd());
            }
        }
        catch (Exception ex)
        {
        }
    }

    private void SelectAll()
    {
        if (Rows == null || ColumnHeaders == null) return;

        _selectedCells.Clear();
        for (int r = 0; r < Rows.Count; r++)
        {
            for (int c = 0; c < ColumnHeaders.Count; c++)
            {
                _selectedCells.Add((r, c));
            }
        }
        UpdateWrapperSelectionState();
        RefreshVirtualizedRows();
    }

    private void ClearSelection()
    {
        _selectedCells.Clear();
        _selectionStartRow = null;
        _selectionStartCol = null;
        UpdateWrapperSelectionState();
        RefreshVirtualizedRows();
    }

    private void UpdateWrapperSelectionState()
    {
        if (_wrappers == null) return;
        
        foreach (var wrapper in _wrappers)
        {
            wrapper.UpdateSelection(_selectedCells, ColumnHeaders?.Count ?? 0);
        }
    }

    private void RefreshVirtualizedRows()
    {
        if (_wrappers == null) return;
        
        foreach (var wrapper in _wrappers)
        {
            wrapper.NotifySelectionChanged();
        }
    }

    protected override void OnPointerPressed(PointerPressedEventArgs e)
    {
        base.OnPointerPressed(e);
        Focus();
    }

    protected override void OnSizeChanged(SizeChangedEventArgs e)
    {
        base.OnSizeChanged(e);
        
        var now = DateTime.Now;
        if (Math.Abs(e.NewSize.Width - _lastWidth) > 50 && (now - _lastResizeTime).TotalMilliseconds > 200)
        {
            _lastWidth = e.NewSize.Width;
            _lastResizeTime = now;
            _cachedColumnWidths = null;
            ScheduleRebuild();
        }
    }

    public void SetDataSource(DataTable? dt)
    {
        _dataSource = dt;
        _sortColumn = -1;
        _sortAscending = true;
        _cachedColumnWidths = null;
        ClearSelection();

        if (dt == null)
        {
            ColumnHeaders = new ObservableCollection<string>();
            Rows = new ObservableCollection<string[]>();
            ScheduleRebuild();
            return;
        }

        var headers = new ObservableCollection<string>();
        foreach (DataColumn col in dt.Columns)
        {
            headers.Add(col.ColumnName);
        }

        var rows = new ObservableCollection<string[]>();
        foreach (DataRow row in dt.Rows)
        {
            var rowArray = new string[dt.Columns.Count];
            for (int i = 0; i < dt.Columns.Count; i++)
            {
                rowArray[i] = row[i]?.ToString() ?? "";
            }
            rows.Add(rowArray);
        }

        ColumnHeaders = headers;
        Rows = rows;
        ScheduleRebuild();
    }

    private void ScheduleRebuild()
    {
        Dispatcher.UIThread.Post(() => RebuildTimerTick());
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        if (change.Property == ColumnHeadersProperty || change.Property == RowsProperty)
        {
            if (change.Property == ColumnHeadersProperty)
            {
                _sortColumn = -1;
                _sortAscending = true;
            }
            _cachedColumnWidths = null;
            if (_dataSource != null || (ColumnHeaders != null && Rows != null))
            {
                ScheduleRebuild();
            }
        }
    }

    private void SortData(int columnIndex)
    {
        if (ColumnHeaders == null || Rows == null || columnIndex < 0 || columnIndex >= ColumnHeaders.Count) return;

        if (_sortColumn == columnIndex)
        {
            _sortAscending = !_sortAscending;
        }
        else
        {
            _sortColumn = columnIndex;
            _sortAscending = true;
        }

        var colName = ColumnHeaders[columnIndex];
        bool isSizeColumn = colName.Contains("Size", StringComparison.OrdinalIgnoreCase);

        if (isSizeColumn)
        {
            var sorted = _sortAscending
                ? Rows.OrderBy(row => ParseSizeToBytes(columnIndex < row.Length ? row[columnIndex] : "0 B")).ToList()
                : Rows.OrderByDescending(row => ParseSizeToBytes(columnIndex < row.Length ? row[columnIndex] : "0 B")).ToList();
            Rows = new ObservableCollection<string[]>(sorted);
        }
        else if (IsNumericColumn(columnIndex))
        {
            var sorted = _sortAscending
                ? Rows.OrderBy(row => ParseNumericValue(columnIndex < row.Length ? row[columnIndex] : "0")).ToList()
                : Rows.OrderByDescending(row => ParseNumericValue(columnIndex < row.Length ? row[columnIndex] : "0")).ToList();
            Rows = new ObservableCollection<string[]>(sorted);
        }
        else if (_dataSource != null)
        {
            var dv = _dataSource.DefaultView;
            dv.Sort = $"[{colName}] {(_sortAscending ? "ASC" : "DESC")}";

            var rows = new ObservableCollection<string[]>();
            foreach (DataRowView rowView in dv)
            {
                var rowArray = new string[_dataSource.Columns.Count];
                for (int i = 0; i < _dataSource.Columns.Count; i++)
                {
                    rowArray[i] = rowView[i]?.ToString() ?? "";
                }
                rows.Add(rowArray);
            }
            Rows = rows;
        }
        else
        {
            var sorted = _sortAscending
                ? Rows.OrderBy(row => columnIndex < row.Length ? row[columnIndex] : "").ToList()
                : Rows.OrderByDescending(row => columnIndex < row.Length ? row[columnIndex] : "").ToList();
            Rows = new ObservableCollection<string[]>(sorted);
        }
    }

    private bool IsNumericColumn(int columnIndex)
    {
        if (Rows == null || Rows.Count == 0) return false;
        int sampleCount = Math.Min(Rows.Count, 50);
        int parsedCount = 0;
        for (int i = 0; i < sampleCount; i++)
        {
            var row = Rows[i];
            if (columnIndex >= row.Length) return false;
            var val = row[columnIndex]?.Trim() ?? "";
            if (string.IsNullOrEmpty(val)) continue;
            if (long.TryParse(val, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out _))
                parsedCount++;
            else
                return false;
        }
        return parsedCount > 0;
    }

    private long ParseNumericValue(string val)
    {
        if (string.IsNullOrWhiteSpace(val)) return 0;
        return long.TryParse(val.Trim(), System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out long result) ? result : 0;
    }

    private long ParseSizeToBytes(string sizeStr)
    {
        if (string.IsNullOrWhiteSpace(sizeStr)) return 0;

        sizeStr = sizeStr.Trim();
        
        int openParen = sizeStr.IndexOf('(');
        if (openParen >= 0)
        {
            int closeParen = sizeStr.LastIndexOf(')');
            if (closeParen > openParen)
            {
                string bytesPart = sizeStr.Substring(openParen + 1, closeParen - openParen - 1).Trim();
                bytesPart = bytesPart.Replace(" ", "").Replace("байт", "").Replace("bytes", "");
                if (long.TryParse(bytesPart, out long bytes))
                    return bytes;

                sizeStr = sizeStr.Substring(0, openParen).Trim();
            }
        }
        sizeStr = sizeStr.ToUpperInvariant();
        
        double multiplier = 1;
        if (sizeStr.EndsWith("TB"))
            multiplier = 1024L * 1024L * 1024L * 1024L;
        else if (sizeStr.EndsWith("GB"))
            multiplier = 1024L * 1024L * 1024L;
        else if (sizeStr.EndsWith("MB"))
            multiplier = 1024L * 1024L;
        else if (sizeStr.EndsWith("KB"))
            multiplier = 1024L;
        else if (sizeStr.EndsWith("B"))
            multiplier = 1;

        string numberPart = sizeStr;
        foreach (var suffix in new[] { "TB", "GB", "MB", "KB", "B" })
        {
            if (numberPart.EndsWith(suffix))
            {
                numberPart = numberPart.Substring(0, numberPart.Length - suffix.Length).Trim();
                break;
            }
        }

        if (double.TryParse(numberPart, System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out double numValue))
            return (long)(numValue * multiplier);

        return 0;
    }

    public void RebuildTable()
    {
        if (ColumnHeaders == null || HeaderGrid == null || DataRows == null)
        {
            return;
        }

        if (_isRebuilding)
        {
            _rebuildPending = true;
            return;
        }
        _isRebuilding = true;

        try
        {
            int count = ColumnHeaders.Count;

            if (_cachedColumnWidths == null || _cachedColumnWidths.Length != count)
            {
                _cachedColumnWidths = MeasureColumnWidths(count);
            }

            var widths = _cachedColumnWidths;

            BuildHeaderGrid(count, widths);

            BuildVirtualizedRows(count, widths);

        }
        catch (Exception ex)
        {
            throw;
        }
        finally
        {
            _isRebuilding = false;
            if (_rebuildPending)
            {
                _rebuildPending = false;
                Dispatcher.UIThread.Post(() => RebuildTable());
            }
        }
    }

    private void BuildHeaderGrid(int count, int[] widths)
    {
        try
        {
            HeaderGrid.ColumnDefinitions.Clear();
            HeaderGrid.Children.Clear();

            Color linkColor = _linkColor;
            Color textColor = _textSecondary;
            Color borderColor = _themeBorder;
            Color bgColor = _themeCardBackground;

            object? resourceVal = Application.Current?.FindResource("ThemeCardBackground");
            IBrush bgBrush;
            if (resourceVal is Brush b)
                bgBrush = b;
            else
                bgBrush = new SolidColorBrush(bgColor);

            for (int i = 0; i < count; i++)
            {
                bool isLastColumn = (i == count - 1);

                if (isLastColumn)
                {
                    HeaderGrid.ColumnDefinitions.Add(new ColumnDefinition(1, GridUnitType.Star));
                }
                else
                {
                    HeaderGrid.ColumnDefinitions.Add(new ColumnDefinition(widths[i], GridUnitType.Pixel));
                }

                string sortIndicator = "";
                if (_sortColumn == i)
                    sortIndicator = _sortAscending ? " ▲" : " ▼";

                Color fgColor = _sortColumn == i ? linkColor : textColor;

                string headerTextStr = GetDisplayHeader(ColumnHeaders[i]) + sortIndicator;

                var headerText = new TextBlock();
                headerText.Text = headerTextStr;
                headerText.FontWeight = FontWeight.SemiBold;
                headerText.Foreground = new SolidColorBrush(fgColor);
                headerText.TextWrapping = TextWrapping.NoWrap;
                headerText.Margin = new Thickness(12, 8);
                headerText.HorizontalAlignment = HorizontalAlignment.Stretch;

                var headerBorder = new Border();
                headerBorder.BorderBrush = new SolidColorBrush(borderColor);
                headerBorder.BorderThickness = new Thickness(0, 0, 1, 1);
                headerBorder.HorizontalAlignment = HorizontalAlignment.Stretch;
                headerBorder.Background = bgBrush;
                headerBorder.Child = headerText;
                headerBorder.Tag = i;

                headerBorder.PointerPressed += HeaderBorder_PointerPressed;
                Grid.SetColumn(headerBorder, i);

                HeaderGrid.Children.Add(headerBorder);
            }
        }
        catch (Exception ex)
        {
            throw;
        }
    }

    private void BuildVirtualizedRows(int count, int[] widths)
    {
        if (Rows == null)
        {
            DataRows.ItemsSource = null;
            _wrappers = null;
            return;
        }

        try
        {
            _wrappers = new ObservableCollection<GridRowWrapper>();

            for (int rowIdx = 0; rowIdx < Rows.Count; rowIdx++)
            {
                var wrapper = new GridRowWrapper(rowIdx, Rows[rowIdx], count, widths, _selectedCells,
                    _themeBorder, _themeTextPrimary, _selectionColor, _elevatedSurface);
                wrapper.CellPointerPressed += OnWrapperCellPointerPressed;
                wrapper.CellPointerMoved += OnWrapperCellPointerMoved;
                wrapper.CellPointerReleased += OnWrapperCellPointerReleased;
                _wrappers.Add(wrapper);
            }

            DataRows.ItemsSource = _wrappers;
        }
        catch (Exception ex)
        {
            throw;
        }
    }

    private void OnWrapperCellPointerPressed(object? sender, CellPointerEventArgs e)
    {
        _isSelecting = true;
        _selectionStartRow = e.RowIndex;
        _selectionStartCol = e.ColumnIndex;
        _currentCell = (e.RowIndex, e.ColumnIndex);

        UpdateSelection(e.RowIndex, e.ColumnIndex);
    }

    private void OnWrapperCellPointerMoved(object? sender, CellPointerEventArgs e)
    {
        if (!_isSelecting) return;
        UpdateSelection(e.RowIndex, e.ColumnIndex);
    }

    private void OnWrapperCellPointerReleased(object? sender, EventArgs e)
    {
        _isSelecting = false;
    }

    private void HeaderBorder_PointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is Border border && border.Tag is int columnIndex)
        {
            SortData(columnIndex);
        }
    }

    private void UpdateSelection(int row, int col)
    {
        if (_selectionStartRow == null || _selectionStartCol == null) return;
        if (Rows == null || ColumnHeaders == null) return;

        _selectedCells.Clear();

        int minRow = Math.Min(_selectionStartRow.Value, row);
        int maxRow = Math.Max(_selectionStartRow.Value, row);
        int minCol = Math.Min(_selectionStartCol.Value, col);
        int maxCol = Math.Max(_selectionStartCol.Value, col);

        for (int r = minRow; r <= maxRow && r < Rows.Count; r++)
        {
            for (int c = minCol; c <= maxCol && c < ColumnHeaders.Count; c++)
            {
                _selectedCells.Add((r, c));
            }
        }

        UpdateWrapperSelectionState();
        RefreshVirtualizedRows();
    }

    private int[] MeasureColumnWidths(int count)
    {
        return MeasureColumnWidthsInternal();
    }

    private int MeasureTextWidth(string text, double fontSize, int columnIndex = -1)
    {
        if (string.IsNullOrEmpty(text))
            return MinColumnWidth;

        var typeface = new Typeface(FontFamily.Default, FontStyle.Normal, FontWeight.Normal, FontStretch.Normal);
        var formattedText = new FormattedText(
            text,
            System.Globalization.CultureInfo.CurrentCulture,
            FlowDirection.LeftToRight,
            typeface,
            fontSize,
            Brushes.Black);
        int measuredWidth = (int)Math.Ceiling(formattedText.Width);

        int maxWidth = MaxColumnWidth;
        if (_uncColumnIndex == columnIndex)
            maxWidth = UncColumnMaxWidth;

        return Math.Max(MinColumnWidth, Math.Min(measuredWidth + PaddingHorizontal, maxWidth));
    }

    public void SetUncColumn(int columnIndex)
    {
        _uncColumnIndex = columnIndex;
        _cachedColumnWidths = null;
        ScheduleRebuild();
    }

    public void SetHeaderTranslationMap(Dictionary<string, string>? map)
    {
        _headerTranslationMap = map;
        _cachedColumnWidths = null;
        ScheduleRebuild();
    }

    private string GetDisplayHeader(string columnName)
    {
        if (_headerTranslationMap != null && _headerTranslationMap.TryGetValue(columnName, out var translated))
            return translated;
        return columnName;
    }
}

public class CellPointerEventArgs : EventArgs
{
    public int RowIndex { get; }
    public int ColumnIndex { get; }
    
    public CellPointerEventArgs(int rowIndex, int columnIndex)
    {
        RowIndex = rowIndex;
        ColumnIndex = columnIndex;
    }
}

public class GridRowWrapper : ContentControl
{
    public event EventHandler<CellPointerEventArgs>? CellPointerPressed;
    public event EventHandler<CellPointerEventArgs>? CellPointerMoved;
    public event EventHandler? CellPointerReleased;

    public int RowIndex { get; }
    public string[] Data { get; }
    private readonly int _columnCount;
    private readonly int[] _columnWidths;
    private readonly HashSet<(int row, int col)> _selectedCells;
    private readonly bool[] _cellSelected;

    private Color _borderColor;
    private Color _textColor;
    private Color _selectionColor;
    private Color _background;

    public string GetCellText(int col) => col < Data.Length ? Data[col] : "";
    public bool IsCellSelected(int col) => col < _cellSelected.Length && _cellSelected[col];
    public int GetColumnWidth(int col) => col < _columnWidths.Length ? _columnWidths[col] : 80;
    public int ColumnCount => _columnCount;
    public bool IsLastColumn(int col) => col == _columnCount - 1;

    public GridRowWrapper(int rowIndex, string[] data, int columnCount, int[] columnWidths, HashSet<(int row, int col)> selectedCells,
        Color borderColor, Color textColor, Color selectionColor, Color background)
    {
        RowIndex = rowIndex;
        Data = data;
        _columnCount = columnCount;
        _columnWidths = columnWidths;
        _selectedCells = selectedCells;
        _cellSelected = new bool[columnCount];
        _borderColor = borderColor;
        _textColor = textColor;
        _selectionColor = selectionColor;
        _background = background;

        BuildRowGrid();
        UpdateSelection(selectedCells, _columnCount);
    }

    public void ReloadColors(Color borderColor, Color textColor, Color selectionColor, Color background)
    {
        _borderColor = borderColor;
        _textColor = textColor;
        _selectionColor = selectionColor;
        _background = background;
        RebuildCells();
    }

    private Grid? _rowGrid;

    private void RebuildCells()
    {
        if (_rowGrid == null) return;

        for (int i = 0; i < _rowGrid.Children.Count && i < _cellSelected.Length; i++)
        {
            if (_rowGrid.Children[i] is Border cellBorder)
            {
                cellBorder.BorderBrush = new SolidColorBrush(_borderColor);
                cellBorder.Background = _cellSelected[i]
                    ? new SolidColorBrush(_selectionColor)
                    : new SolidColorBrush(_background);

                if (cellBorder.Child is TextBlock textBlock)
                {
                    textBlock.Foreground = new SolidColorBrush(_textColor);
                }
            }
        }
    }

    private void BuildRowGrid()
    {
        var rowGrid = new Grid();
        rowGrid.Tag = RowIndex;

        for (int i = 0; i < _columnCount; i++)
        {
            if (i == _columnCount - 1)
            {
                rowGrid.ColumnDefinitions.Add(new ColumnDefinition(1, GridUnitType.Star));
            }
            else
            {
                rowGrid.ColumnDefinitions.Add(new ColumnDefinition(_columnWidths[i], GridUnitType.Pixel));
            }
        }

        for (int i = 0; i < _columnCount; i++)
        {
            bool isSelected = _cellSelected[i];

            var cellBorder = new Border
            {
                BorderBrush = new SolidColorBrush(_borderColor),
                BorderThickness = new Thickness(0, 0, 1, 1),
                Background = isSelected ? new SolidColorBrush(_selectionColor) : new SolidColorBrush(_background),
                MinHeight = 30,
                MaxHeight = 500,
                Tag = (RowIndex, i)
            };

            var textBlock = new TextBlock
            {
                Text = i < Data.Length ? Data[i] : "",
                Foreground = new SolidColorBrush(_textColor),
                FontSize = 13.0,
                TextWrapping = TextWrapping.Wrap,
                VerticalAlignment = VerticalAlignment.Top,
                HorizontalAlignment = HorizontalAlignment.Left,
                Margin = new Thickness(12, 6)
            };

            cellBorder.Child = textBlock;

            int col = i;
            cellBorder.PointerPressed += (s, e) =>
            {
                e.Handled = true;
                CellPointerPressed?.Invoke(this, new CellPointerEventArgs(RowIndex, col));
            };

            Grid.SetColumn(cellBorder, i);
            rowGrid.Children.Add(cellBorder);
        }

        _rowGrid = rowGrid;
        Content = rowGrid;
    }

    public void UpdateSelection(HashSet<(int row, int col)> selectedCells, int columnCount)
    {
        for (int i = 0; i < _cellSelected.Length && i < columnCount; i++)
        {
            _cellSelected[i] = selectedCells.Contains((RowIndex, i));
        }
    }

    public void NotifySelectionChanged()
    {
        if (_rowGrid == null) return;

        for (int i = 0; i < _rowGrid.Children.Count && i < _cellSelected.Length; i++)
        {
            if (_rowGrid.Children[i] is Border cellBorder)
            {
                cellBorder.Background = _cellSelected[i]
                    ? new SolidColorBrush(_selectionColor)
                    : new SolidColorBrush(_background);
            }
        }
    }
}