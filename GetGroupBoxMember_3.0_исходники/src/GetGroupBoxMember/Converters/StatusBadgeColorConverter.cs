using Avalonia;
using Avalonia.Data.Converters;
using Avalonia.Media;
using System;
using System.Globalization;

namespace GetGroupBoxMember.Converters;

public class StatusBadgeColorConverter : IValueConverter
{
    private static Color GetResourceColor(string key, Color fallback)
    {
        if (Application.Current?.Resources.TryGetValue(key, out var value) == true && value is Color c)
            return c;
        return fallback;
    }

    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is string status)
        {
            var lower = status.ToLowerInvariant();

            if (lower.Contains("присутствует"))
                return new SolidColorBrush(GetResourceColor("AccentOrange", Color.Parse("#F0883E")));
            if (lower.Contains("отсутствует"))
                return new SolidColorBrush(GetResourceColor("AccentBlue", Color.Parse("#1F6FEB")));
            if (lower.Contains("disable") || lower.Contains("блок"))
                return new SolidColorBrush(GetResourceColor("AccentRed", Color.Parse("#DA3633")));
            if (lower.Contains("normal") || lower.Contains("работает"))
                return new SolidColorBrush(GetResourceColor("AccentGreen", Color.Parse("#238636")));
            if (lower.Contains("hr"))
                return new SolidColorBrush(GetResourceColor("AccentPurple", Color.Parse("#8957E5")));
            if (lower.Contains("сумд"))
                return new SolidColorBrush(GetResourceColor("AccentBlue", Color.Parse("#1F6FEB")));
            if (lower.Contains("пароль") && lower.Contains("истёк"))
                return new SolidColorBrush(GetResourceColor("AccentRed", Color.Parse("#DA3633")));
            if (lower.Contains("пароль") && lower.Contains("требует"))
                return new SolidColorBrush(GetResourceColor("AccentOrange", Color.Parse("#F0883E")));
        }
        return new SolidColorBrush(GetResourceColor("ThemeTextSecondary", Color.Parse("#8B949E")));
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        throw new NotImplementedException();
    }
}

public class PasswordBadgeColorConverter : IValueConverter
{
    private static Color GetResourceColor(string key, Color fallback)
    {
        if (Application.Current?.Resources.TryGetValue(key, out var value) == true && value is Color c)
            return c;
        return fallback;
    }

    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is string status)
        {
            var lower = status.ToLowerInvariant();

            var match = System.Text.RegularExpressions.Regex.Match(status, @"(\d+)\s*(?:дн|дней|дня)");
            if (match.Success && int.TryParse(match.Groups[1].Value, out int days))
            {
                if (days <= 0)
                    return new SolidColorBrush(GetResourceColor("AccentRed", Color.Parse("#DA3633")));
                if (days <= 7)
                    return new SolidColorBrush(GetResourceColor("AccentOrange", Color.Parse("#F0883E")));
                return new SolidColorBrush(GetResourceColor("AccentGreen", Color.Parse("#238636")));
            }

            if (lower.Contains("просрочен") || lower.Contains("требует смены"))
                return new SolidColorBrush(GetResourceColor("AccentRed", Color.Parse("#DA3633")));
            if (lower.Contains("не установлен"))
                return new SolidColorBrush(GetResourceColor("AccentOrange", Color.Parse("#F0883E")));
        }
        return new SolidColorBrush(GetResourceColor("AccentGreen", Color.Parse("#238636")));
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        throw new NotImplementedException();
    }
}
