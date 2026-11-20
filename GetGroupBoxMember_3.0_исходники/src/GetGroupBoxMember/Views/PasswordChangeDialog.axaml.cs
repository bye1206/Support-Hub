using System.ComponentModel;
using Avalonia.Controls;
using GetGroupBoxMember.ViewModels;

namespace GetGroupBoxMember.Views;

public partial class PasswordChangeDialog : Window
{
    public PasswordChangeDialog()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
        Opened += (_, _) => PasswordBox?.Focus();
    }

    private void OnDataContextChanged(object? sender, System.EventArgs e)
    {
        if (DataContext is PasswordChangeDialogViewModel vm)
        {
            vm.PropertyChanged += OnVmPropertyChanged;
        }
    }

    private void OnVmPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(PasswordChangeDialogViewModel.DialogResult)
            && sender is PasswordChangeDialogViewModel vm
            && vm.DialogResult.HasValue)
        {
            Close(vm.ResultPassword);
        }
    }
}
