using Avalonia.Controls;
using Avalonia.Interactivity;

namespace GetGroupBoxMember.Views;

public partial class SearchDialog : Window
{
    public string SearchText { get; private set; } = "";

    public SearchDialog()
    {
        InitializeComponent();
        Opened += (s, e) => SearchTextBox.Focus();
    }

    private void Ok_Click(object? sender, RoutedEventArgs e)
    {
        SearchText = SearchTextBox.Text ?? "";
        Close();
    }

    private void Cancel_Click(object? sender, RoutedEventArgs e)
    {
        SearchText = "";
        Close();
    }
}
