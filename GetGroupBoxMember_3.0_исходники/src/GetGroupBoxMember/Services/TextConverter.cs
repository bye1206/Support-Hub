using System;
using System.Text;

namespace GetGroupBoxMember.Services;

public static class TextConverter
{
    private static readonly Dictionary<char, char> _latinicToCyrillic;
    private static readonly Dictionary<char, char> _cyrillicToLatin;
    private static readonly Dictionary<string, string> _translitMap;

    static TextConverter()
    {
        _latinicToCyrillic = new Dictionary<char, char>
        {
            ['~'] = 'Ё', ['@'] = '"', ['#'] = '№', ['$'] = ';', ['^'] = ':', ['&'] = '?',
            ['Q'] = 'Й', ['W'] = 'Ц', ['E'] = 'У', ['R'] = 'К', ['T'] = 'Е', ['Y'] = 'Н',
            ['U'] = 'Г', ['I'] = 'Ш', ['O'] = 'Щ', ['P'] = 'З', ['{'] = 'Х', ['}'] = 'Ъ',
            ['A'] = 'Ф', ['S'] = 'Ы', ['D'] = 'В', ['F'] = 'А', ['G'] = 'П', ['H'] = 'Р',
            ['J'] = 'О', ['K'] = 'Л', ['L'] = 'Д', [':'] = 'Ж', ['"'] = 'Э', ['|'] = '/',
            ['Z'] = 'Я', ['X'] = 'Ч', ['C'] = 'С', ['V'] = 'М', ['B'] = 'И', ['N'] = 'Т',
            ['M'] = 'Ь', ['<'] = 'Б', ['>'] = 'Ю', ['?'] = ',',
            ['`'] = 'ё', ['q'] = 'й', ['w'] = 'ц', ['e'] = 'у', ['r'] = 'к', ['t'] = 'е',
            ['y'] = 'н', ['u'] = 'г', ['i'] = 'ш', ['o'] = 'щ', ['p'] = 'з', ['['] = 'х',
            [']'] = 'ъ', ['a'] = 'ф', ['s'] = 'ы', ['d'] = 'в', ['f'] = 'а', ['g'] = 'п',
            ['h'] = 'р', ['j'] = 'о', ['k'] = 'л', ['l'] = 'д', [';'] = 'ж', ['\''] = 'э',
            ['z'] = 'я', ['x'] = 'ч', ['c'] = 'с', ['v'] = 'м', ['b'] = 'и', ['n'] = 'т',
            ['m'] = 'ь', [','] = 'б', ['.'] = 'ю', ['/'] = '.'
        };

        _cyrillicToLatin = _latinicToCyrillic.ToDictionary(kvp => kvp.Value, kvp => kvp.Key);

        _translitMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["а"] = "a", ["б"] = "b", ["в"] = "v", ["г"] = "g", ["д"] = "d", ["е"] = "e",
            ["ё"] = "e", ["ж"] = "zh", ["з"] = "z", ["и"] = "i", ["й"] = "y", ["к"] = "k",
            ["л"] = "l", ["м"] = "m", ["н"] = "n", ["о"] = "o", ["п"] = "p", ["р"] = "r",
            ["с"] = "s", ["т"] = "t", ["у"] = "u", ["ф"] = "f", ["х"] = "kh", ["ц"] = "tc",
            ["ч"] = "ch", ["ш"] = "sh", ["щ"] = "shch", ["ъ"] = "", ["ы"] = "y", ["ь"] = "",
            ["э"] = "e", ["ю"] = "yu", ["я"] = "ya"
        };
    }

    public static string GetCyrillicText(string text)
    {
        if (string.IsNullOrEmpty(text))
            return text;

        var sb = new StringBuilder(text.Length);
        foreach (char c in text)
        {
            sb.Append(_latinicToCyrillic.TryGetValue(c, out var cyrillic) ? cyrillic : c);
        }
        return sb.ToString();
    }

    public static string GetLatinicText(string text)
    {
        if (string.IsNullOrEmpty(text))
            return text;

        var sb = new StringBuilder(text.Length);
        foreach (char c in text)
        {
            sb.Append(_cyrillicToLatin.TryGetValue(c, out var latin) ? latin : c);
        }
        return sb.ToString();
    }

    public static string Translite(string text)
    {
        if (string.IsNullOrEmpty(text))
            return text;

        var sb = new StringBuilder(text.Length * 2);
        foreach (char c in text)
        {
            var key = c.ToString();
            sb.Append(_translitMap.TryGetValue(key, out var translit) ? translit : key);
        }
        return sb.ToString();
    }
}
