namespace GetGroupBoxMember.Models;

public enum AppTheme
{
    Dark,
    Light,
    Pink,
    Green,
    Blue,
    Orange,
    Purple
}

public class ThemeColors
{
    public string Name { get; set; } = "";
    public string Background { get; set; } = "#0D1117";
    public string CardBackground { get; set; } = "#161B22";
    public string ElevatedSurface { get; set; } = "#21262D";
    public string BorderColor { get; set; } = "#30363D";
    public string TextPrimary { get; set; } = "#F0F6FC";
    public string TextSecondary { get; set; } = "#8B949E";
    public string TextMuted { get; set; } = "#8D99A7";
    public string AccentGreen { get; set; } = "#238636";
    public string AccentBlue { get; set; } = "#1F6FEB";
    public string AccentOrange { get; set; } = "#F0883E";
    public string AccentPurple { get; set; } = "#8957E5";
    public string AccentPink { get; set; } = "#E91E63";
    public string AccentRed { get; set; } = "#DA3633";
    public string ButtonBackground { get; set; } = "#21262D";
    public string ButtonHover { get; set; } = "#30363D";
    public string LinkColor { get; set; } = "#58A6FF";
}

public static class ThemeManager
{
    private static AppTheme _currentTheme = AppTheme.Dark;
    public static AppTheme CurrentTheme => _currentTheme;

    private static readonly Dictionary<AppTheme, ThemeColors> _themes = new()
    {
        [AppTheme.Dark] = new ThemeColors
        {
            Name = "Тёмная",
            Background = "#0D1117",
            CardBackground = "#161B22",
            ElevatedSurface = "#21262D",
            BorderColor = "#30363D",
            TextPrimary = "#F0F6FC",
            TextSecondary = "#8B949E",
            TextMuted = "#8D99A7",
            AccentGreen = "#238636",
            AccentBlue = "#1F6FEB",
            AccentOrange = "#F0883E",
            AccentPurple = "#8957E5",
            AccentPink = "#E91E63",
            AccentRed = "#DA3633",
            ButtonBackground = "#21262D",
            ButtonHover = "#30363D",
            LinkColor = "#58A6FF"
        },
        [AppTheme.Light] = new ThemeColors
        {
            Name = "Светлая",
            Background = "#FFFFFF",
            CardBackground = "#F6F8FA",
            ElevatedSurface = "#FFFFFF",
            BorderColor = "#D0D7DE",
            TextPrimary = "#1F2328",
            TextSecondary = "#475057",
            TextMuted = "#6B7785",
            AccentGreen = "#1A7F37",
            AccentBlue = "#0969DA",
            AccentOrange = "#9B6D00",
            AccentPurple = "#8250DF",
            AccentPink = "#D1242F",
            AccentRed = "#CF222E",
            ButtonBackground = "#F6F8FA",
            ButtonHover = "#EAECEF",
            LinkColor = "#0969DA"
        },
        [AppTheme.Pink] = new ThemeColors
        {
            Name = "Розовая (Hello Kitty)",
            Background = "#FFF0F5",
            CardBackground = "#FFE4EC",
            ElevatedSurface = "#FFF5FA",
            BorderColor = "#E8A0B0",
            TextPrimary = "#4A2535",
            TextSecondary = "#7A4055",
            TextMuted = "#9A6070",
            AccentGreen = "#2E7D32",
            AccentBlue = "#1565C0",
            AccentOrange = "#B65200",
            AccentPurple = "#7B1FA2",
            AccentPink = "#D81B60",
            AccentRed = "#C62828",
            ButtonBackground = "#FFD1DC",
            ButtonHover = "#FFBCD0",
            LinkColor = "#AD1457"
        },
        [AppTheme.Green] = new ThemeColors
        {
            Name = "Зеленая",
            Background = "#0D1117",
            CardBackground = "#0D1F12",
            ElevatedSurface = "#163318",
            BorderColor = "#1B3D1B",
            TextPrimary = "#F0F6FC",
            TextSecondary = "#8B949E",
            TextMuted = "#8D99A7",
            AccentGreen = "#2EA043",
            AccentBlue = "#1F6FEB",
            AccentOrange = "#F0883E",
            AccentPurple = "#8957E5",
            AccentPink = "#E91E63",
            AccentRed = "#DA3633",
            ButtonBackground = "#0D1F12",
            ButtonHover = "#163318",
            LinkColor = "#58A6FF"
        },
        [AppTheme.Blue] = new ThemeColors
        {
            Name = "Синяя",
            Background = "#0D1117",
            CardBackground = "#0D1F2D",
            ElevatedSurface = "#163341",
            BorderColor = "#1A3A4D",
            TextPrimary = "#F0F6FC",
            TextSecondary = "#8B949E",
            TextMuted = "#8D99A7",
            AccentGreen = "#238636",
            AccentBlue = "#388BFD",
            AccentOrange = "#F0883E",
            AccentPurple = "#8957E5",
            AccentPink = "#E91E63",
            AccentRed = "#DA3633",
            ButtonBackground = "#0D1F2D",
            ButtonHover = "#163341",
            LinkColor = "#58A6FF"
        },
        [AppTheme.Orange] = new ThemeColors
        {
            Name = "Оранжевая",
            Background = "#0D1117",
            CardBackground = "#1C1207",
            ElevatedSurface = "#2D1E0A",
            BorderColor = "#3D2A15",
            TextPrimary = "#F0F6FC",
            TextSecondary = "#8B949E",
            TextMuted = "#8D99A7",
            AccentGreen = "#238636",
            AccentBlue = "#1F6FEB",
            AccentOrange = "#DB6D28",
            AccentPurple = "#8957E5",
            AccentPink = "#E91E63",
            AccentRed = "#DA3633",
            ButtonBackground = "#1C1207",
            ButtonHover = "#2D1E0A",
            LinkColor = "#58A6FF"
        },
        [AppTheme.Purple] = new ThemeColors
        {
            Name = "Фиолетовая",
            Background = "#0D1117",
            CardBackground = "#1A1625",
            ElevatedSurface = "#251F35",
            BorderColor = "#2A2540",
            TextPrimary = "#F0F6FC",
            TextSecondary = "#8B949E",
            TextMuted = "#8D99A7",
            AccentGreen = "#238636",
            AccentBlue = "#1F6FEB",
            AccentOrange = "#F0883E",
            AccentPurple = "#8957E5",
            AccentPink = "#E91E63",
            AccentRed = "#DA3633",
            ButtonBackground = "#1A1625",
            ButtonHover = "#251F35",
            LinkColor = "#58A6FF"
        }
    };

    public static ThemeColors GetColors(AppTheme theme) => _themes[theme];
    public static ThemeColors CurrentColors => GetColors(_currentTheme);

    public static void SetTheme(AppTheme theme)
    {
        _currentTheme = theme;
    }

    public static string GetCurrentThemeName() => _currentTheme.ToString();

    public static IEnumerable<(AppTheme Theme, string Name)> GetAllThemes()
    {
        foreach (var theme in _themes)
        {
            yield return (theme.Key, theme.Value.Name);
        }
    }
}
