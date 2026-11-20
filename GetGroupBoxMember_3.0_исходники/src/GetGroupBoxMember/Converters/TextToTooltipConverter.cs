using Avalonia.Data.Converters;
using System;
using System.Globalization;

namespace GetGroupBoxMember.Converters;

public class TextToTooltipConverter : IValueConverter
{
    public static readonly TextToTooltipConverter Instance = new();

    private const int MaxVisibleChars = 40;

    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is not string text)
            return null;

        if (string.IsNullOrEmpty(text))
            return null;

        return text.Length > MaxVisibleChars ? text : null;
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) => null;
}
