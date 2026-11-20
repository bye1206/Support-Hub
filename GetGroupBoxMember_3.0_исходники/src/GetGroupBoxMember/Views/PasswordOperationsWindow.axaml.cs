using Avalonia.Controls;
using GetGroupBoxMember.ViewModels;

namespace GetGroupBoxMember.Views;

public partial class PasswordOperationsWindow : WindowBase
{
    public PasswordOperationsWindow()
    {
        InitializeComponent();
    }

    public PasswordOperationsWindow(MainWindowViewModel viewModel) : this()
    {
        DataContext = viewModel;
    }
}
