using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;

namespace GetGroupBoxMember.Behaviors;

public static class FocusPreservation
{
    private static readonly AttachedProperty<bool> IsEnabledProperty =
        AvaloniaProperty.RegisterAttached<Control, bool>("IsEnabled", typeof(FocusPreservation));

    private static readonly AttachedProperty<bool> IsRestoringProperty =
        AvaloniaProperty.RegisterAttached<Control, bool>("IsRestoring", typeof(FocusPreservation));

    private static readonly AttachedProperty<bool> WasFocusedProperty =
        AvaloniaProperty.RegisterAttached<Control, bool>("WasFocused", typeof(FocusPreservation));

    private static DispatcherTimer? _restoreTimer;

    static FocusPreservation()
    {
        IsEnabledProperty.Changed.AddClassHandler<Control>(OnIsEnabledChanged);
    }

    public static bool GetIsEnabled(Control element) => element.GetValue(IsEnabledProperty);
    public static void SetIsEnabled(Control element, bool value) => element.SetValue(IsEnabledProperty, value);

    private static bool GetIsRestoring(Control element) => element.GetValue(IsRestoringProperty);
    private static void SetIsRestoring(Control element, bool value) => element.SetValue(IsRestoringProperty, value);

    private static bool GetWasFocused(Control element) => element.GetValue(WasFocusedProperty);
    private static void SetWasFocused(Control element, bool value) => element.SetValue(WasFocusedProperty, value);

    private static void OnIsEnabledChanged(Control control, AvaloniaPropertyChangedEventArgs e)
    {
        if (control is not TextBox textBox)
            return;

        textBox.LostFocus -= TextBox_LostFocus;
        textBox.GotFocus -= TextBox_GotFocus;
        textBox.KeyDown -= TextBox_KeyDown;

        if (e.NewValue is true)
        {
            textBox.LostFocus += TextBox_LostFocus;
            textBox.GotFocus += TextBox_GotFocus;
            textBox.KeyDown += TextBox_KeyDown;
        }
    }

    private static void TextBox_KeyDown(object? sender, KeyEventArgs e)
    {
        if (sender is not TextBox textBox)
            return;

        if (e.Key == Key.LeftCtrl || e.Key == Key.RightCtrl ||
            e.Key == Key.LeftAlt || e.Key == Key.RightAlt)
        {
            SetWasFocused(textBox, true);
        }
    }

    private static void TextBox_GotFocus(object? sender, RoutedEventArgs e)
    {
        if (sender is not TextBox textBox)
            return;

        _restoreTimer?.Stop();
        _restoreTimer = null;
        SetIsRestoring(textBox, false);
        SetWasFocused(textBox, true);
    }

    private static void TextBox_LostFocus(object? sender, RoutedEventArgs e)
    {
        if (sender is not TextBox textBox)
            return;

        if (GetIsRestoring(textBox))
            return;

        var focusManager = TopLevel.GetTopLevel(textBox)?.FocusManager;
        var newFocus = focusManager?.GetFocusedElement() as Control;
        if (newFocus == null)
            return;

        if (IsButton(newFocus))
            return;

        var newFocusTopLevel = TopLevel.GetTopLevel(newFocus);
        var textBoxTopLevel = TopLevel.GetTopLevel(textBox);
        if (newFocusTopLevel != textBoxTopLevel)
            return;

        bool shouldRestore = IsMenuRelated(newFocus) || GetWasFocused(textBox);

        if (shouldRestore)
        {
            SetIsRestoring(textBox, true);
            SetWasFocused(textBox, false);
            _restoreTimer?.Stop();

            _restoreTimer = new DispatcherTimer
            {
                Interval = TimeSpan.FromMilliseconds(80)
            };

            _restoreTimer.Tick += (s, args) =>
            {
                _restoreTimer?.Stop();
                _restoreTimer = null;

                if (!textBox.IsFocused)
                {
                    textBox.Focus();
                    if (textBox.Text != null && textBox.Text.Length > 0)
                        textBox.CaretIndex = textBox.Text.Length;
                }

                SetIsRestoring(textBox, false);
            };

            _restoreTimer.Start();
        }
    }

    private static bool IsButton(Control control)
    {
        var current = control;
        while (current != null)
        {
            if (current is Button)
                return true;
            current = current.Parent as Control;
        }
        return false;
    }

    private static bool IsMenuRelated(Control control)
    {
        var current = control;
        while (current != null)
        {
            if (current is MenuItem || current is Menu)
                return true;
            current = current.Parent as Control;
        }
        return false;
    }
}
