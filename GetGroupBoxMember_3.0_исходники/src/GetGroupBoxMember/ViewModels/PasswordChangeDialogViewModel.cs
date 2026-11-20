using System;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace GetGroupBoxMember.ViewModels;

public partial class PasswordChangeDialogViewModel : ViewModelBase
{
    [ObservableProperty] private string _password = string.Empty;
    [ObservableProperty] private string _confirmPassword = string.Empty;
    [ObservableProperty] private bool _isPasswordVisible;
    [ObservableProperty] private bool _isConfirmVisible;
    [ObservableProperty] private bool _hasError;
    [ObservableProperty] private string _errorMessage = string.Empty;
    [ObservableProperty] private string _targetDisplayName = string.Empty;
    [ObservableProperty] private string _targetLogin = string.Empty;

    public bool HasMinLength => Password.Length >= 8 && Password.Length <= 128;
    public bool HasUpper => !string.IsNullOrEmpty(Password) && Password.AsSpan().IndexOfAny("ABCDEFGHIJKLMNOPQRSTUVWXYZ".AsSpan()) >= 0;
    public bool HasLower => !string.IsNullOrEmpty(Password) && Password.AsSpan().IndexOfAny("abcdefghijklmnopqrstuvwxyz".AsSpan()) >= 0;
    public bool HasDigit => !string.IsNullOrEmpty(Password) && Password.AsSpan().IndexOfAny("0123456789".AsSpan()) >= 0;
    public bool HasSpecial => !string.IsNullOrEmpty(Password) && Password.AsSpan().IndexOfAny("!@#$%^&*()_+-=[]{}|;:,.<>?/~`".AsSpan()) >= 0;
    public bool PasswordsMatch => !string.IsNullOrEmpty(Password) && Password == ConfirmPassword;
    public bool IsValid => HasMinLength && HasUpper && HasLower && HasDigit && HasSpecial && PasswordsMatch;

    public int PasswordStrength => CalculateStrength();
    public string StrengthText => PasswordStrength switch
    {
        >= 80 => "Высокая",
        >= 50 => "Средняя",
        > 0 => "Низкая",
        _ => ""
    };

    public string? ResultPassword { get; private set; }
    public bool? DialogResult { get; private set; }

    partial void OnPasswordChanged(string value) => UpdateChecks();
    partial void OnConfirmPasswordChanged(string value) => UpdateChecks();

    private void UpdateChecks()
    {
        OnPropertyChanged(nameof(HasMinLength));
        OnPropertyChanged(nameof(HasUpper));
        OnPropertyChanged(nameof(HasLower));
        OnPropertyChanged(nameof(HasDigit));
        OnPropertyChanged(nameof(HasSpecial));
        OnPropertyChanged(nameof(PasswordsMatch));
        OnPropertyChanged(nameof(IsValid));
        OnPropertyChanged(nameof(PasswordStrength));
        OnPropertyChanged(nameof(StrengthText));
    }

    private int CalculateStrength()
    {
        if (string.IsNullOrEmpty(Password)) return 0;
        int score = 0;
        if (Password.Length >= 8) score += 20;
        if (Password.Length >= 12) score += 15;
        if (HasUpper) score += 15;
        if (HasLower) score += 15;
        if (HasDigit) score += 15;
        if (HasSpecial) score += 20;
        return Math.Min(score, 100);
    }

    [RelayCommand]
    private void Confirm()
    {
        ResultPassword = Password;
        DialogResult = true;
    }

    [RelayCommand]
    private void Cancel()
    {
        ResultPassword = null;
        DialogResult = false;
    }
}
