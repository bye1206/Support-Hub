using Avalonia;
using Avalonia.Media;
using GetGroupBoxMember.Services;

namespace GetGroupBoxMember.Views;

public class VdiFolderItem
{
    public string Path { get; set; } = "";
    public string Status { get; set; } = "";
    public string SizeText { get; set; } = "";
    public string Icon { get; set; } = "✗";
    public bool Exists { get; set; }
}

public class VdiFoldersWindowViewModel
{
    public SolidColorBrush BackgroundColor { get; set; }
    public SolidColorBrush SurfaceColor { get; set; }
    public SolidColorBrush TextPrimaryColor { get; set; }
    public SolidColorBrush TextSecondaryColor { get; set; }
    public SolidColorBrush BorderColor { get; set; }
    public SolidColorBrush PrimaryColor { get; set; }
    public List<VdiFolderItem> FolderItems { get; set; } = new();

    public VdiFoldersWindowViewModel()
    {
        RefreshColors();
    }

    public void RefreshColors()
    {
        var colors = ThemeService.Instance.CurrentColors;
        BackgroundColor = new SolidColorBrush(Color.Parse(colors.Background));
        SurfaceColor = new SolidColorBrush(Color.Parse(colors.CardBackground));
        TextPrimaryColor = new SolidColorBrush(Color.Parse(colors.TextPrimary));
        TextSecondaryColor = new SolidColorBrush(Color.Parse(colors.TextSecondary));
        BorderColor = new SolidColorBrush(Color.Parse(colors.BorderColor));
        PrimaryColor = new SolidColorBrush(Color.Parse(colors.AccentBlue));
    }
}
