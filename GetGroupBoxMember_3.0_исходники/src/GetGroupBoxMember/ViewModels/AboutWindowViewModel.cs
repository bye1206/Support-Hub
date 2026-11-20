using System;
using CommunityToolkit.Mvvm.ComponentModel;

namespace GetGroupBoxMember.ViewModels;

public partial class AboutWindowViewModel : ObservableObject
{
    public string Version { get; }

    public AboutWindowViewModel()
    {
        var version = System.Reflection.Assembly.GetExecutingAssembly().GetName().Version;
        Version = $"{version?.Major}.{version?.Minor}.{version?.Build}";
    }
}
