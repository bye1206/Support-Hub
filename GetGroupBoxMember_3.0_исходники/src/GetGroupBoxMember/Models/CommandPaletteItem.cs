using System;

namespace GetGroupBoxMember.Models;

public class CommandPaletteItem
{
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public string Title { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Category { get; set; } = string.Empty;
    public string Icon { get; set; } = string.Empty;
    public CommandPaletteActionType ActionType { get; set; } = CommandPaletteActionType.Search;
    public string? SearchQuery { get; set; }
    public string? Argument { get; set; }
    public DateTime LastUsed { get; set; } = DateTime.MinValue;
    public int UseCount { get; set; } = 0;
}

public enum CommandPaletteActionType
{
    Search,
    Action,
    Navigation,
    Recent
}
