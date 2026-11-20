using System;
using System.Collections.Generic;
using System.Linq;

namespace GetGroupBoxMember.Models;

public class TrackingRecord
{
    public DateTime Timestamp { get; set; }
    public string EventId { get; set; } = "";
    public string Sender { get; set; } = "";
    public string Recipients { get; set; } = "";
    public string MessageSubject { get; set; } = "";
    public long TotalBytes { get; set; }
    public string Source { get; set; } = "";
    public string Server { get; set; } = "";
    public string SizeMB { get; set; } = "";
    public string MessageId { get; set; } = "";

    public string EventIdLocalized => EventIdHelper.GetLocalizedName(EventId);
    public string TimestampStr => Timestamp.ToString("yyyy-MM-dd HH:mm:ss");
    public string RecipientDisplay
    {
        get
        {
            if (string.IsNullOrEmpty(Recipients)) return "—";
            var parts = Recipients.Split(new[] { "; ", ";" }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0) return "—";
            if (parts.Length == 1) return parts[0];
            return parts[0] + $" (+{parts.Length - 1})";
        }
    }
    public string RecipientsFull
    {
        get
        {
            if (string.IsNullOrEmpty(Recipients)) return "—";
            var parts = Recipients.Split(new[] { "; ", ";" }, StringSplitOptions.RemoveEmptyEntries);
            return string.Join(", ", parts);
        }
    }
}

public class MessageGroup
{
    public string MessageId { get; set; } = "";
    public string Subject { get; set; } = "";
    public string Sender { get; set; } = "";
    public string Recipients { get; set; } = "";
    public long TotalBytes { get; set; }
    public string SizeMB { get; set; } = "";
    public List<TrackingRecord> Records { get; set; } = new();
    public List<string> UniqueEvents { get; set; } = new();
    public int ServerCount { get; set; }
    public DateTime FirstSeen { get; set; }
    public DateTime LastSeen { get; set; }
    public bool IsExpanded { get; set; }

    public List<string> UniqueRecipients => Records
        .SelectMany(r => r.Recipients.Split(new[] { "; ", ";" }, StringSplitOptions.RemoveEmptyEntries))
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .ToList();

    public string RecipientsSummary
    {
        get
        {
            var recs = UniqueRecipients;
            if (recs.Count == 0) return "—";
            if (recs.Count == 1) return recs[0];
            return $"{recs[0]} (+{recs.Count - 1} ещё)";
        }
    }

    public string EventsSummary => string.Join(" → ", UniqueEvents.Select(e => EventIdHelper.GetLocalizedName(e)));
    public string TimeRange => $"{FirstSeen:HH:mm:ss} → {LastSeen:HH:mm:ss}";
    public int RecordCount => Records.Count;
    public string DurationStr
    {
        get
        {
            var dur = LastSeen - FirstSeen;
            if (dur.TotalSeconds < 60) return $"{(int)dur.TotalSeconds} сек";
            if (dur.TotalMinutes < 60) return $"{(int)dur.TotalMinutes} мин";
            return $"{(int)dur.TotalHours} ч {((int)dur.TotalMinutes) % 60} мин";
        }
    }
}

public static class EventIdHelper
{
    private static readonly Dictionary<string, string> Localizations = new(StringComparer.OrdinalIgnoreCase)
    {
        { "AGENTINFO", "Агент записал данные" },
        { "BADMAIL", "Поврежденное письмо" },
        { "CLIENTSUBMISSION", "Отправка клиентом" },
        { "DEFER", "Отложено" },
        { "DELIVER", "Доставлено" },
        { "DELIVERFAIL", "Ошибка доставки" },
        { "DROP", "Отброшено" },
        { "DSN", "Отбойник (NDR)" },
        { "DUPLICATEDELIVER", "Доставлен дубликат" },
        { "DUPLICATEEXPAND", "Дубликат в группе" },
        { "DUPLICATEREDIRECT", "Дубликат перенаправления" },
        { "EXPAND", "Раскрытие группы" },
        { "FAIL", "Ошибка" },
        { "HADISCARD", "Резервная копия удалена" },
        { "HARECEIVE", "Резервная копия принята" },
        { "HAREDIRECT", "Резервная копия создана" },
        { "HAREDIRECTFAIL", "Резервная копия не создана" },
        { "INITMESSAGECREATED", "На модерацию" },
        { "LOAD", "Загружено" },
        { "MODERATIONEXPIRE", "Модерация просрочена" },
        { "MODERATORAPPROVE", "Модератор одобрил" },
        { "MODERATORREJECT", "Модератор отклонил" },
        { "MODERATORSALLNDR", "Все модераторы недоступны" },
        { "NOTIFYMAPI", "Обнаружено в исходящих" },
        { "NOTIFYSHADOW", "Требуется резервная копия" },
        { "POISONMESSAGE", "Карантин" },
        { "PROCESS", "Обработано" },
        { "PROCESSMEETINGMESSAGE", "Приглашение обработано" },
        { "RECEIVE", "Получено" },
        { "REDIRECT", "Перенаправлено" },
        { "RESOLVE", "Получатель найден" },
        { "RESUBMIT", "Повторная отправка" },
        { "RESUBMITDEFER", "Повтор отложен" },
        { "RESUBMITFAIL", "Повтор не удался" },
        { "SEND", "Отправлено" },
        { "SENDEXTERNAL", "Отправлено наружу" },
        { "SUBMIT", "Передано" },
        { "SUBMITDEFER", "Передача отложена" },
        { "SUBMITFAIL", "Передача не удалась" },
        { "SUPPRESSED", "Подавлено" },
        { "THROTTLE", "Ограничено" },
        { "TRANSFER", "Размножено" },
    };

    public static string GetLocalizedName(string? eventId)
    {
        if (string.IsNullOrEmpty(eventId)) return "";
        return Localizations.TryGetValue(eventId, out var name) ? name : eventId;
    }

    public static string GetDisplayName(string? eventId)
    {
        if (string.IsNullOrEmpty(eventId)) return "";
        var localized = GetLocalizedName(eventId);
        return localized == eventId ? eventId : $"{localized} ({eventId})";
    }
}
