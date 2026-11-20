using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using GetGroupBoxMember.ViewModels;
using System.Diagnostics;

namespace GetGroupBoxMember.Views;

public partial class AboutWindow : WindowBase
{
    public AboutWindow()
    {
        InitializeComponent();
        DataContext = new AboutWindowViewModel();
    }

    private void Close_Click(object? sender, RoutedEventArgs e)
    {
        Close();
    }

    private void Telegram_Click(object? sender, PointerPressedEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo { FileName = "https://t.me/bond_dmitriy", UseShellExecute = true });
        }
        catch { }
    }
}
