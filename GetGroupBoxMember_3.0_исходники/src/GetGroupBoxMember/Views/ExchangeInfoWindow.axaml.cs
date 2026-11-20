using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using GetGroupBoxMember.Services;
using GetGroupBoxMember.Models;
using GetGroupBoxMember.Views.Controls;
using System;
using System.Collections.Generic;
using System.Data;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace GetGroupBoxMember.Views;

public partial class ExchangeInfoWindow : WindowBase
{
    private string _mailbox;
    private DataTable? _currentData;
    private DataTable? _originalData;
    private string _currentSearchMode = "";
    private DataTable? _trackingFullData;
    private List<MessageGroup>? _trackingGroups;
    private bool _isTrackingMode = false;
    private CancellationTokenSource? _trackingCts;
    private bool _isTrackingRunning = false;
    private CancellationTokenSource? _loadCts;

    private static readonly Dictionary<string, string> HeaderTranslations = new()
    {
        { "Property", "Свойство" },
        { "Value", "Значение" },
        { "FolderPath", "Путь к папке" },
        { "FolderSize", "Размер папки" },
        { "ItemsInFolder", "Элементов в папке" },
        { "Category", "Категория" },
        { "Name", "Имя" },
        { "ItemCount", "Количество элементов" },
        { "Size", "Размер" },
        { "User", "Пользователь" },
        { "AccessRights", "Права доступа" },
        { "From", "От" },
        { "MoveToFolder", "Переместить в папку" },
        { "Description", "Описание" },
        { "ForwardTo", "Переслать" },
        { "RedirectTo", "Перенаправить" },
        { "DeleteMessage", "Удалить сообщение" },
        { "CopyToFolder", "Копировать в папку" },
        { "Timestamp", "Время" },
        { "EventId", "ID события" },
        { "Sender", "Отправитель" },
        { "Recipients", "Получатели" },
        { "MessageSubject", "Тема сообщения" },
        { "TotalBytes", "Всего байт" },
        { "Source", "Источник" },
        { "Server", "Сервер" },
        { "SizeMB", "Размер (МБ)" },
        { "MessageID", "ID сообщения" },
    };

    private void CancelCurrentLoad()
    {
        try { _loadCts?.Cancel(); } catch { }
        _loadCts?.Dispose();
        _loadCts = new CancellationTokenSource();
    }

    private void CancelTrackingLoad()
    {
        try { _trackingCts?.Cancel(); } catch { }
        _trackingCts?.Dispose();
        _trackingCts = new CancellationTokenSource();
    }

    public class TrackingProgress
    {
        public string Status { get; set; } = "";
        public int TotalRecords { get; set; }
        public int CurrentServer { get; set; }
        public int TotalServers { get; set; }
    }

    public ExchangeInfoWindow(string mailbox)
    {
        try
        {
            InitializeComponent();
        }
        catch (Exception ex)
        {
            throw;
        }
        _mailbox = mailbox;
        Title = $"Exchange меню: {mailbox}";

        MainGridTable.SetHeaderTranslationMap(HeaderTranslations);

        TrackingStartDate.SelectedDate = DateTime.Now.AddDays(-7);
        TrackingStartTime.Text = "09:01";
        TrackingEndDate.SelectedDate = DateTime.Now;
        TrackingEndTime.Text = "00:00";

        if (!string.IsNullOrEmpty(_mailbox))
        {
            TrackingSenderTextBox.Text = _mailbox;
        }

        Opened += OnWindowOpened;
    }

    private async void OnWindowOpened(object? sender, EventArgs e)
    {
        Opened -= OnWindowOpened;
        await LoadDefaultDataAsync();
    }

    private async Task LoadDefaultDataAsync()
    {
        await ShowQuota_ClickAsync();
    }

    public ExchangeInfoWindow() : this("")
    {
    }

    private string GetEmail()
    {
        if (string.IsNullOrEmpty(_mailbox))
        {
            return "";
        }
        if (_mailbox.Contains("@"))
        {
            return _mailbox;
        }
        var result = $"{_mailbox}@magnit.ru";
        return result;
    }

    private async void ShowQuota_Click(object? sender, RoutedEventArgs e)
    {
        await ShowQuota_ClickAsync();
    }

    private async Task ShowQuota_ClickAsync()
    {
        _isTrackingMode = false;
        _isAutoReplyMode = false;
        _currentSearchMode = "quota";
        TrackingPanel.IsVisible = false;
        AutoReplyPanel.IsVisible = false;
        MainContentGrid.IsVisible = true;
        CancelCurrentLoad();
        var localCts = _loadCts;

        LoadingOverlay.IsVisible = true;
        try
        {
            var ct = localCts!.Token;
            var dt = await RunScriptAsync("quota", ct);
            if (!ct.IsCancellationRequested)
            {
                _currentData = dt;
                _originalData = dt;
                if (dt == null || dt.Rows.Count == 0)
                {
                    await ShowMessageAsync("Не удалось получить данные квоты. Подробности в лог-файле.");
                }
                MainGridTable.SetDataSource(dt);
            }
        }
        catch (OperationCanceledException) {  }
        catch (Exception ex)
        {
            if (!localCts!.Token.IsCancellationRequested)
                await ShowMessageAsync($"Ошибка: {ex.Message}");
        }
        finally
        {
            if (ReferenceEquals(_loadCts, localCts) && !localCts!.Token.IsCancellationRequested)
                LoadingOverlay.IsVisible = false;
        }
    }

    private async void ShowFolders_Click(object? sender, RoutedEventArgs e)
    {
        _isTrackingMode = false;
        _isAutoReplyMode = false;
        _currentSearchMode = "folders";
        TrackingPanel.IsVisible = false;
        AutoReplyPanel.IsVisible = false;
        MainContentGrid.IsVisible = true;
        CancelCurrentLoad();
        var localCts = _loadCts;

        LoadingOverlay.IsVisible = true;
        try
        {
            var ct = localCts!.Token;
            var dt = await RunScriptAsync("folders", ct);
            if (!ct.IsCancellationRequested)
            {
                _currentData = dt;
                _originalData = dt;
                if (dt == null || dt.Rows.Count == 0)
                {
                    await ShowMessageAsync("Не удалось получить данные о папках. Подробности в лог-файле.");
                }
                MainGridTable.SetDataSource(dt);
            }
        }
        catch (OperationCanceledException) {  }
        catch (Exception ex)
        {
            if (!localCts!.Token.IsCancellationRequested)
                await ShowMessageAsync($"Ошибка: {ex.Message}");
        }
        finally
        {
            if (ReferenceEquals(_loadCts, localCts) && !localCts!.Token.IsCancellationRequested)
                LoadingOverlay.IsVisible = false;
        }
    }

    private async void ShowDeletedItems_Click(object? sender, RoutedEventArgs e)
    {
        _isTrackingMode = false;
        _isAutoReplyMode = false;
        _currentSearchMode = "deleted";
        TrackingPanel.IsVisible = false;
        AutoReplyPanel.IsVisible = false;
        MainContentGrid.IsVisible = true;
        CancelCurrentLoad();
        var localCts = _loadCts;

        LoadingOverlay.IsVisible = true;
        try
        {
            var ct = localCts!.Token;
            var dt = await RunScriptAsync("deleted", ct);
            if (!ct.IsCancellationRequested)
            {
                _currentData = dt;
                _originalData = dt;
                if (dt == null || dt.Rows.Count == 0)
                {
                    await ShowMessageAsync("Не удалось получить данные об удалённых элементах. Подробности в лог-файле.");
                }
                MainGridTable.SetDataSource(dt);
            }
        }
        catch (OperationCanceledException) {  }
        catch (Exception ex)
        {
            if (!localCts!.Token.IsCancellationRequested)
                await ShowMessageAsync($"Ошибка: {ex.Message}");
        }
        finally
        {
            if (ReferenceEquals(_loadCts, localCts) && !localCts!.Token.IsCancellationRequested)
                LoadingOverlay.IsVisible = false;
        }
    }

    private async void ShowFullInfo_Click(object? sender, RoutedEventArgs e)
    {
        _isTrackingMode = false;
        _isAutoReplyMode = false;
        _currentSearchMode = "fullinfo";
        TrackingPanel.IsVisible = false;
        AutoReplyPanel.IsVisible = false;
        MainContentGrid.IsVisible = true;
        CancelCurrentLoad();
        var localCts = _loadCts;

        LoadingOverlay.IsVisible = true;
        try
        {
            var ct = localCts!.Token;
            var dt = await RunScriptAsync("fullinfo", ct);
            if (!ct.IsCancellationRequested)
            {
                _currentData = dt;
                _originalData = dt;
                if (dt == null || dt.Rows.Count == 0)
                {
                    await ShowMessageAsync("Не удалось получить полную информацию. Подробности в лог-файле.");
                }
                MainGridTable.SetDataSource(dt);
            }
        }
        catch (OperationCanceledException) {  }
        catch (Exception ex)
        {
            if (!localCts!.Token.IsCancellationRequested)
                await ShowMessageAsync($"Ошибка: {ex.Message}");
        }
        finally
        {
            if (ReferenceEquals(_loadCts, localCts) && !localCts!.Token.IsCancellationRequested)
                LoadingOverlay.IsVisible = false;
        }
    }

    private async void ShowCalendar_Click(object? sender, RoutedEventArgs e)
    {
        _isTrackingMode = false;
        _isAutoReplyMode = false;
        _currentSearchMode = "calendar";
        TrackingPanel.IsVisible = false;
        AutoReplyPanel.IsVisible = false;
        MainContentGrid.IsVisible = true;
        CancelCurrentLoad();
        var localCts = _loadCts;

        LoadingOverlay.IsVisible = true;
        try
        {
            var ct = localCts!.Token;
            var dt = await RunScriptAsync("calendar", ct);
            if (!ct.IsCancellationRequested)
            {
                _currentData = dt;
                _originalData = dt;
                if (dt == null || dt.Rows.Count == 0)
                {
                    await ShowMessageAsync("Не удалось получить данные о календаре. Подробности в лог-файле.");
                }
                MainGridTable.SetDataSource(dt);
            }
        }
        catch (OperationCanceledException) {  }
        catch (Exception ex)
        {
            if (!localCts!.Token.IsCancellationRequested)
                await ShowMessageAsync($"Ошибка: {ex.Message}");
        }
        finally
        {
            if (ReferenceEquals(_loadCts, localCts) && !localCts!.Token.IsCancellationRequested)
                LoadingOverlay.IsVisible = false;
        }
    }

    private async void ShowInboxRules_Click(object? sender, RoutedEventArgs e)
    {
        _isTrackingMode = false;
        _isAutoReplyMode = false;
        _currentSearchMode = "inboxrules";
        TrackingPanel.IsVisible = false;
        AutoReplyPanel.IsVisible = false;
        MainContentGrid.IsVisible = true;
        CancelCurrentLoad();
        var localCts = _loadCts;

        LoadingOverlay.IsVisible = true;
        try
        {
            var ct = localCts!.Token;
            var dt = await RunScriptAsync("inboxrules", ct);
            if (!ct.IsCancellationRequested)
            {
                _currentData = dt;
                _originalData = dt;
                if (dt == null || dt.Rows.Count == 0)
                {
                    await ShowMessageAsync("Не удалось получить правила входящих. Подробности в лог-файле.");
                }
                MainGridTable.SetDataSource(dt);
            }
        }
        catch (OperationCanceledException) {  }
        catch (Exception ex)
        {
            if (!localCts!.Token.IsCancellationRequested)
                await ShowMessageAsync($"Ошибка: {ex.Message}");
        }
        finally
        {
            if (ReferenceEquals(_loadCts, localCts) && !localCts!.Token.IsCancellationRequested)
                LoadingOverlay.IsVisible = false;
        }
    }

    private void ShowTracking_Click(object? sender, RoutedEventArgs e)
    {
        _isAutoReplyMode = false;
        _isTrackingMode = true;
        _currentSearchMode = "tracking";
        AutoReplyPanel.IsVisible = false;
        TrackingPanel.IsVisible = true;
        MainContentGrid.IsVisible = false;
        CancelCurrentLoad();
        LoadingOverlay.IsVisible = false;
        if (!string.IsNullOrEmpty(_mailbox))
        {
            TrackingSenderTextBox.Text = _mailbox;
        }
    }

    private void ResetFilter_Click(object? sender, RoutedEventArgs e)
    {
        CancelCurrentLoad();
        LoadingOverlay.IsVisible = false;
        if (_isTrackingMode)
        {
            if (TrackingSubjectFilterTextBox != null) TrackingSubjectFilterTextBox.Text = "";
            if (TrackingEventIdComboBox != null) TrackingEventIdComboBox.SelectedIndex = 0;
            if (TrackingSourceComboBox != null) TrackingSourceComboBox.SelectedIndex = 0;
            if (TrackingMessageIdTextBox != null) TrackingMessageIdTextBox.Text = "";
            if (TrackingStatsPanel != null) TrackingStatsPanel.IsVisible = false;
            _trackingFullData = null;
            _trackingGroups = null;
            if (TrackingCardList != null) TrackingCardList.Clear();
            if (TrackingProgressText != null) TrackingProgressText.Text = "";
        }
        else if (!_isAutoReplyMode)
        {
            MainGridTable.SetDataSource(null);
        }
        _currentData = null;
        _originalData = null;
        if (ExchangeSearchBox != null) ExchangeSearchBox.Text = "";
    }

    private void ExchangeSearchBox_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            ExchangeSearch_Click(sender, e);
            e.Handled = true;
        }
    }

    private void ExchangeSearch_Click(object? sender, RoutedEventArgs e)
    {
        if (_isTrackingMode)
        {
            TrackingSubjectFilter_Click(sender, e);
            return;
        }

        if (_originalData == null || _originalData.Rows.Count == 0) return;

        string filter = ExchangeSearchBox?.Text?.Trim() ?? "";

        if (string.IsNullOrEmpty(filter))
        {
            MainGridTable.SetDataSource(_originalData);
            _currentData = _originalData;
            return;
        }

        string? searchColumn = _currentSearchMode switch
        {
            "folders" => _originalData.Columns.Contains("FolderPath") ? "FolderPath" : null,
            "fullinfo" => _originalData.Columns.Contains("Property") ? "Property" : null,
            _ => null
        };

        var filtered = _originalData.Clone();
        foreach (DataRow row in _originalData.Rows)
        {
            if (searchColumn != null)
            {
                var val = row[searchColumn]?.ToString() ?? "";
                if (val.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0)
                    filtered.ImportRow(row);
            }
            else
            {
                bool match = false;
                foreach (DataColumn col in _originalData.Columns)
                {
                    var val = row[col]?.ToString() ?? "";
                    if (val.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        match = true;
                        break;
                    }
                }
                if (match)
                    filtered.ImportRow(row);
            }
        }

        MainGridTable.SetDataSource(filtered);
        _currentData = filtered;
    }

    private async void TrackingSearch_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            
            if (TrackingSenderTextBox == null || TrackingRecipientTextBox == null || TrackingStartDate == null || TrackingEndDate == null)
            {
                return;
            }
            
            string senderLogin = TrackingSenderTextBox.Text?.Trim() ?? "";
            string recipientLogin = TrackingRecipientTextBox.Text?.Trim() ?? "";
            string messageId = TrackingMessageIdTextBox?.Text?.Trim() ?? "";
            
            string? eventId = null;
            if (TrackingEventIdComboBox != null && TrackingEventIdComboBox.SelectedIndex > 0)
            {
                eventId = (TrackingEventIdComboBox.SelectedItem as ComboBoxItem)?.Content?.ToString();
            }
            
            string? source = null;
            if (TrackingSourceComboBox != null && TrackingSourceComboBox.SelectedIndex > 0)
            {
                source = (TrackingSourceComboBox.SelectedItem as ComboBoxItem)?.Content?.ToString();
            }

            string? senderEmail = NormalizeEmail(senderLogin);
            string? recipientEmail = NormalizeEmail(recipientLogin);

            if (string.IsNullOrEmpty(senderEmail) && string.IsNullOrEmpty(recipientEmail) && string.IsNullOrEmpty(messageId))
            {
                await ShowMessageAsync("Введите хотя бы одного из: отправитель, получатель или Message-ID.");
                return;
            }

            DateTime startDate = DateTime.Now.AddDays(-7);
            DateTime endDate = DateTime.Now;
            
            var startDateVal = TrackingStartDate.SelectedDate;
            var endDateVal = TrackingEndDate.SelectedDate;
            
            if (startDateVal.HasValue)
            {
                var dto = startDateVal.Value;
                startDate = new DateTime(dto.Year, dto.Month, dto.Day, dto.Hour, dto.Minute, dto.Second);
            }
            
            if (endDateVal.HasValue)
            {
                var dto = endDateVal.Value;
                endDate = new DateTime(dto.Year, dto.Month, dto.Day, dto.Hour, dto.Minute, dto.Second);
            }
            
            startDate = CombineWithTime(startDate, TrackingStartTime?.Text ?? "09:01");
            endDate = CombineWithTime(endDate, TrackingEndTime?.Text ?? "00:00");

            if (endDate < startDate)
            {
                await ShowMessageAsync("Дата окончания не может быть раньше даты начала.");
                return;
            }

            int maxDays = 21;
            if ((endDate - startDate).TotalDays > maxDays)
            {
                await ShowMessageAsync($"Максимальный диапазон дат — {maxDays} дней (срок хранения tracking logs).");
                return;
            }


            if (TrackingProgressText != null) TrackingProgressText.Text = "Подключение к серверам Exchange...";
            if (TrackingProgressBar != null)
            {
                TrackingProgressBar.IsVisible = true;
                TrackingProgressBar.IsIndeterminate = true;
            }
            if (TrackingCardList != null)
            {
                TrackingCardList.Clear();
            }
            if (TrackingStatsPanel != null) TrackingStatsPanel.IsVisible = false;

            _isTrackingRunning = true;
            if (TrackingSearchButton != null) TrackingSearchButton.IsVisible = false;
            if (TrackingCancelButton != null) TrackingCancelButton.IsVisible = true;

            _trackingCts = new CancellationTokenSource();
            
            string lastProgressStatus = "";
            var progress = new Progress<TrackingProgress>(p =>
            {
                if (p != null)
                {
                    lastProgressStatus = p.Status;
                    Dispatcher.UIThread.Post(() =>
                    {
                        if (TrackingProgressText != null)
                            TrackingProgressText.Text = p.Status;
                        if (p.TotalServers > 0 && TrackingProgressBar != null)
                        {
                            TrackingProgressBar.IsIndeterminate = false;
                            TrackingProgressBar.Minimum = 0;
                            TrackingProgressBar.Maximum = p.TotalServers;
                            TrackingProgressBar.Value = p.CurrentServer;
                        }
                    });
                }
            });

            var result = await Task.Run(() => RunTrackingScriptAsync(
                senderEmail, recipientEmail, startDate, endDate, eventId, source, messageId,
                _trackingCts.Token, progress), _trackingCts.Token);
            var dt = result.dt;
            var progressStatus = result.progressStatus;
            
            _trackingFullData = dt;
            _currentData = dt;
            
            DisplayTrackingCards(dt);
            
            UpdateTrackingStats(dt);
            
            if (TrackingProgressText != null)
                TrackingProgressText.Text = $"Найдено сообщений: {_trackingGroups?.Count ?? 0} (записей: {dt?.Rows.Count ?? 0})";
        }
        catch (Exception ex)
        {
            if (TrackingProgressText != null) TrackingProgressText.Text = $"Ошибка: {ex.Message}";
        }
        finally
        {
            _isTrackingRunning = false;
            try
            {
                if (TrackingSearchButton != null) TrackingSearchButton.IsVisible = true;
                if (TrackingCancelButton != null) TrackingCancelButton.IsVisible = false;
                if (TrackingProgressBar != null) TrackingProgressBar.IsVisible = false;
            }
            catch (Exception ex)
            {
            }
        }
    }

    private void TrackingCancel_Click(object? sender, RoutedEventArgs e)
    {
        _trackingCts?.Cancel();
        if (TrackingProgressText != null) TrackingProgressText.Text = "Отмена...";
    }

    private void TrackingQuickDate_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is string tagStr && int.TryParse(tagStr, out int days))
        {
            TrackingStartDate.SelectedDate = DateTime.Now.AddDays(-days);
            TrackingStartTime.Text = DateTime.Now.ToString("HH:mm");
            TrackingEndDate.SelectedDate = DateTime.Now;
            TrackingEndTime.Text = DateTime.Now.ToString("HH:mm");
        }
    }

    private void TrackingSubjectFilter_Click(object? sender, RoutedEventArgs e)
    {
        if (_trackingFullData == null || _trackingFullData.Rows.Count == 0)
        {
            return;
        }

        string filter = TrackingSubjectFilterTextBox?.Text?.Trim() ?? "";
        
        if (string.IsNullOrEmpty(filter))
        {
            DisplayTrackingCards(_trackingFullData);
            _currentData = _trackingFullData;
            if (TrackingProgressText != null)
                TrackingProgressText.Text = $"Найдено сообщений: {_trackingGroups?.Count ?? 0}";
            UpdateTrackingStats(_trackingFullData);
            return;
        }

        DisplayTrackingCards(_trackingFullData, filter);
        _currentData = _trackingFullData;
        if (TrackingProgressText != null)
            TrackingProgressText.Text = $"Отфильтровано: {_trackingGroups?.Count ?? 0} сообщений";
        UpdateTrackingStats(_trackingFullData);
    }

    private List<MessageGroup> GroupTrackingData(DataTable? dt)
    {
        if (dt == null || dt.Rows.Count == 0) return new List<MessageGroup>();

        var records = new List<TrackingRecord>();
        foreach (DataRow row in dt.Rows)
        {
            var rec = new TrackingRecord
            {
                Timestamp = DateTime.TryParse(row["Timestamp"]?.ToString(), out var ts) ? ts : DateTime.MinValue,
                EventId = row["EventId"]?.ToString() ?? "",
                Sender = row["Sender"]?.ToString() ?? "",
                Recipients = row["Recipients"]?.ToString() ?? "",
                MessageSubject = row["MessageSubject"]?.ToString() ?? "",
                TotalBytes = long.TryParse(row["TotalBytes"]?.ToString(), out var tb) ? tb : 0,
                Source = row["Source"]?.ToString() ?? "",
                Server = row["Server"]?.ToString() ?? "",
                SizeMB = row["SizeMB"]?.ToString() ?? "",
                MessageId = row["MessageID"]?.ToString() ?? ""
            };
            records.Add(rec);
        }

        var groups = records
            .GroupBy(r => r.MessageId, StringComparer.OrdinalIgnoreCase)
            .Select(g =>
            {
                var groupRecords = g
                    .OrderBy(r => r.Timestamp)
                    .ToList();

                var deduped = new List<TrackingRecord>();
                var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (var r in groupRecords)
                {
                    var key = $"{r.Timestamp:O}|{r.EventId}|{r.Server}|{r.Recipients}";
                    if (seen.Add(key)) deduped.Add(r);
                }
                groupRecords = deduped;

                var first = groupRecords.FirstOrDefault();
                var allRecipients = groupRecords
                    .SelectMany(r => r.Recipients.Split(new[] { "; ", ";" }, StringSplitOptions.RemoveEmptyEntries))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .ToList();
                return new MessageGroup
                {
                    MessageId = g.Key,
                    Subject = first?.MessageSubject ?? "",
                    Sender = first?.Sender ?? "",
                    Recipients = string.Join("; ", allRecipients),
                    TotalBytes = first?.TotalBytes ?? 0,
                    SizeMB = first?.SizeMB ?? "",
                    Records = groupRecords,
                    UniqueEvents = groupRecords.Select(r => r.EventId).Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
                    ServerCount = groupRecords.Select(r => r.Server).Distinct(StringComparer.OrdinalIgnoreCase).Count(),
                    FirstSeen = groupRecords.FirstOrDefault()?.Timestamp ?? DateTime.MinValue,
                    LastSeen = groupRecords.LastOrDefault()?.Timestamp ?? DateTime.MinValue,
                    IsExpanded = false
                };
            })
            .OrderByDescending(g => g.FirstSeen)
            .ToList();

        return groups;
    }

    private void DisplayTrackingCards(DataTable? dt, string? subjectFilter = null)
    {
        var groups = GroupTrackingData(dt);

        if (!string.IsNullOrEmpty(subjectFilter))
        {
            groups = groups
                .Where(g => g.Subject.IndexOf(subjectFilter, StringComparison.OrdinalIgnoreCase) >= 0)
                .ToList();
        }

        _trackingGroups = groups;
        TrackingCardList?.SetData(groups, subjectFilter);
    }

    private void UpdateTrackingStats(DataTable? dt)
    {
        if (dt == null || dt.Rows.Count == 0 || TrackingStatsPanel == null)
        {
            if (TrackingStatsPanel != null) TrackingStatsPanel.IsVisible = false;
            return;
        }

        int total = _trackingGroups?.Count ?? dt.Rows.Count;
        int delivered = 0, sent = 0, failed = 0;

        if (_trackingGroups != null)
        {
            foreach (var g in _trackingGroups)
            {
                if (g.UniqueEvents.Any(e => e.Equals("DELIVER", StringComparison.OrdinalIgnoreCase))) delivered++;
                if (g.UniqueEvents.Any(e => e.Equals("SEND", StringComparison.OrdinalIgnoreCase))) sent++;
                if (g.UniqueEvents.Any(e => e.Equals("FAIL", StringComparison.OrdinalIgnoreCase))) failed++;
            }
        }
        else
        {
            foreach (DataRow row in dt.Rows)
            {
                var eventId = row["EventId"]?.ToString() ?? "";
                if (eventId.Equals("DELIVER", StringComparison.OrdinalIgnoreCase)) delivered++;
                else if (eventId.Equals("SEND", StringComparison.OrdinalIgnoreCase)) sent++;
                else if (eventId.Equals("FAIL", StringComparison.OrdinalIgnoreCase)) failed++;
            }
        }

        if (TrackingStatsTotal != null) TrackingStatsTotal.Text = $"Всего сообщений: {total}";
        if (TrackingStatsDelivered != null) TrackingStatsDelivered.Text = $"Доставлено: {delivered}";
        if (TrackingStatsSent != null) TrackingStatsSent.Text = $"Отправлено: {sent}";
        if (TrackingStatsFailed != null) TrackingStatsFailed.Text = $"Ошибок: {failed}";
        TrackingStatsPanel.IsVisible = true;
    }

    private static string? NormalizeEmail(string input)
    {
        if (string.IsNullOrWhiteSpace(input)) return null;
        input = input.Trim();
        if (!input.Contains("@"))
            input += "@magnit.ru";
        return input;
    }

    private static string EscapePsSingleQuote(string input)
    {
        return input.Replace("'", "''");
    }

    private static readonly Regex EmailRegex = new Regex(
        @"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
        RegexOptions.Compiled);

    private static bool IsValidEmail(string? email)
    {
        if (string.IsNullOrEmpty(email)) return false;
        return EmailRegex.IsMatch(email);
    }

    private DateTime CombineWithTime(DateTime date, string? timeText)
    {
        try
        {
            var parts = (timeText ?? "00:00").Split(':');
            if (parts.Length >= 2 && int.TryParse(parts[0], out int hours) && int.TryParse(parts[1], out int minutes))
            {
                return new DateTime(date.Year, date.Month, date.Day, hours, minutes, 0);
            }
        }
        catch { }
        return date;
    }

    private (DataTable? dt, string progressStatus) RunTrackingScriptAsync(
        string? senderEmail, string? recipientEmail, DateTime startDate, DateTime endDate,
        string? eventId, string? source, string? messageId,
        CancellationToken ct, IProgress<TrackingProgress>? progress)
    {
        string currentStatus = "Подключение к Exchange...";
        string tempFile = Path.Combine(Path.GetTempPath(), $"ggbm_et_{Guid.NewGuid():N}.ps1");
        string outFile = Path.Combine(Path.GetTempPath(), $"ggbm_et_{Guid.NewGuid():N}.csv");
        string outDir = Path.Combine(Path.GetTempPath(), $"ggbm_et_out_{Guid.NewGuid():N}");
        string progressDir = Path.Combine(Path.GetTempPath(), $"ggbm_et_prog_{Guid.NewGuid():N}");

        Directory.CreateDirectory(outDir);
        Directory.CreateDirectory(progressDir);

        progress?.Report(new TrackingProgress { Status = currentStatus, TotalServers = 1 });

        try
        {

            string ps = BuildTrackingScript(outFile, outDir, progressDir, startDate, endDate,
                senderEmail, recipientEmail, eventId, source, messageId);

            File.WriteAllText(tempFile, ps, new UTF8Encoding(false));

            var psi = new System.Diagnostics.ProcessStartInfo();
            psi.FileName = "powershell.exe";
            psi.Arguments = $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tempFile}\"";
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;

            var proc = System.Diagnostics.Process.Start(psi);

            var stdoutTask = System.Threading.Tasks.Task.Run(() => { try { return proc?.StandardOutput?.ReadToEnd() ?? ""; } catch { return ""; } });
            var stderrTask = System.Threading.Tasks.Task.Run(() => { try { return proc?.StandardError?.ReadToEnd() ?? ""; } catch { return ""; } });

            var lastProgressRead = DateTime.MinValue;
            var isComplete = false;
            int totalRecords = 0;
            int totalServers = 0;
            var processStartTime = DateTime.Now;
            var maxProcessDuration = TimeSpan.FromMinutes(60);

            while (!isComplete && !ct.IsCancellationRequested)
            {
                string finalFile = Path.Combine(progressDir, "final.txt");
                if (File.Exists(finalFile))
                {
                    var finalContent = File.ReadAllText(finalFile).Trim();
                    if (finalContent.Contains("COMPLETE"))
                    {
                        isComplete = true;
                        var finalParts = finalContent.Split('|');
                        if (finalParts.Length >= 3 && int.TryParse(finalParts[2], out int fc))
                            totalRecords = fc;
                        break;
                    }
                    if (finalContent.StartsWith("ERROR:"))
                    {
                        isComplete = true;
                        currentStatus = finalContent;
                        break;
                    }
                }

                if (proc?.HasExited == true && !isComplete)
                {
                    Thread.Sleep(500);
                    if (File.Exists(finalFile))
                    {
                        var fc = File.ReadAllText(finalFile).Trim();
                        if (fc.Contains("COMPLETE") || fc.StartsWith("ERROR:"))
                        {
                            isComplete = true;
                            var fp = fc.Split('|');
                            if (fp.Length >= 3 && int.TryParse(fp[2], out int c))
                                totalRecords = c;
                            break;
                        }
                    }
                    isComplete = true;
                    break;
                }

                if (DateTime.Now - processStartTime > maxProcessDuration)
                {
                    try { proc?.Kill(); } catch { }
                    isComplete = true;
                    break;
                }

                if ((DateTime.Now - lastProgressRead).TotalMilliseconds > 500)
                {
                    lastProgressRead = DateTime.Now;
                    try
                    {
                        string metaFile = Path.Combine(progressDir, "meta.txt");
                        if (totalServers == 0 && File.Exists(metaFile))
                        {
                            var mc = File.ReadAllText(metaFile).Trim();
                            var mp = mc.Split('|');
                            if (mp.Length >= 2 && int.TryParse(mp[1], out int ts))
                                totalServers = ts;
                        }

                        int doneServers = 0, inProgServers = 0, errServers = 0, recSoFar = 0;
                        var curServers = new StringBuilder();

                        foreach (var jf in Directory.GetFiles(progressDir, "job_*.txt"))
                        {
                            try
                            {
                                var c = File.ReadAllText(jf).Trim();
                                var p = c.Split('|');
                                if (p.Length >= 3)
                                {
                                    if (int.TryParse(p[2], out int r)) recSoFar += r;
                                    if (p[0] == "Done") doneServers++;
                                    else if (p[0] == "Error") errServers++;
                                    else if (p[0] == "In progress")
                                    {
                                        inProgServers++;
                                        if (curServers.Length > 0) curServers.Append(", ");
                                        curServers.Append(p[1]);
                                    }
                                }
                            }
                            catch { }
                        }

                        totalRecords = recSoFar;
                        int processed = doneServers + errServers;
                        string st;
                        if (totalServers > 0)
                        {
                            st = $"Серверов: {processed}/{totalServers} | Записей: {totalRecords}";
                            if (inProgServers > 0 && curServers.Length > 0)
                                st += $" | Сейчас: {curServers}";
                        }
                        else
                        {
                            st = "Получение списка серверов Exchange...";
                        }

                        currentStatus = st;
                        progress?.Report(new TrackingProgress
                        {
                            Status = st,
                            TotalRecords = totalRecords,
                            CurrentServer = processed,
                            TotalServers = totalServers > 0 ? totalServers : 1
                        });
                    }
                    catch { }
                }

                Thread.Sleep(100);
            }

            if (ct.IsCancellationRequested)
            {
                try { proc?.Kill(); } catch { }
                try { proc?.WaitForExit(3000); } catch { }
            }
            else
            {
                try { proc?.WaitForExit(3000); } catch { }
            }

            try
            {
                var stdout = stdoutTask.Result;
                var stderr = stderrTask.Result;
            }
            catch { }


            currentStatus = "Загрузка данных...";
            progress?.Report(new TrackingProgress { Status = currentStatus });

            var dt = ParseCsvFile(outFile);

            string finalFile2 = Path.Combine(progressDir, "final.txt");
            bool wasLimited = false;
            try { if (File.Exists(finalFile2)) { var fc2 = File.ReadAllText(finalFile2).Trim();  if (fc2.Contains("LIMIT")) wasLimited = true; } } catch { }

            currentStatus = wasLimited
                ? $"Завершено. Записей: {dt?.Rows.Count ?? 0} ⚠ Достигнут лимит 150000 — показаны не все записи"
                : $"Завершено. Найдено записей: {dt?.Rows.Count ?? 0}";
            return (dt, currentStatus);
        }
        finally
        {
            try { if (File.Exists(tempFile)) File.Delete(tempFile); } catch { }
            try { if (File.Exists(outFile)) File.Delete(outFile); } catch { }
            try { if (Directory.Exists(outDir)) Directory.Delete(outDir, true); } catch { }
            try { if (Directory.Exists(progressDir)) Directory.Delete(progressDir, true); } catch { }
        }
    }

    private static string BuildTrackingScript(
        string outFile, string outDir, string progressDir,
        DateTime startDate, DateTime endDate,
        string? senderEmail, string? recipientEmail,
        string? eventId, string? source, string? messageId)
    {
        string startDateStr = startDate.ToString("yyyy-MM-dd HH:mm:ss");
        string endDateStr = endDate.ToString("yyyy-MM-dd HH:mm:ss");

        var sb = new StringBuilder();
        sb.AppendLine("$ErrorActionPreference = 'Continue'");
        sb.AppendLine($"$outFile = '{EscapePsSingleQuote(outFile.Replace("\\", "\\\\"))}'");
        sb.AppendLine($"$outDir = '{EscapePsSingleQuote(outDir.Replace("\\", "\\\\"))}'");
        sb.AppendLine($"$progressDir = '{EscapePsSingleQuote(progressDir.Replace("\\", "\\\\"))}'");
        sb.AppendLine($"$startDate = '{startDateStr}'");
        sb.AppendLine($"$endDate = '{endDateStr}'");

        sb.AppendLine("$senderEmail = $null");
        sb.AppendLine("$recipientEmail = $null");
        sb.AppendLine("$eventIdFilter = $null");
        sb.AppendLine("$sourceFilter = $null");
        sb.AppendLine("$messageIdFilter = $null");

        if (!string.IsNullOrEmpty(senderEmail))
            sb.AppendLine($"$senderEmail = '{EscapePsSingleQuote(senderEmail)}'");
        if (!string.IsNullOrEmpty(recipientEmail))
            sb.AppendLine($"$recipientEmail = '{EscapePsSingleQuote(recipientEmail)}'");
        if (!string.IsNullOrEmpty(eventId))
            sb.AppendLine($"$eventIdFilter = '{EscapePsSingleQuote(eventId)}'");
        if (!string.IsNullOrEmpty(source))
            sb.AppendLine($"$sourceFilter = '{EscapePsSingleQuote(source)}'");
        if (!string.IsNullOrEmpty(messageId))
            sb.AppendLine($"$messageIdFilter = '{EscapePsSingleQuote(messageId)}'");

        sb.AppendLine();
        sb.AppendLine("$maxParallel = 10");
        sb.AppendLine("$maxTotalRecords = 150000");
        sb.AppendLine();
        sb.AppendLine("New-Item -ItemType Directory -Path $outDir -Force | Out-Null");
        sb.AppendLine("New-Item -ItemType Directory -Path $progressDir -Force | Out-Null");
        sb.AppendLine();
        sb.AppendLine("try {");
        sb.AppendLine("    $sessionOption = New-PSSessionOption -UICulture 'ru-RU'");
        sb.AppendLine("    $sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop");
        sb.AppendLine("    $allServers = Invoke-Command -Session $sess -ScriptBlock { Get-ExchangeServer } -ErrorAction SilentlyContinue");
        sb.AppendLine("    $exchangeServers = @($allServers | Where-Object { $_.ServerRole -like '*Mailbox*' } | Select-Object -ExpandProperty Name)");
        sb.AppendLine("    Remove-PSSession $sess -ErrorAction SilentlyContinue");
        sb.AppendLine("    $serverCount = $exchangeServers.Count");
        sb.AppendLine("    \"SERVERS|$serverCount\" | Out-File (Join-Path $progressDir 'meta.txt') -Encoding UTF8");
        sb.AppendLine();
        sb.AppendLine("    $jobScript = {");
        sb.AppendLine("        param($server, $jobIdx, $outDir, $progressDir, $startDate, $endDate, $senderEmail, $recipientEmail, $eventIdFilter, $sourceFilter, $messageIdFilter)");
        sb.AppendLine("        $jobOutFile = Join-Path $outDir \"job_$jobIdx.csv\"");
        sb.AppendLine("        $jobProgressFile = Join-Path $progressDir \"job_$jobIdx.txt\"");
        sb.AppendLine("        \"In progress|$server|0\" | Out-File $jobProgressFile -Encoding UTF8");
        sb.AppendLine("        try {");
        sb.AppendLine("            $sessionOption = New-PSSessionOption -UICulture 'ru-RU'");
        sb.AppendLine("            $sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop");
        sb.AppendLine("            $params = @{ Server = $server; Start = [DateTime]::Parse($startDate); End = [DateTime]::Parse($endDate); ResultSize = 'Unlimited'; ErrorAction = 'SilentlyContinue' }");
        sb.AppendLine("            if ($messageIdFilter) { $params.MessageId = $messageIdFilter }");
        sb.AppendLine("            if ($eventIdFilter) { $params.EventId = $eventIdFilter }");
        sb.AppendLine("            if ($sourceFilter) { $params.Source = $sourceFilter }");
        sb.AppendLine("            if ($senderEmail) { $params.Sender = $senderEmail }");
        sb.AppendLine("            if ($recipientEmail -and -not $senderEmail) { $params.Recipients = $recipientEmail }");
        sb.AppendLine("            $rawResults = Invoke-Command -Session $sess -ScriptBlock { Get-MessageTrackingLog @using:params } -ErrorAction SilentlyContinue");
        sb.AppendLine("            Remove-PSSession $sess -ErrorAction SilentlyContinue");
        sb.AppendLine("            $results = @($rawResults | Where-Object {");
        sb.AppendLine("                $_.Timestamp -ge [DateTime]::Parse($startDate) -and");
        sb.AppendLine("                $_.Timestamp -le [DateTime]::Parse($endDate)");
        sb.AppendLine("            })");
        sb.AppendLine("            if ($senderEmail -and $recipientEmail) {");
        sb.AppendLine("                $results = @($results | Where-Object { $_.Recipients -contains $recipientEmail })");
        sb.AppendLine("            }");
        sb.AppendLine("            $count = $results.Count");
        sb.AppendLine("            foreach ($r in $results) {");
        sb.AppendLine("                $ts = $r.Timestamp.ToString('yyyy-MM-dd HH:mm:ss')");
        sb.AppendLine("                $recipients = if ($r.Recipients) { ($r.Recipients -join '; ') } else { '' }");
        sb.AppendLine("                $subj = if ($r.MessageSubject) { \"$($r.MessageSubject)\" -replace '\\|', '-' -replace '`', \"'\" } else { '' }");
        sb.AppendLine("                $sizeMB = \"$([math]::Round($r.TotalBytes / 1MB, 2))\"");
        sb.AppendLine("                $msgID = if ($r.MessageId) { \"$($r.MessageId)\" } else { '' }");
        sb.AppendLine("                \"$ts|$($r.EventId)|$($r.Sender)|$recipients|$subj|$($r.TotalBytes)|$($r.Source)|$server|$sizeMB|$msgID\" | Out-File $jobOutFile -Append -Encoding UTF8");
        sb.AppendLine("            }");
        sb.AppendLine("            \"Done|$server|$count\" | Out-File $jobProgressFile -Encoding UTF8");
        sb.AppendLine("        }");
        sb.AppendLine("        catch {");
        sb.AppendLine("            $errMsg = $_.Exception.Message.Substring(0, [Math]::Min(60, $_.Exception.Message.Length))");
        sb.AppendLine("            \"Error|$server|0|$errMsg\" | Out-File $jobProgressFile -Encoding UTF8");
        sb.AppendLine("        }");
        sb.AppendLine("    }");
        sb.AppendLine();
        sb.AppendLine("    $runspacePool = [runspacefactory]::CreateRunspacePool(1, $maxParallel)");
        sb.AppendLine("    $runspacePool.Open()");
        sb.AppendLine("    $jobs = @()");
        sb.AppendLine("    $jobIndex = 0");
        sb.AppendLine("    foreach ($server in $exchangeServers) {");
        sb.AppendLine("        $jobIndex++");
        sb.AppendLine("        $ps = [powershell]::Create()");
        sb.AppendLine("        $ps.RunspacePool = $runspacePool");
        sb.AppendLine("        $null = $ps.AddScript($jobScript).AddParameters(@{");
        sb.AppendLine("            server = $server; jobIdx = $jobIndex; outDir = $outDir; progressDir = $progressDir;");
        sb.AppendLine("            startDate = $startDate; endDate = $endDate;");
        sb.AppendLine("            senderEmail = $senderEmail; recipientEmail = $recipientEmail;");
        sb.AppendLine("            eventIdFilter = $eventIdFilter; sourceFilter = $sourceFilter; messageIdFilter = $messageIdFilter");
        sb.AppendLine("        })");
        sb.AppendLine("        $jobs += [PSCustomObject]@{ PS = $ps; Handle = $ps.BeginInvoke() }");
        sb.AppendLine("    }");
        sb.AppendLine();
        sb.AppendLine("    foreach ($job in $jobs) {");
        sb.AppendLine("        $job.PS.EndInvoke($job.Handle)");
        sb.AppendLine("        $job.PS.Dispose()");
        sb.AppendLine("    }");
        sb.AppendLine("    $runspacePool.Close()");
        sb.AppendLine("    $runspacePool.Dispose()");
        sb.AppendLine();
        sb.AppendLine("    'Timestamp|EventId|Sender|Recipients|MessageSubject|TotalBytes|Source|Server|SizeMB|MessageID' | Out-File $outFile -Encoding UTF8");
        sb.AppendLine("    $totalRecords = 0");
        sb.AppendLine("    $limitReached = $false");
        sb.AppendLine("    for ($i = 1; $i -le $serverCount; $i++) {");
        sb.AppendLine("        $jobFile = Join-Path $outDir \"job_$i.csv\"");
        sb.AppendLine("        if (Test-Path $jobFile) {");
        sb.AppendLine("            $content = Get-Content $jobFile -Encoding UTF8");
        sb.AppendLine("            $lineCount = @($content).Count");
        sb.AppendLine("            if ($totalRecords + $lineCount -gt $maxTotalRecords) {");
        sb.AppendLine("                $remaining = $maxTotalRecords - $totalRecords");
        sb.AppendLine("                $content | Select-Object -First $remaining | Out-File $outFile -Append -Encoding UTF8");
        sb.AppendLine("                $totalRecords = $maxTotalRecords");
        sb.AppendLine("                $limitReached = $true");
        sb.AppendLine("                Remove-Item $jobFile -Force -ErrorAction SilentlyContinue");
        sb.AppendLine("                break");
        sb.AppendLine("            }");
        sb.AppendLine("            $content | Out-File $outFile -Append -Encoding UTF8");
        sb.AppendLine("            $totalRecords += $lineCount");
        sb.AppendLine("            Remove-Item $jobFile -Force -ErrorAction SilentlyContinue");
        sb.AppendLine("        }");
        sb.AppendLine("    }");
        sb.AppendLine();
        sb.AppendLine("    if ($limitReached) {");
        sb.AppendLine("        \"COMPLETE|LIMIT|$totalRecords\" | Out-File (Join-Path $progressDir 'final.txt') -Encoding UTF8");
        sb.AppendLine("    } else {");
        sb.AppendLine("        \"COMPLETE|OK|$totalRecords\" | Out-File (Join-Path $progressDir 'final.txt') -Encoding UTF8");
        sb.AppendLine("    }");
        sb.AppendLine("}");
        sb.AppendLine("catch {");
        sb.AppendLine("    $errMsg = $_.Exception.Message");
        sb.AppendLine("    'ERROR:' + $errMsg | Out-File (Join-Path $progressDir 'final.txt') -Encoding UTF8");
        sb.AppendLine("}");

        return sb.ToString();
    }

    private async Task<DataTable?> RunScriptAsync(string mode, CancellationToken ct = default)
    {
        string email = GetEmail();

        if (string.IsNullOrEmpty(email))
        {
            return null;
        }

        string tempFile = Path.Combine(Path.GetTempPath(), $"ggbm_e_{mode}_{Guid.NewGuid()}.ps1");
        string outFile = Path.Combine(Path.GetTempPath(), $"ggbm_e_{mode}_{Guid.NewGuid()}.csv");

        string ps = mode switch
        {
            "quota" => $@"
$ErrorActionPreference = 'Stop'
try {{
$sessionOption = New-PSSessionOption -UICulture 'ru-RU'
$sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
$stats = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxStatistics -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
$mailbox = Invoke-Command -Session $sess -ScriptBlock {{ Get-Mailbox -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
Remove-PSSession $sess -ErrorAction SilentlyContinue
'Property|Value' | Out-File '{outFile}' -Encoding UTF8
if ($stats) {{
    ""DisplayName|$($stats.DisplayName)"" | Out-File '{outFile}' -Append -Encoding UTF8
    $sizeStr = ""$($stats.TotalItemSize)"" -replace '\s*\([\d,\s]+\s*bytes\)', ''
    ""TotalItemSize|$sizeStr"" | Out-File '{outFile}' -Append -Encoding UTF8
    ""ItemCount|$($stats.ItemCount)"" | Out-File '{outFile}' -Append -Encoding UTF8
    $quotaStr = if ($stats.DatabaseProhibitSendReceiveQuota) {{ ""$($stats.DatabaseProhibitSendReceiveQuota)"" }} else {{ 'N/A' }}
    ""DatabaseProhibitSendReceiveQuota|$quotaStr"" | Out-File '{outFile}' -Append -Encoding UTF8
    $mbType = if ($mailbox) {{ ""$($mailbox.RecipientTypeDetails)"" }} else {{ 'Unknown' }}
    ""MailboxType|$mbType"" | Out-File '{outFile}' -Append -Encoding UTF8
}}
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}",
            "folders" => $@"
$ErrorActionPreference = 'Stop'
try {{
$sessionOption = New-PSSessionOption -UICulture 'ru-RU'
$sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
$folders = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxFolderStatistics -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
Remove-PSSession $sess -ErrorAction SilentlyContinue
'FolderPath|FolderSize|ItemsInFolder' | Out-File '{outFile}' -Encoding UTF8
foreach ($f in $folders) {{
    $size = if ($f.FolderSize) {{ ""$($f.FolderSize)"" -replace '\s*\([\d,\s]+\s*bytes\)', '' }} else {{ '0 B' }}
    $path = $f.FolderPath -replace '\|', ' :: '
    ""$path|$size|$($f.ItemsInFolder)"" | Out-File '{outFile}' -Append -Encoding UTF8
}}
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}",
            "deleted" => $@"
$ErrorActionPreference = 'Stop'
try {{
$sessionOption = New-PSSessionOption -UICulture 'ru-RU'
$sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
$stats = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxStatistics -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
$recoverable = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxFolderStatistics -Identity $args[0] -FolderScope RecoverableItems -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
Remove-PSSession $sess -ErrorAction SilentlyContinue
'Category|Name|Value|ItemCount|Size' | Out-File '{outFile}' -Encoding UTF8
if ($stats) {{
    ""Basic Info|DisplayName|$($stats.DisplayName)||"" | Out-File '{outFile}' -Append -Encoding UTF8
    ""Basic Info|DeletedItemCount|$($stats.DeletedItemCount)||"" | Out-File '{outFile}' -Append -Encoding UTF8
    $tdSize = if ($stats.TotalDeletedItemSize) {{ ""$($stats.TotalDeletedItemSize)"" }} else {{ '0 B' }}
    ""Basic Info|TotalDeletedItemSize|$tdSize||"" | Out-File '{outFile}' -Append -Encoding UTF8
}}
foreach ($r in $recoverable) {{
    $rSize = if ($r.FolderSize) {{ ""$($r.FolderSize)"" }} else {{ '0 B' }}
    $rName = $r.Name -replace '\|', ' :: '
    ""RecoverableItems|$rName||$($r.ItemsInFolderAndSubfolders)|$rSize"" | Out-File '{outFile}' -Append -Encoding UTF8
}}
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}",
            "fullinfo" => $@"
$ErrorActionPreference = 'Stop'
try {{
$sessionOption = New-PSSessionOption -UICulture 'ru-RU'
$sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
$mailboxObj = Invoke-Command -Session $sess -ScriptBlock {{ Get-Mailbox -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
Remove-PSSession $sess -ErrorAction SilentlyContinue
'Property|Value' | Out-File '{outFile}' -Encoding UTF8
if ($mailboxObj) {{
    foreach ($prop in $mailboxObj.PSObject.Properties) {{
        $val = ""$($prop.Value)""
        $val = $val -replace '\|', ' :: '
        ""$($prop.Name)|$val"" | Out-File '{outFile}' -Append -Encoding UTF8
    }}
}}
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}",
            "calendar" => $@"
$ErrorActionPreference = 'Stop'
try {{
$mailboxEmail = '{email}'
$mailboxLogin = '{email}' -replace '@.*', ''
$sessionOption = New-PSSessionOption -UICulture 'ru-RU'
$sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
$allPerms = $null
$allPerms = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxFolderPermission -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList ($mailboxEmail + ':\Calendar')
if (-not $allPerms) {{ $allPerms = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxFolderPermission -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList ($mailboxLogin + ':\Calendar') }}
if (-not $allPerms) {{ $allPerms = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxFolderPermission -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList ($mailboxEmail + ':\' + [char]0x041A + [char]0x0430 + [char]0x043B + [char]0x0435 + [char]0x043D + [char]0x0434 + [char]0x0430 + [char]0x0440 + [char]0x044C) }}
if (-not $allPerms) {{ $allPerms = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxFolderPermission -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList ($mailboxLogin + ':\' + [char]0x041A + [char]0x0430 + [char]0x043B + [char]0x0435 + [char]0x043D + [char]0x0434 + [char]0x0430 + [char]0x0440 + [char]0x044C) }}
if (-not $allPerms) {{
    $folderStats = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxFolderStatistics -Identity $args[0] -FolderScope Calendar -ErrorAction SilentlyContinue }} -ArgumentList $mailboxEmail
    if ($folderStats) {{
        $calPath = ""$($folderStats[0].FolderPath)"".TrimStart('/')
        $allPerms = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxFolderPermission -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList ($mailboxEmail + ':\' + $calPath)
    }}
}}
Remove-PSSession $sess -ErrorAction SilentlyContinue
'User|AccessRights' | Out-File '{outFile}' -Encoding UTF8
if ($allPerms) {{
    foreach ($perm in $allPerms) {{
        $u = if ($perm.User) {{ ""$($perm.User)"" }} else {{ 'N/A' }}
        $r = if ($perm.AccessRights) {{ ($perm.AccessRights -join ', ') }} else {{ 'N/A' }}
        ""$u|$r"" | Out-File '{outFile}' -Append -Encoding UTF8
    }}
}}
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}",
            "inboxrules" => $@"
$ErrorActionPreference = 'Stop'
try {{
$sessionOption = New-PSSessionOption -UICulture 'ru-RU'
$sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
$rules = Invoke-Command -Session $sess -ScriptBlock {{ Get-InboxRule -Mailbox $args[0] -IncludeHidden -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
Remove-PSSession $sess -ErrorAction SilentlyContinue
'Name|From|MoveToFolder|Description|ForwardTo|RedirectTo|DeleteMessage|CopyToFolder' | Out-File '{outFile}' -Encoding UTF8
if ($rules) {{
    foreach ($rule in $rules) {{
        $name = if ($rule.Name) {{ ""$($rule.Name)"" -replace '\|', ' ' }} else {{ '' }}
        $from = ''
        if ($rule.From) {{
            $fromList = @($rule.From | ForEach-Object {{ $v = ""$_""; if ($v -and $v -notmatch 'ArrayList|Collections') {{ $v }} }} | Select-Object -Unique)
            $from = $fromList -join '; '
        }}
        $moveTo = ''
        if ($rule.MoveToFolder) {{
            $moveList = @($rule.MoveToFolder | ForEach-Object {{ $v = ""$_""; if ($v -and $v -notmatch 'ArrayList|Collections') {{ $v }} }} | Select-Object -Unique)
            $moveTo = $moveList -join '; '
        }}
        $forwardTo = ''
        if ($rule.ForwardTo) {{ $forwardTo = ($rule.ForwardTo | ForEach-Object {{ $_.ToString() }}) -join '; ' }}
        $forwardTo = $forwardTo -replace '\|', ' '
        $redirectTo = ''
        if ($rule.RedirectTo) {{ $redirectTo = ($rule.RedirectTo | ForEach-Object {{ $_.ToString() }}) -join '; ' }}
        $redirectTo = $redirectTo -replace '\|', ' '
        $deleteMessage = if ($rule.DeleteMessage) {{ 'Yes' }} else {{ '' }}
        $copyToFolder = ''
        if ($rule.CopyToFolder) {{ $copyToFolder = $rule.CopyToFolder.ToString() }}
        $copyToFolder = $copyToFolder -replace '\|', ' '
        $descParts = @()
        if ($rule.Description) {{
            $rule.Description | ForEach-Object {{
                $v = ""$_""
                if ($v -and $v -notmatch 'ArrayList|Collections' -and $v.Length -gt 1) {{
                    $cleaned = $v -replace '\|', ' ' -replace '\r?\n', '[BR]'
                    $descParts += $cleaned.Trim()
                }}
            }}
        }}
        $desc = $descParts -join ' [BR] '
        ""$name|$from|$moveTo|$desc|$forwardTo|$redirectTo|$deleteMessage|$copyToFolder"" | Out-File '{outFile}' -Append -Encoding UTF8
    }}
}}
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}",
            _ => ""
        };

        if (string.IsNullOrEmpty(ps))
        {
            return null;
        }

        try
        {
            File.WriteAllText(tempFile, ps, new System.Text.UTF8Encoding(false));

            var psi = new System.Diagnostics.ProcessStartInfo();
            psi.FileName = "powershell.exe";
            psi.Arguments = $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tempFile}\"";
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;

            var sw = System.Diagnostics.Stopwatch.StartNew();
            using var proc = System.Diagnostics.Process.Start(psi);
            var waitTask = proc.WaitForExitAsync();
            var timeoutTask = Task.Delay(90000);
            using var ctReg = ct.Register(() => { try { proc.Kill(); } catch { } });
            var completedTask = await Task.WhenAny(waitTask, timeoutTask);
            sw.Stop();

            if (ct.IsCancellationRequested)
            {
                ct.ThrowIfCancellationRequested();
            }

            if (completedTask == timeoutTask)
            {
                try { proc?.Kill(); } catch { }
            }
            else
            {
            }

            string stdout = "";
            string stderr = "";
            try { stdout = proc?.StandardOutput?.ReadToEnd() ?? ""; } catch { }
            try { stderr = proc?.StandardError?.ReadToEnd() ?? ""; } catch { }

            ct.ThrowIfCancellationRequested();

            if (File.Exists(outFile))
            {
                var fi = new FileInfo(outFile);
            }
            else
            {
            }

            var result = ParseCsvFile(outFile);
            return result;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw;
        }
        finally
        {
            try { if (File.Exists(tempFile)) File.Delete(tempFile); } catch { }
            try { if (File.Exists(outFile)) File.Delete(outFile); } catch { }
        }
    }

    private DataTable? ParseCsvFile(string outFile)
    {

        if (!File.Exists(outFile))
        {
            return null;
        }

        var lines = File.ReadAllLines(outFile);

        if (lines.Length <= 1)
        {
            return null;
        }

        var headers = lines[0].Split('|');

        if (headers.Length > 0 && headers[0] == "ERROR")
        {
            var errorMsg = lines.Length > 1 ? lines[1] : "Unknown error";
            throw new Exception($"Exchange: {errorMsg}");
        }

        var dt = new DataTable();
        foreach (var h in headers) dt.Columns.Add(h);

        for (int i = 1; i < lines.Length; i++)
        {
            var vals = lines[i].Split('|');
            var row = dt.NewRow();
            for (int j = 0; j < Math.Min(vals.Length, dt.Columns.Count); j++)
                row[j] = vals[j].Replace(" :: ", "|").Replace("[BR]", "\n");
            dt.Rows.Add(row);
        }


        File.Delete(outFile);
        return dt;
    }

    private async void ExportXlsx_Click(object? sender, RoutedEventArgs e)
    {
        if (_currentData == null || _currentData.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var topLevel = GetTopLevel(this);
        if (topLevel == null) {  return; }

        IStorageFile? file = null;
        try
        {
            file = await topLevel.StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "Экспорт в Excel",
                SuggestedFileName = FileDialogHelper.SanitizeFileName($"Exchange_{_mailbox}"),
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
            var ex = await Task.Run(() => log.WriteXlsx(_currentData));
            if (ex != null)
            {
                await ShowMessageAsync(ex.Message);
            }
            else
            {
                await ShowMessageAsync("Успешно!");
            }
        }
        else
        {
        }
    }

    private async void CopyToClipboard_Click(object? sender, RoutedEventArgs e)
    {
        if (_currentData == null || _currentData.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для копирования.");
            return;
        }

        try
        {
            var sb = new System.Text.StringBuilder();
            
            for (int i = 0; i < _currentData.Columns.Count; i++)
            {
                sb.Append(_currentData.Columns[i].ColumnName);
                if (i < _currentData.Columns.Count - 1)
                    sb.Append('\t');
            }
            sb.AppendLine();

            for (int row = 0; row < _currentData.Rows.Count; row++)
            {
                for (int col = 0; col < _currentData.Columns.Count; col++)
                {
                    var val = _currentData.Rows[row][col]?.ToString() ?? "";
                    val = val.Replace("\r", "").Replace("\n", " ").Replace("\t", " ");
                    sb.Append(val);
                    if (col < _currentData.Columns.Count - 1)
                        sb.Append('\t');
                }
                sb.AppendLine();
            }

            var topLevel = GetTopLevel(this);
            if (topLevel?.Clipboard != null)
            {
                await topLevel.Clipboard.SetTextAsync(sb.ToString());
                await ShowMessageAsync($"Скопировано {_currentData.Rows.Count} строк в буфер обмена!");
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

    private async void ExportTxt_Click(object? sender, RoutedEventArgs e)
    {
        if (_currentData == null || _currentData.Rows.Count == 0)
        {
            await ShowMessageAsync("Нет данных для экспорта.");
            return;
        }

        var topLevel = GetTopLevel(this);
        if (topLevel == null) {  return; }

        IStorageFile? file = null;
        try
        {
            file = await topLevel.StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = "Экспорт в текст",
                SuggestedFileName = FileDialogHelper.SanitizeFileName($"Exchange_{_mailbox}"),
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
            var ex = await Task.Run(() => log.WriteTxt(_currentData));
            if (ex != null)
            {
                await ShowMessageAsync(ex.Message);
            }
            else
            {
                await ShowMessageAsync("Успешно!");
            }
        }
        else
        {
        }
    }

    private bool _isAutoReplyMode = false;
    private string _autoReplyInternalHtml = "";
    private string _autoReplyExternalHtml = "";

    private int GetAutoReplyScope() => AutoReplyScopeComboBox.SelectedIndex;

    private void AutoReplyScope_Changed(object? sender, SelectionChangedEventArgs e)
    {
        if (!_isAutoReplyMode) return;
        int scope = GetAutoReplyScope();
        string html = scope == 2 ? _autoReplyExternalHtml : _autoReplyInternalHtml;
        if (!string.IsNullOrEmpty(html))
        {
            AutoReplyTextBox.Text = HtmlToPlainText(html);
            AutoReplyPreviewBox.Text = html;
        }
        else
        {
            AutoReplyTextBox.Text = "";
            AutoReplyPreviewBox.Text = "";
        }
    }

    private async void ShowAutoReply_Click(object? sender, RoutedEventArgs e)
    {
        _isAutoReplyMode = true;
        _isTrackingMode = false;
        _currentSearchMode = "autoreply";
        AutoReplyPanel.IsVisible = true;
        AutoReplySchedulePanel.IsVisible = true;
        TrackingPanel.IsVisible = false;
        MainContentGrid.IsVisible = false;
        CancelCurrentLoad();
        LoadingOverlay.IsVisible = false;
        await AutoReplyRefresh_ClickAsync();
    }

    private async void AutoReplyRefresh_Click(object? sender, RoutedEventArgs e)
    {
        await AutoReplyRefresh_ClickAsync();
    }

    private async Task AutoReplyRefresh_ClickAsync()
    {
        string email = GetEmail();
        if (string.IsNullOrEmpty(email))
        {
            await ShowMessageAsync("Не указан почтовый ящик.");
            return;
        }

        AutoReplyErrorText.IsVisible = false;
        AutoReplySetButton.IsEnabled = false;
        AutoReplyDisableButton.IsEnabled = false;

        try
        {
            var (status, internalHtml, externalHtml, scheduleText) = await GetAutoReplyStateAsync(email);

            _autoReplyInternalHtml = internalHtml ?? "";
            _autoReplyExternalHtml = externalHtml ?? "";

            AutoReplyStatusText.Text = status;
            AutoReplyScheduleText.Text = scheduleText ?? "";

            int scope = GetAutoReplyScope();
            string displayHtml = scope == 2 ? _autoReplyExternalHtml : _autoReplyInternalHtml;
            if (!string.IsNullOrEmpty(displayHtml))
            {
                AutoReplyTextBox.Text = HtmlToPlainText(displayHtml);
                AutoReplyPreviewBox.Text = displayHtml;
            }
            else
            {
                AutoReplyTextBox.Text = "";
                AutoReplyPreviewBox.Text = "";
            }

            if (status == "Enabled" || status == "Scheduled")
            {
                AutoReplyDisableButton.IsEnabled = true;
            }
            else
            {
                AutoReplyDisableButton.IsEnabled = false;
            }

            AutoReplySetButton.IsEnabled = true;
        }
        catch (Exception ex)
        {
            AutoReplyErrorText.Text = $"Ошибка: {ex.Message}";
            AutoReplyErrorText.IsVisible = true;
            AutoReplySetButton.IsEnabled = true;
        }
    }

    private async Task<(string status, string internalHtml, string externalHtml, string scheduleText)> GetAutoReplyStateAsync(string email)
    {
        string tempFile = Path.Combine(Path.GetTempPath(), $"ggbm_ar_get_{Guid.NewGuid():N}.ps1");
        string outFile = Path.Combine(Path.GetTempPath(), $"ggbm_ar_get_{Guid.NewGuid():N}.csv");

        string ps = $@"
$ErrorActionPreference = 'Stop'
try {{
    $sessionOption = New-PSSessionOption -UICulture 'ru-RU'
    $sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
    $reply = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxAutoReplyConfiguration -Identity $args[0] -ErrorAction Stop }} -ArgumentList '{EscapePsSingleQuote(email)}'
    Remove-PSSession $sess -ErrorAction SilentlyContinue
    'Status|InternalMessage|ExternalMessage|State|StartTime|EndTime' | Out-File '{outFile}' -Encoding UTF8
    $status = 'Disabled'
    $internal = $reply.InternalMessage
    $external = $reply.ExternalMessage
    $state = ""$($reply.AutoReplyState)""
    $startTime = ""$($reply.StartTime)""
    $endTime = ""$($reply.EndTime)""
    if ($reply.AutoReplyState -eq 'Enabled') {{
        $status = 'Enabled'
    }} elseif ($reply.AutoReplyState -eq 'Scheduled') {{
        $status = 'Scheduled'
    }}
    $internal = $internal -replace '\r?\n', '[BR]'
    $internal = $internal -replace '\|', '[PIPE]'
    $external = $external -replace '\r?\n', '[BR]'
    $external = $external -replace '\|', '[PIPE]'
    ""$status|$internal|$external|$state|$startTime|$endTime"" | Out-File '{outFile}' -Append -Encoding UTF8
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}
";

        try
        {
            File.WriteAllText(tempFile, ps, new UTF8Encoding(false));

            var psi = new System.Diagnostics.ProcessStartInfo();
            psi.FileName = "powershell.exe";
            psi.Arguments = $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tempFile}\"";
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;


            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc == null)
            {
                throw new Exception("Не удалось запустить PowerShell.");
            }

            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            var stderrTask = proc.StandardError.ReadToEndAsync();
            var waitTask = proc.WaitForExitAsync();
            var timeoutTask = Task.Delay(60000);
            var completedTask = await Task.WhenAny(waitTask, timeoutTask);
            if (completedTask == timeoutTask)
            {
                try { proc.Kill(); } catch { }
                throw new Exception("Превышено время ожидания ответа от Exchange (60с).");
            }

            var stdout = await stdoutTask;
            var stderr = await stderrTask;
            if (!string.IsNullOrWhiteSpace(stderr))

            if (!File.Exists(outFile))
            {
                throw new Exception("Не удалось получить ответ от Exchange. stderr: " + stderr);
            }

            var lines = File.ReadAllLines(outFile);
            if (lines.Length > 0 && lines[0] == "ERROR")
            {
                var msg = lines.Length > 1 ? lines[1] : "Unknown error";
                throw new Exception($"Exchange: {msg}");
            }

            if (lines.Length < 2)
                throw new Exception("Пустой ответ от Exchange.");

            var parts = lines[1].Split('|');
            var status = parts.Length > 0 ? parts[0] : "Unknown";
            var internalHtml = parts.Length > 1 ? parts[1] : "";
            var externalHtml = parts.Length > 2 ? parts[2] : "";
            var state = parts.Length > 3 ? parts[3] : "";
            var startTimeStr = parts.Length > 4 ? parts[4] : "";
            var endTimeStr = parts.Length > 5 ? parts[5] : "";

            internalHtml = internalHtml.Replace("[BR]", "\n").Replace("[PIPE]", "|");
            externalHtml = externalHtml.Replace("[BR]", "\n").Replace("[PIPE]", "|");

            string scheduleText = "";
            if (state == "Scheduled" && !string.IsNullOrEmpty(startTimeStr) && !string.IsNullOrEmpty(endTimeStr))
                scheduleText = $"Расписание: {startTimeStr} — {endTimeStr}";

            return (status, internalHtml, externalHtml, scheduleText);
        }
        finally
        {
            try { if (File.Exists(tempFile)) File.Delete(tempFile); } catch { }
            try { if (File.Exists(outFile)) File.Delete(outFile); } catch { }
        }
    }

    private async void AutoReplySet_Click(object? sender, RoutedEventArgs e)
    {
        string email = GetEmail();
        if (string.IsNullOrEmpty(email))
        {
            await ShowMessageAsync("Не указан почтовый ящик.");
            return;
        }

        string plainText = AutoReplyTextBox.Text ?? "";
        if (string.IsNullOrWhiteSpace(plainText))
        {
            await ShowMessageAsync("Текст автоответа не может быть пустым.");
            return;
        }

        string html = PlainTextToHtml(plainText);

        AutoReplyErrorText.IsVisible = false;
        AutoReplySetButton.IsEnabled = false;

        try
        {
            bool useSchedule = AutoReplyScheduleCheckBox.IsChecked == true;
            DateTime? startTime = null;
            DateTime? endTime = null;

            if (useSchedule)
            {
                if (AutoReplyStartDate.SelectedDate.HasValue)
                    startTime = CombineWithTime(AutoReplyStartDate.SelectedDate.Value, AutoReplyStartTime.Text ?? "09:00");
                if (AutoReplyEndDate.SelectedDate.HasValue)
                    endTime = CombineWithTime(AutoReplyEndDate.SelectedDate.Value, AutoReplyEndTime.Text ?? "18:00");

                if (!startTime.HasValue || !endTime.HasValue)
                {
                    await ShowMessageAsync("Укажите даты начала и окончания расписания.");
                    AutoReplySetButton.IsEnabled = true;
                    return;
                }
                if (endTime < startTime)
                {
                    await ShowMessageAsync("Дата окончания не может быть раньше даты начала.");
                    AutoReplySetButton.IsEnabled = true;
                    return;
                }
            }

            await SetAutoReplyStateAsync(email, html, GetAutoReplyScope(), useSchedule, startTime, endTime);

            int scope = GetAutoReplyScope();
            if (scope == 2)
                _autoReplyExternalHtml = html;
            else
                _autoReplyInternalHtml = html;
            if (scope == 0)
                _autoReplyExternalHtml = html;

            AutoReplyStatusText.Text = useSchedule ? "Scheduled" : "Enabled";
            AutoReplyScheduleText.Text = useSchedule ? $"Расписание: {startTime:dd.MM.yyyy HH:mm} — {endTime:dd.MM.yyyy HH:mm}" : "";
            AutoReplyDisableButton.IsEnabled = true;
            AutoReplyPreviewBox.Text = html;

            await ShowMessageAsync("Автоответ установлен.");
            AutoReplySetButton.IsEnabled = true;
        }
        catch (Exception ex)
        {
            AutoReplyErrorText.Text = $"Ошибка: {ex.Message}";
            AutoReplyErrorText.IsVisible = true;
            AutoReplySetButton.IsEnabled = true;
        }
    }

    private async Task SetAutoReplyStateAsync(string email, string html, int scope, bool useSchedule, DateTime? startTime, DateTime? endTime)
    {
        string tempFile = Path.Combine(Path.GetTempPath(), $"ggbm_ar_set_{Guid.NewGuid():N}.ps1");
        string outFile = Path.Combine(Path.GetTempPath(), $"ggbm_ar_set_{Guid.NewGuid():N}.csv");
        string htmlFile = Path.Combine(Path.GetTempPath(), $"ggbm_ar_html_{Guid.NewGuid():N}.bin");

        string htmlBase64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(html));
        File.WriteAllText(htmlFile, htmlBase64, new UTF8Encoding(false));

        string scheduleParams = "";
        string state = "Enabled";
        if (useSchedule && startTime.HasValue && endTime.HasValue)
        {
            state = "Scheduled";
            scheduleParams = $" -StartTime '{startTime:yyyy-MM-dd HH:mm:ss}' -EndTime '{endTime:yyyy-MM-dd HH:mm:ss}'";
        }

        string msgParams = scope switch
        {
            1 => " -InternalMessage $msg",
            2 => " -ExternalMessage $msg",
            _ => " -InternalMessage $msg -ExternalMessage $msg"
        };

        string ps = $@"
$ErrorActionPreference = 'Stop'
try {{
    $htmlB64 = Get-Content -Raw -Path '{EscapePsSingleQuote(htmlFile)}'
    $html = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($htmlB64))

    $sessionOption = New-PSSessionOption -UICulture 'ru-RU'
    $sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop

    Invoke-Command -Session $sess -ScriptBlock {{
        param($mb, $msg)
        Set-MailboxAutoReplyConfiguration -Identity $mb -AutoReplyState '{state}'{msgParams}{scheduleParams} -ErrorAction Stop
    }} -ArgumentList '{EscapePsSingleQuote(email)}', $html

    Remove-PSSession $sess -ErrorAction SilentlyContinue
    'OK' | Out-File '{outFile}' -Encoding UTF8
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}
";

        try
        {
            File.WriteAllText(tempFile, ps, new UTF8Encoding(false));

            var psi = new System.Diagnostics.ProcessStartInfo();
            psi.FileName = "powershell.exe";
            psi.Arguments = $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tempFile}\"";
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;


            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc == null)
            {
                throw new Exception("Не удалось запустить PowerShell.");
            }

            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            var stderrTask = proc.StandardError.ReadToEndAsync();
            var waitTask = proc.WaitForExitAsync();
            var timeoutTask = Task.Delay(60000);
            var completedTask = await Task.WhenAny(waitTask, timeoutTask);

            if (completedTask == timeoutTask)
            {
                try { proc.Kill(); } catch { }
                throw new Exception("Превышено время ожидания ответа от Exchange (60с).");
            }

            var stdout = await stdoutTask;
            var stderr = await stderrTask;
            if (!string.IsNullOrWhiteSpace(stdout))
            if (!string.IsNullOrWhiteSpace(stderr))

            if (!File.Exists(outFile))
            {
                throw new Exception("Не удалось получить ответ от Exchange. stderr: " + stderr);
            }

            var lines = File.ReadAllLines(outFile);
            if (lines.Length > 0 && lines[0] == "ERROR")
            {
                var msg = lines.Length > 1 ? lines[1] : "Unknown error";
                throw new Exception($"Exchange: {msg}");
            }
        }
        finally
        {
            try { if (File.Exists(tempFile)) File.Delete(tempFile); } catch { }
            try { if (File.Exists(outFile)) File.Delete(outFile); } catch { }
            try { if (File.Exists(htmlFile)) File.Delete(htmlFile); } catch { }
        }
    }

    private async void AutoReplyDisable_Click(object? sender, RoutedEventArgs e)
    {
        string email = GetEmail();
        if (string.IsNullOrEmpty(email)) return;

        AutoReplyErrorText.IsVisible = false;
        AutoReplyDisableButton.IsEnabled = false;

        try
        {
            await DisableAutoReplyStateAsync(email);

            AutoReplyStatusText.Text = "Disabled";
            AutoReplyScheduleText.Text = "";
            AutoReplyDisableButton.IsEnabled = false;

            await ShowMessageAsync("Автоответ отключён.");
        }
        catch (Exception ex)
        {
            AutoReplyErrorText.Text = $"Ошибка: {ex.Message}";
            AutoReplyErrorText.IsVisible = true;
            AutoReplyDisableButton.IsEnabled = true;
        }
    }

    private async Task DisableAutoReplyStateAsync(string email)
    {
        string tempFile = Path.Combine(Path.GetTempPath(), $"ggbm_ar_dis_{Guid.NewGuid():N}.ps1");
        string outFile = Path.Combine(Path.GetTempPath(), $"ggbm_ar_dis_{Guid.NewGuid():N}.csv");

        string ps = $@"
$ErrorActionPreference = 'Stop'
try {{
    $sessionOption = New-PSSessionOption -UICulture 'ru-RU'
    $sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
    Invoke-Command -Session $sess -ScriptBlock {{ Set-MailboxAutoReplyConfiguration -Identity $args[0] -AutoReplyState Disabled -ErrorAction Stop }} -ArgumentList '{EscapePsSingleQuote(email)}'
    Remove-PSSession $sess -ErrorAction SilentlyContinue
    'OK' | Out-File '{outFile}' -Encoding UTF8
}} catch {{
    'ERROR' | Out-File '{outFile}' -Encoding UTF8
    $_.Exception.Message | Out-File '{outFile}' -Append -Encoding UTF8
}}
";

        try
        {
            File.WriteAllText(tempFile, ps, new UTF8Encoding(false));

            var psi = new System.Diagnostics.ProcessStartInfo();
            psi.FileName = "powershell.exe";
            psi.Arguments = $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tempFile}\"";
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;


            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc == null)
            {
                throw new Exception("Не удалось запустить PowerShell.");
            }

            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            var stderrTask = proc.StandardError.ReadToEndAsync();
            var waitTask = proc.WaitForExitAsync();
            var timeoutTask = Task.Delay(60000);
            var completedTask = await Task.WhenAny(waitTask, timeoutTask);
            if (completedTask == timeoutTask)
            {
                try { proc.Kill(); } catch { }
                throw new Exception("Превышено время ожидания ответа от Exchange (60с).");
            }

            var stdout = await stdoutTask;
            var stderr = await stderrTask;
            if (!string.IsNullOrWhiteSpace(stderr))

            if (!File.Exists(outFile))
            {
                throw new Exception("Не удалось получить ответ от Exchange. stderr: " + stderr);
            }

            var lines = File.ReadAllLines(outFile);
            if (lines.Length > 0 && lines[0] == "ERROR")
            {
                var msg = lines.Length > 1 ? lines[1] : "Unknown error";
                throw new Exception($"Exchange: {msg}");
            }
        }
        finally
        {
            try { if (File.Exists(tempFile)) File.Delete(tempFile); } catch { }
            try { if (File.Exists(outFile)) File.Delete(outFile); } catch { }
        }
    }

    private void AutoReplySchedule_Changed(object? sender, RoutedEventArgs e)
    {
        AutoReplyScheduleDates.IsVisible = AutoReplyScheduleCheckBox.IsChecked == true;
    }

    private void AutoReplyPreview_Click(object? sender, RoutedEventArgs e)
    {
        string plainText = AutoReplyTextBox.Text ?? "";
        string html = PlainTextToHtml(plainText);
        AutoReplyPreviewBox.Text = html;
    }

    private void FmtBold_Click(object? sender, RoutedEventArgs e)
    {
        WrapSelection("**", "**");
    }

    private void FmtItalic_Click(object? sender, RoutedEventArgs e)
    {
        WrapSelection("*", "*");
    }

    private void FmtUnderline_Click(object? sender, RoutedEventArgs e)
    {
        WrapSelection("__", "__");
    }

    private void FmtList_Click(object? sender, RoutedEventArgs e)
    {
        WrapSelection("\n• ", "");
    }

    private void FmtBR_Click(object? sender, RoutedEventArgs e)
    {
        var tb = AutoReplyTextBox;
        if (tb.Text == null) return;
        var caret = tb.CaretIndex;
        tb.Text = tb.Text.Insert(caret, "\n");
        tb.CaretIndex = caret + 1;
        tb.Focus();
    }

    private void FmtLink_Click(object? sender, RoutedEventArgs e)
    {
        var tb = AutoReplyTextBox;
        if (tb.Text == null) return;
        var selStart = tb.SelectionStart;
        var selEnd = tb.SelectionEnd;
        if (selStart >= 0 && selEnd > selStart && selEnd <= tb.Text.Length)
        {
            var selected = tb.Text.Substring(selStart, selEnd - selStart);
            var replacement = $"[{selected}](https://)";
            tb.Text = tb.Text.Remove(selStart, selEnd - selStart).Insert(selStart, replacement);
            tb.CaretIndex = selStart + replacement.Length;
        }
        else
        {
            var caret = tb.CaretIndex;
            tb.Text = tb.Text.Insert(caret, "[текст ссылки](https://)");
            tb.CaretIndex = caret + "[текст ссылки](https://)".Length;
        }
        tb.Focus();
    }

    private void WrapSelection(string prefix, string suffix)
    {
        var tb = AutoReplyTextBox;
        if (tb.Text == null) return;
        var selStart = tb.SelectionStart;
        var selEnd = tb.SelectionEnd;
        if (selStart >= 0 && selEnd > selStart && selEnd <= tb.Text.Length)
        {
            var selected = tb.Text.Substring(selStart, selEnd - selStart);
            var replacement = prefix + selected + suffix;
            tb.Text = tb.Text.Remove(selStart, selEnd - selStart).Insert(selStart, replacement);
            tb.CaretIndex = selStart + prefix.Length + selected.Length;
            tb.SelectionStart = selStart + prefix.Length;
            tb.SelectionEnd = selStart + prefix.Length + selected.Length;
        }
        else
        {
            var caret = tb.CaretIndex;
            tb.Text = tb.Text.Insert(caret, prefix + suffix);
            tb.CaretIndex = caret + prefix.Length;
        }
        tb.Focus();
    }

    private static string PlainTextToHtml(string plainText)
    {
        if (string.IsNullOrEmpty(plainText))
            return "<html><body></body></html>";

        var sb = new StringBuilder();
        sb.Append("<html><body>");

        var lines = plainText.Split('\n');
        bool inList = false;

        foreach (var line in lines)
        {
            var trimmed = line.TrimEnd();
            if (trimmed.StartsWith("• "))
            {
                if (!inList) { sb.Append("<ul>"); inList = true; }
                sb.Append("<li>").Append(HtmlEncodeText(trimmed.Substring(2))).Append("</li>");
            }
            else
            {
                if (inList) { sb.Append("</ul>"); inList = false; }
                if (string.IsNullOrEmpty(trimmed))
                    sb.Append("<br>");
                else
                    sb.Append("<p>").Append(HtmlEncodeText(trimmed)).Append("</p>");
            }
        }
        if (inList) sb.Append("</ul>");

        sb.Append("</body></html>");
        return ProcessMarkdownToHtml(sb.ToString());
    }

    private static string ProcessMarkdownToHtml(string html)
    {
        html = Regex.Replace(html, @"\*\*(.+?)\*\*", "<b>$1</b>");
        html = Regex.Replace(html, @"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", "<i>$1</i>");
        html = Regex.Replace(html, @"__(.+?)__", "<u>$1</u>");

        var linkRegex = new Regex(@"\[([^\]]+)\]\(([^)]+)\)");
        html = linkRegex.Replace(html, m => $"<a href=\"{m.Groups[2].Value}\">{m.Groups[1].Value}</a>");

        return html;
    }

    private static string HtmlEncodeText(string text)
    {
        var sb = new StringBuilder(text.Length + 16);
        foreach (char c in text)
        {
            switch (c)
            {
                case '<': sb.Append("&lt;"); break;
                case '>': sb.Append("&gt;"); break;
                case '&': sb.Append("&amp;"); break;
                case '"': sb.Append("&quot;"); break;
                default: sb.Append(c); break;
            }
        }
        return sb.ToString();
    }

    private static string HtmlToPlainText(string html)
    {
        if (string.IsNullOrEmpty(html)) return "";

        var text = html;
        text = Regex.Replace(text, @"<style.*?>.*?</style>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
        text = Regex.Replace(text, @"<head.*?>.*?</head>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
        text = Regex.Replace(text, @"<br\s*/?>", "\n", RegexOptions.IgnoreCase);
        text = Regex.Replace(text, @"</p>", "\n", RegexOptions.IgnoreCase);
        text = Regex.Replace(text, @"<li>", "• ", RegexOptions.IgnoreCase);
        text = Regex.Replace(text, @"<[^>]+>", "", RegexOptions.IgnoreCase);
        text = System.Net.WebUtility.HtmlDecode(text);
        text = text.Replace("\r\n", "\n");
        while (text.Contains("\n\n\n"))
            text = text.Replace("\n\n\n", "\n\n");
        return text.Trim();
    }

    private async Task ShowMessageAsync(string message, string title = "Информация")
    {
        var app = Application.Current;
        Brush bgBrush = new SolidColorBrush(Color.Parse("#1E1E1E"));
        Brush fgBrush = new SolidColorBrush(Colors.White);
        if (app != null)
        {
            if (app.FindResource("ThemeCardBackground") is Brush cb) bgBrush = cb;
            if (app.FindResource("ThemeTextOnCard") is Brush ct) fgBrush = ct;
        }

        var dialog = new Window
        {
            Title = title,
            Width = 350,
            Height = 150,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Background = bgBrush,
            Content = new StackPanel
            {
                Spacing = 16,
                Margin = new Thickness(20),
                VerticalAlignment = VerticalAlignment.Center,
                Children =
                {
                    new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap, Foreground = fgBrush, HorizontalAlignment = HorizontalAlignment.Center },
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