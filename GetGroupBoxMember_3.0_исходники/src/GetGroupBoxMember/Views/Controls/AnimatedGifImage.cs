using System;
using System.IO;
using System.Threading;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using Avalonia.Threading;
using SkiaSharp;

namespace GetGroupBoxMember.Views.Controls;

public class AnimatedGifImage : Image
{
    public static readonly StyledProperty<string?> SourceProperty =
        AvaloniaProperty.Register<AnimatedGifImage, string?>(nameof(Source), string.Empty);

    public string? Source
    {
        get => GetValue(SourceProperty);
        set => SetValue(SourceProperty, value);
    }

    public static readonly StyledProperty<bool> IsIndeterminateProperty =
        AvaloniaProperty.Register<AnimatedGifImage, bool>(nameof(IsIndeterminate), true);

    public bool IsIndeterminate
    {
        get => GetValue(IsIndeterminateProperty);
        set => SetValue(IsIndeterminateProperty, value);
    }

    public static readonly StyledProperty<bool> IsLoadingProperty =
        AvaloniaProperty.Register<AnimatedGifImage, bool>(nameof(IsLoading), false);

    public bool IsLoading
    {
        get => GetValue(IsLoadingProperty);
        set => SetValue(IsLoadingProperty, value);
    }

    private SKBitmap?[]? _frames;
    private int[]? _frameDurations;
    private int _frameCount;
    private int _currentFrame;
    private CancellationTokenSource? _animationCts;

    static AnimatedGifImage()
    {
        AffectsMeasure<AnimatedGifImage>(SourceProperty);
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        if (change.Property == IsVisibleProperty && change.NewValue is true)
        {
            if (!string.IsNullOrEmpty(Source))
                LoadGif();
        }
    }

    private void LoadGif()
    {
        StopAnimation();

        if (string.IsNullOrEmpty(Source))
        {
            Source = null;
            return;
        }

        try
        {
            var uri = new Uri(Source, UriKind.RelativeOrAbsolute);
            using var stream = AssetLoader.Open(uri);
            using var memoryStream = new MemoryStream();
            stream.CopyTo(memoryStream);
            memoryStream.Position = 0;

            var (frames, durations, count) = LoadAllFrames(memoryStream);
            if (frames != null && count > 0)
            {
                _frames = frames;
                _frameDurations = durations;
                _frameCount = count;
                _currentFrame = 0;
                UpdateFrame();
                StartAnimation();
            }
        }
        catch
        {
            Source = null;
        }
    }

    private (SKBitmap?[], int[]?, int) LoadAllFrames(Stream stream)
    {
        try
        {
            using var codec = SKCodec.Create(stream);
            if (codec == null) return (null, null, 0);

            var frameCount = codec.FrameCount;
            var info = codec.Info;

            var options = new SKImageInfo(info.Width, info.Height, SKColorType.Bgra8888, SKAlphaType.Premul);
            var frames = new SKBitmap[frameCount];
            var durations = new int[frameCount];

            stream.Position = 0;
            using var codec2 = SKCodec.Create(stream);

            for (int i = 0; i < frameCount; i++)
            {
                var frameBitmap = new SKBitmap(options);
                frameBitmap.Erase(SKColors.Transparent);

                var frameOptions = new SKCodecOptions(i);
                codec2?.GetPixels(options, frameBitmap.GetPixels(out _), frameOptions);
                frames[i] = frameBitmap;
                durations[i] = codec2?.FrameInfo[i].Duration > 0 ? codec2.FrameInfo[i].Duration : 100;
            }

            return (frames, durations, frameCount);
        }
        catch
        {
            return (null, null, 0);
        }
    }

    private void UpdateFrame()
    {
        if (_frames == null || _currentFrame >= _frameCount) return;

        var skBitmap = _frames[_currentFrame];
        if (skBitmap == null) return;

        try
        {
            var pixelData = skBitmap.GetPixels(out _);
            var pixelSize = new PixelSize(skBitmap.Info.Width, skBitmap.Info.Height);
            var dpi = new Vector(96, 96);
            var bitmap = new Bitmap(
                PixelFormat.Bgra8888,
                AlphaFormat.Premul,
                pixelData,
                pixelSize,
                dpi,
                skBitmap.RowBytes);
            base.Source = bitmap;
        }
        catch
        {
            Source = null;
        }
    }

    private void StartAnimation()
    {
        if (_animationCts != null || _frameCount <= 1) return;

        _animationCts = new CancellationTokenSource();
        var token = _animationCts.Token;

        global::System.Threading.Tasks.Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                var delay = _frameDurations != null && _currentFrame < _frameCount
                    ? _frameDurations[_currentFrame]
                    : 100;

                try
                {
                    await global::System.Threading.Tasks.Task.Delay(delay, token);
                }
                catch
                {
                    break;
                }

                _currentFrame = (_currentFrame + 1) % _frameCount;

                global::Avalonia.Threading.Dispatcher.UIThread.Post(UpdateFrame);
            }
        }, token);
    }

    private void StopAnimation()
    {
        _animationCts?.Cancel();
        _animationCts?.Dispose();
        _animationCts = null;

        if (_frames != null)
        {
            foreach (var frame in _frames)
            {
                frame?.Dispose();
            }
            _frames = null;
        }
        _frameDurations = null;
        _frameCount = 0;
        _currentFrame = 0;
    }

    protected override void OnDetachedFromVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnDetachedFromVisualTree(e);
        StopAnimation();
    }

    protected override void OnAttachedToVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnAttachedToVisualTree(e);
        if (!string.IsNullOrEmpty(Source))
        {
            LoadGif();
        }
    }
}
