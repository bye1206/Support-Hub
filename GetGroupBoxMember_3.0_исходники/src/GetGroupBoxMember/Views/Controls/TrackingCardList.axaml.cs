using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using GetGroupBoxMember.Models;
using GetGroupBoxMember.Services;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;

namespace GetGroupBoxMember.Views.Controls;

public partial class TrackingCardList : UserControl
{
    private ObservableCollection<MessageGroup>? _groups;
    private string? _subjectFilter;

    private Color _cardBg;
    private Color _border;
    private Color _textPrimary;
    private Color _textSecondary;
    private Color _accent;
    private Color _linkColor;
    private Color _elevatedSurface;
    private Color _failColor;
    private Color _successColor;

    public TrackingCardList()
    {
        InitializeComponent();
        LoadColors();
        ThemeService.Instance.ThemeChanged += (s, e) => { LoadColors(); ReloadCards(); };
    }

    private void LoadColors()
    {
        _cardBg = GetResourceColor("ThemeCardBackground", Color.Parse("#161B22"));
        _border = GetResourceColor("ThemeBorder", Color.Parse("#30363D"));
        _textPrimary = GetResourceColor("ThemeTextPrimary", Color.Parse("#F0F6FC"));
        _textSecondary = GetResourceColor("ThemeTextSecondary", Color.Parse("#8B949E"));
        _accent = GetResourceColor("ThemeAccent", Color.Parse("#60CDFF"));
        _linkColor = GetResourceColor("LinkColor", Color.Parse("#58A6FF"));
        _elevatedSurface = GetResourceColor("ThemeElevatedSurface", Color.Parse("#21262D"));
        _failColor = Color.Parse("#F85149");
        _successColor = Color.Parse("#3FB950");
    }

    private Color GetResourceColor(string key, Color fallback)
    {
        if (Application.Current?.Resources.TryGetValue(key, out var value) == true && value is Color c)
            return c;
        return fallback;
    }

    public void SetData(List<MessageGroup>? groups, string? subjectFilter = null)
    {
        _groups = groups != null ? new ObservableCollection<MessageGroup>(groups) : null;
        _subjectFilter = subjectFilter;
        RebuildCards();
    }

    public void Clear()
    {
        _groups = null;
        _subjectFilter = null;
        if (CardsPanel != null) CardsPanel.Children.Clear();
    }

    private void ReloadCards()
    {
        if (_groups != null) RebuildCards();
    }

    private void RebuildCards()
    {
        if (CardsPanel == null) return;
        CardsPanel.Children.Clear();

        if (_groups == null || _groups.Count == 0)
        {
            var empty = new TextBlock
            {
                Text = "Нет данных для отображения",
                Foreground = new SolidColorBrush(_textSecondary),
                FontSize = 14,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 40, 0, 0)
            };
            CardsPanel.Children.Add(empty);
            return;
        }

        foreach (var group in _groups)
        {
            CardsPanel.Children.Add(BuildCard(group));
        }
    }

    private Border BuildCard(MessageGroup group)
    {
        var cardBorder = new Border
        {
            Background = new SolidColorBrush(_cardBg),
            BorderBrush = new SolidColorBrush(_border),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(0),
            Margin = new Thickness(0, 0, 0, 2)
        };

        var cardGrid = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto") };

        var header = BuildCardHeader(group);
        Grid.SetRow(header, 0);
        cardGrid.Children.Add(header);

        var detailsPlaceholder = new Border
        {
            IsVisible = false,
            BorderBrush = new SolidColorBrush(_border),
            BorderThickness = new Thickness(0, 1, 0, 0),
            Background = new SolidColorBrush(_elevatedSurface)
        };
        Grid.SetRow(detailsPlaceholder, 1);
        cardGrid.Children.Add(detailsPlaceholder);

        header.Tag = (group, detailsPlaceholder);

        cardBorder.Child = cardGrid;
        return cardBorder;
    }

    private Border BuildCardHeader(MessageGroup group)
    {
        var headerBorder = new Border
        {
            Padding = new Thickness(14, 10),
            Cursor = Cursor.Parse("Hand"),
            Background = new SolidColorBrush(Colors.Transparent)
        };

        var headerGrid = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"),
            RowDefinitions = new RowDefinitions("Auto,Auto,Auto")
        };

        var arrow = new TextBlock
        {
            Text = group.IsExpanded ? "▼" : "▶",
            FontSize = 12,
            Foreground = new SolidColorBrush(_textSecondary),
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 8, 0),
            FontWeight = FontWeight.Normal
        };
        Grid.SetRowSpan(arrow, 3);
        Grid.SetColumn(arrow, 0);
        headerGrid.Children.Add(arrow);

        var subjectText = !string.IsNullOrEmpty(group.Subject) ? group.Subject : "(без темы)";
        var subjectTb = new TextBlock
        {
            Text = subjectText,
            FontSize = 14,
            FontWeight = FontWeight.SemiBold,
            Foreground = new SolidColorBrush(_textPrimary),
            TextWrapping = TextWrapping.NoWrap,
            TextTrimming = TextTrimming.CharacterEllipsis,
            VerticalAlignment = VerticalAlignment.Center
        };
        Grid.SetRow(subjectTb, 0);
        Grid.SetColumn(subjectTb, 1);
        headerGrid.Children.Add(subjectTb);

        var metaText = $"{group.Sender} → {group.RecipientsSummary}";
        var metaTb = new TextBlock
        {
            Text = metaText,
            FontSize = 12,
            Foreground = new SolidColorBrush(_textSecondary),
            TextWrapping = TextWrapping.NoWrap,
            TextTrimming = TextTrimming.CharacterEllipsis,
            Margin = new Thickness(0, 2, 0, 0)
        };
        Grid.SetRow(metaTb, 1);
        Grid.SetColumn(metaTb, 1);
        headerGrid.Children.Add(metaTb);

        var eventsTb = new TextBlock
        {
            Text = $"{group.EventsSummary}  |  {group.ServerCount} серв.  |  {group.TimeRange}  |  {group.DurationStr}",
            FontSize = 11,
            Foreground = new SolidColorBrush(_accent),
            TextWrapping = TextWrapping.NoWrap,
            TextTrimming = TextTrimming.CharacterEllipsis,
            Margin = new Thickness(0, 2, 0, 0)
        };
        Grid.SetRow(eventsTb, 2);
        Grid.SetColumn(eventsTb, 1);
        headerGrid.Children.Add(eventsTb);

        var countBadge = new Border
        {
            Background = new SolidColorBrush(_elevatedSurface),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(10, 4, 10, 4),
            VerticalAlignment = VerticalAlignment.Center,
            Child = new TextBlock
            {
                Text = group.RecordCount.ToString(),
                FontSize = 12,
                FontWeight = FontWeight.SemiBold,
                Foreground = new SolidColorBrush(_textPrimary)
            }
        };
        Grid.SetRowSpan(countBadge, 3);
        Grid.SetColumn(countBadge, 2);
        headerGrid.Children.Add(countBadge);

        headerBorder.Child = headerGrid;

        headerBorder.PointerPressed += (s, e) =>
        {
            if (headerBorder.Tag is (MessageGroup g, Border d))
            {
                g.IsExpanded = !g.IsExpanded;
                if (g.IsExpanded)
                {
                    if (d.Child == null)
                    {
                        d.Padding = new Thickness(14, 8, 14, 12);
                        d.Child = BuildCardDetailsContent(g);
                    }
                    d.IsVisible = true;
                }
                else
                {
                    d.IsVisible = false;
                    d.Child = null;
                }
                arrow.Text = g.IsExpanded ? "▼" : "▶";
                e.Handled = true;
            }
        };

        return headerBorder;
    }

    private StackPanel BuildCardDetailsContent(MessageGroup group)
    {
        var detailsStack = new StackPanel { Spacing = 8 };

        var infoGrid = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("Auto,*"),
            RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto")
        };

        AddInfoRow(infoGrid, 0, "Message-ID:", group.MessageId);
        AddInfoRow(infoGrid, 1, "Размер:", !string.IsNullOrEmpty(group.SizeMB) ? $"{group.SizeMB} МБ" : "—");
        AddInfoRow(infoGrid, 2, "Отправитель:", group.Sender);
        AddInfoRow(infoGrid, 3, "Получатели:", group.Recipients);
        detailsStack.Children.Add(infoGrid);

        var recipientStatuses = BuildRecipientStatusSummary(group);
        if (recipientStatuses != null) detailsStack.Children.Add(recipientStatuses);

        var timelineHeader = new TextBlock
        {
            Text = "Хронология событий",
            FontSize = 12,
            FontWeight = FontWeight.SemiBold,
            Foreground = new SolidColorBrush(_textSecondary),
            Margin = new Thickness(0, 4, 0, 0)
        };
        detailsStack.Children.Add(timelineHeader);

        var colHeaderGrid = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("130,150,*,140,80"),
            Margin = new Thickness(3, 0, 3, 2)
        };
        var colHeaders = new[] { "Время", "Событие", "Получатель", "Сервер", "Размер" };
        for (int i = 0; i < colHeaders.Length; i++)
        {
            var htb = new TextBlock
            {
                Text = colHeaders[i],
                FontSize = 10,
                Foreground = new SolidColorBrush(_textSecondary),
                FontWeight = FontWeight.SemiBold,
                VerticalAlignment = VerticalAlignment.Center
            };
            if (i == 4) htb.HorizontalAlignment = HorizontalAlignment.Right;
            Grid.SetColumn(htb, i);
            colHeaderGrid.Children.Add(htb);
        }
        detailsStack.Children.Add(colHeaderGrid);

        foreach (var rec in group.Records)
        {
            detailsStack.Children.Add(BuildTimelineRow(rec));
        }

        var statsBorder = new Border
        {
            Background = new SolidColorBrush(_cardBg),
            CornerRadius = new CornerRadius(6),
            Padding = new Thickness(10, 6),
            Margin = new Thickness(0, 4, 0, 0),
            Child = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Spacing = 16,
                Children =
                {
                    new TextBlock
                    {
                        Text = $"Серверов: {group.ServerCount}",
                        FontSize = 12,
                        Foreground = new SolidColorBrush(_textSecondary)
                    },
                    new TextBlock
                    {
                        Text = $"Событий: {group.RecordCount}",
                        FontSize = 12,
                        Foreground = new SolidColorBrush(_textSecondary)
                    },
                    new TextBlock
                    {
                        Text = $"Длительность: {group.DurationStr}",
                        FontSize = 12,
                        Foreground = new SolidColorBrush(_textSecondary)
                    }
                }
            }
        };
        detailsStack.Children.Add(statsBorder);

        return detailsStack;
    }

    private Border? BuildRecipientStatusSummary(MessageGroup group)
    {
        var recipientEvents = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
        foreach (var rec in group.Records)
        {
            var parts = rec.Recipients.Split(new[] { "; ", ";" }, StringSplitOptions.RemoveEmptyEntries);
            foreach (var p in parts)
            {
                if (!recipientEvents.ContainsKey(p))
                    recipientEvents[p] = new List<string>();
                if (!recipientEvents[p].Contains(rec.EventId, StringComparer.OrdinalIgnoreCase))
                    recipientEvents[p].Add(rec.EventId);
            }
        }

        if (recipientEvents.Count <= 1) return null;

        var border = new Border
        {
            Background = new SolidColorBrush(_cardBg),
            CornerRadius = new CornerRadius(6),
            Padding = new Thickness(10, 6),
            Margin = new Thickness(0, 0, 0, 0)
        };

        var stack = new StackPanel { Spacing = 4 };
        var header = new TextBlock
        {
            Text = "Статусы по получателям",
            FontSize = 11,
            FontWeight = FontWeight.SemiBold,
            Foreground = new SolidColorBrush(_textSecondary),
            Margin = new Thickness(0, 0, 0, 2)
        };
        stack.Children.Add(header);

        foreach (var kvp in recipientEvents)
        {
            var hasFail = kvp.Value.Any(e => e.Equals("FAIL", StringComparison.OrdinalIgnoreCase) ||
                                              e.Equals("DELIVERFAIL", StringComparison.OrdinalIgnoreCase));
            var hasDeliver = kvp.Value.Any(e => e.Equals("DELIVER", StringComparison.OrdinalIgnoreCase));
            var statusColor = hasFail ? _failColor : hasDeliver ? _successColor : _textSecondary;
            var statusText = hasFail ? "❌ Ошибка" : hasDeliver ? "✅ Доставлено" : "⏳ " + string.Join(", ", kvp.Value.Select(e => EventIdHelper.GetLocalizedName(e)));

            var rowGrid = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("*,Auto")
            };
            var nameTb = new TextBlock
            {
                Text = kvp.Key,
                FontSize = 11,
                Foreground = new SolidColorBrush(_textPrimary),
                TextTrimming = TextTrimming.CharacterEllipsis,
                VerticalAlignment = VerticalAlignment.Center
            };
            Grid.SetColumn(nameTb, 0);
            rowGrid.Children.Add(nameTb);

            var statusTb = new TextBlock
            {
                Text = statusText,
                FontSize = 11,
                Foreground = new SolidColorBrush(statusColor),
                FontWeight = FontWeight.SemiBold,
                VerticalAlignment = VerticalAlignment.Center
            };
            Grid.SetColumn(statusTb, 1);
            rowGrid.Children.Add(statusTb);

            stack.Children.Add(rowGrid);
        }

        border.Child = stack;
        return border;
    }

    private void AddInfoRow(Grid grid, int row, string label, string value)
    {
        var labelTb = new TextBlock
        {
            Text = label,
            FontSize = 12,
            Foreground = new SolidColorBrush(_textSecondary),
            Margin = new Thickness(0, 0, 8, 2),
            VerticalAlignment = VerticalAlignment.Top
        };
        Grid.SetRow(labelTb, row);
        Grid.SetColumn(labelTb, 0);
        grid.Children.Add(labelTb);

        var valueTb = new TextBlock
        {
            Text = value,
            FontSize = 12,
            Foreground = new SolidColorBrush(_textPrimary),
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 2),
            VerticalAlignment = VerticalAlignment.Top
        };
        Grid.SetRow(valueTb, row);
        Grid.SetColumn(valueTb, 1);
        grid.Children.Add(valueTb);
    }

    private Grid BuildTimelineRow(TrackingRecord rec)
    {
        var isFail = rec.EventId.Equals("FAIL", StringComparison.OrdinalIgnoreCase) ||
                     rec.EventId.Equals("DELIVERFAIL", StringComparison.OrdinalIgnoreCase) ||
                     rec.EventId.Equals("SUBMITFAIL", StringComparison.OrdinalIgnoreCase) ||
                     rec.EventId.Equals("RESUBMITFAIL", StringComparison.OrdinalIgnoreCase);

        var eventColor = isFail ? _failColor :
                         rec.EventId.Equals("DELIVER", StringComparison.OrdinalIgnoreCase) ? _successColor :
                         _linkColor;

        var outerGrid = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("3,*"),
            Margin = new Thickness(0, 0, 0, 2)
        };

        var accentStrip = new Border
        {
            Background = new SolidColorBrush(eventColor),
            CornerRadius = new CornerRadius(2, 0, 0, 2)
        };
        Grid.SetColumn(accentStrip, 0);
        outerGrid.Children.Add(accentStrip);

        var rowBorder = new Border
        {
            Padding = new Thickness(10, 5),
            CornerRadius = new CornerRadius(0, 4, 4, 0),
            Background = new SolidColorBrush(_cardBg),
            BorderBrush = new SolidColorBrush(_border),
            BorderThickness = new Thickness(0, 0, 1, 1)
        };

        var rowGrid = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("130,150,*,140,80")
        };

        var timeTb = new TextBlock
        {
            Text = rec.TimestampStr,
            FontSize = 11,
            Foreground = new SolidColorBrush(_textSecondary),
            FontFamily = "Consolas,Courier New,monospace",
            VerticalAlignment = VerticalAlignment.Center
        };
        Grid.SetColumn(timeTb, 0);
        rowGrid.Children.Add(timeTb);

        var eventTb = new TextBlock
        {
            Text = rec.EventIdLocalized,
            FontSize = 12,
            FontWeight = FontWeight.SemiBold,
            Foreground = new SolidColorBrush(eventColor),
            VerticalAlignment = VerticalAlignment.Center
        };
        Grid.SetColumn(eventTb, 1);
        rowGrid.Children.Add(eventTb);

        var recipientTb = new TextBlock
        {
            Text = rec.RecipientDisplay,
            FontSize = 11,
            Foreground = new SolidColorBrush(_textPrimary),
            TextTrimming = TextTrimming.CharacterEllipsis,
            VerticalAlignment = VerticalAlignment.Center
        };
        ToolTip.SetTip(recipientTb, rec.RecipientsFull);
        Grid.SetColumn(recipientTb, 2);
        rowGrid.Children.Add(recipientTb);

        var serverTb = new TextBlock
        {
            Text = $"{rec.Server} ({rec.Source})",
            FontSize = 11,
            Foreground = new SolidColorBrush(_textSecondary),
            TextTrimming = TextTrimming.CharacterEllipsis,
            VerticalAlignment = VerticalAlignment.Center
        };
        Grid.SetColumn(serverTb, 3);
        rowGrid.Children.Add(serverTb);

        var sizeTb = new TextBlock
        {
            Text = !string.IsNullOrEmpty(rec.SizeMB) ? $"{rec.SizeMB} МБ" : "",
            FontSize = 11,
            Foreground = new SolidColorBrush(_textSecondary),
            HorizontalAlignment = HorizontalAlignment.Right,
            VerticalAlignment = VerticalAlignment.Center
        };
        Grid.SetColumn(sizeTb, 4);
        rowGrid.Children.Add(sizeTb);

        rowBorder.Child = rowGrid;
        Grid.SetColumn(rowBorder, 1);
        outerGrid.Children.Add(rowBorder);

        return outerGrid;
    }
}
