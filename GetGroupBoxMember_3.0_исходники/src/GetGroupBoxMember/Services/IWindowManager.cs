using Avalonia.Controls;

namespace GetGroupBoxMember.Services;

public interface IWindowManager
{
    void OpenWindow<T>() where T : Window, new();
    void OpenWindow(Window window);
    IReadOnlyList<Window> GetOpenWindows();
    void BringToFront(Window window);
    void CloseAllWindows();
    void RegisterOpenedWindow(Window window);
    void UnregisterWindow(Window window);
    void ShowNotification(string message);
}
