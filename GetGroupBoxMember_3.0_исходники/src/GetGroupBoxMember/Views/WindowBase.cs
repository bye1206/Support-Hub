using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.Platform;
using Avalonia.Styling;
using Avalonia.Threading;
using GetGroupBoxMember.Models;
using GetGroupBoxMember.Services;

namespace GetGroupBoxMember.Views;

public partial class WindowBase : Window
{
    protected readonly ThemeService _themeService;
    protected readonly AppSettings _settings;
    protected bool _isInitialized = false;

    private DispatcherTimer? _saveDebounceTimer;

    public string WindowId => GetType().Name;

    protected virtual bool CloseOnCtrlW => true;

    public WindowBase()
    {
        _themeService = ThemeService.Instance;
        _settings = AppSettings.Load();

        Opened += WindowBase_Opened;
        PropertyChanged += WindowBase_PropertyChanged;
        _themeService.ThemeChanged += OnThemeChanged;
    }

    private void OnThemeChanged(object? sender, (AppTheme Theme, ThemeColors Colors) args)
    {
        _themeService.ApplyThemeResources(args.Theme);
    }

    private void WindowBase_Opened(object? sender, EventArgs e)
    {
        if (_isInitialized) return;
        _isInitialized = true;

        var savedSize = _settings.WindowSizes.GetValueOrDefault(WindowId);
        if (savedSize != null)
        {
            double scale = RenderScaling;

            Width = savedSize.Width / scale;
            Height = savedSize.Height / scale;

            if (savedSize.Left.HasValue && savedSize.Top.HasValue)
            {
                WindowStartupLocation = WindowStartupLocation.Manual;
                int x = (int)(savedSize.Left.Value * scale);
                int y = (int)(savedSize.Top.Value * scale);
                Position = new PixelPoint(x, y);
            }
        }

        _themeService.ApplyThemeResources();
    }

    protected override void OnPointerPressed(PointerPressedEventArgs e)
    {
        var props = e.GetCurrentPoint(this).Properties;
        if (e.KeyModifiers == KeyModifiers.Alt && props.PointerUpdateKind == PointerUpdateKind.LeftButtonPressed)
        {
            e.Handled = true;
            WindowManager.Instance.CloseAllWindows();
            return;
        }
        base.OnPointerPressed(e);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (CloseOnCtrlW && e.Key == Key.W && (e.KeyModifiers & KeyModifiers.Control) != 0)
        {
            e.Handled = true;
            Close();
            return;
        }
        base.OnKeyDown(e);
    }

    protected override void OnClosing(WindowClosingEventArgs e)
    {
        _saveDebounceTimer?.Stop();
        SaveWindowSize();
        _themeService.ThemeChanged -= OnThemeChanged;
        base.OnClosing(e);
    }

    private void WindowBase_PropertyChanged(object? sender, AvaloniaPropertyChangedEventArgs e)
    {
        if (!_isInitialized) return;
        if (WindowState == WindowState.Minimized) return;

        if (e.Property.Name == "Width" || e.Property.Name == "Height" ||
            e.Property.Name == "Position")
        {
            ScheduleSaveWindowSize();
        }
    }

    private void ScheduleSaveWindowSize()
    {
        _saveDebounceTimer?.Stop();
        _saveDebounceTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(500) };
        _saveDebounceTimer.Tick += (s, e) =>
        {
            _saveDebounceTimer?.Stop();
            SaveWindowSize();
        };
        _saveDebounceTimer.Start();
    }

    protected void SaveWindowSize()
    {
        if (!_isInitialized) return;
        if (WindowState == WindowState.Minimized) return;

        double scale = RenderScaling;

        double deviceWidth = Width * scale;
        double deviceHeight = Height * scale;
        double? left = scale > 0 ? Position.X / scale : (double?)null;
        double? top = scale > 0 ? Position.Y / scale : (double?)null;

        _settings.WindowSizes[WindowId] = new WindowSize(deviceWidth, deviceHeight, left, top);
        _settings.Save();
    }

    protected virtual void ApplyThemeColors()
    {
    }
}
