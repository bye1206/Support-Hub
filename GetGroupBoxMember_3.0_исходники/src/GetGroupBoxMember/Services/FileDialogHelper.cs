using System;
using System.IO;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Platform.Storage;

namespace GetGroupBoxMember.Services;

public static class FileDialogHelper
{
    public static string SanitizeFileName(string fileName)
    {
        if (string.IsNullOrEmpty(fileName)) return "export";
        var invalid = Path.GetInvalidFileNameChars();
        return string.Join("_", fileName.Split(invalid, StringSplitOptions.RemoveEmptyEntries));
    }

    public static async Task<string?> SelectExcelFileAsync(Window window, string title = "Выберите файл Excel")
    {
        var storageProvider = window.StorageProvider;
        
        var files = await storageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = title,
            AllowMultiple = false,
            FileTypeFilter = new[]
            {
                new FilePickerFileType("Excel")
                {
                    Patterns = new[] { "*.xlsx", "*.xls" },
                    MimeTypes = new[] { "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel" }
                }
            }
        });

        return files.Count > 0 ? files[0].Path.LocalPath : null;
    }

    public static async Task<string?> SelectSaveExcelFileAsync(Window window, string defaultFileName = "export")
    {
        var storageProvider = window.StorageProvider;
        
        var file = await storageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
        {
            Title = "Сохранить как",
            SuggestedFileName = SanitizeFileName(defaultFileName),
            FileTypeChoices = new[]
            {
                new FilePickerFileType("Excel 2007+")
                {
                    Patterns = new[] { "*.xlsx" },
                    MimeTypes = new[] { "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }
                },
                new FilePickerFileType("Excel 97-2003")
                {
                    Patterns = new[] { "*.xls" },
                    MimeTypes = new[] { "application/vnd.ms-excel" }
                }
            }
        });

        return file?.Path.LocalPath;
    }

    public static async Task<string?> SelectFileAsync(Window window, string title = "Выберите файл", params string[] extensions)
    {
        var storageProvider = window.StorageProvider;
        
        var filters = new List<FilePickerFileType>();
        
        if (extensions.Length > 0)
        {
            var patterns = extensions.Select(e => $"*{e}").ToArray();
            filters.Add(new FilePickerFileType("All Files") { Patterns = patterns });
        }
        else
        {
            filters.Add(new FilePickerFileType("All Files") { Patterns = new[] { "*.*" } });
        }

        var files = await storageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = title,
            AllowMultiple = false,
            FileTypeFilter = filters
        });

        return files.Count > 0 ? files[0].Path.LocalPath : null;
    }

    public static async Task<string?> SelectFolderAsync(Window window, string title = "Выберите папку")
    {
        var storageProvider = window.StorageProvider;
        
        var folders = await storageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = title,
            AllowMultiple = false
        });

        return folders.Count > 0 ? folders[0].Path.LocalPath : null;
    }
}
