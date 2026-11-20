using System.Data;
using System.Text.RegularExpressions;

namespace GetGroupBoxMember.Services;

public static class Helpers
{
    private static readonly Regex EmailInBracketsRegex = new(
        @"[<(\[]\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\s*[)\]>]",
        RegexOptions.Compiled);

    private static readonly Regex BareEmailRegex = new(
        @"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
        RegexOptions.Compiled);

    /// <summary>
    /// Extracts an email address from strings like:
    /// "Name &lt;email@domain&gt;", "Name (email@domain)", "Name [email@domain]", or bare "email@domain"
    /// </summary>
    public static string? TryExtractEmail(string input)
    {
        if (string.IsNullOrWhiteSpace(input))
            return null;

        input = input.Trim();

        var match = EmailInBracketsRegex.Match(input);
        if (match.Success)
            return match.Groups[1].Value;

        if (BareEmailRegex.IsMatch(input))
            return input;

        return null;
    }

    /// <summary>
    /// Normalizes a search query by extracting the login (local part) from
    /// "Name &lt;email&gt;", "Name (email)", or bare email formats.
    /// Returns the original query if no email pattern is found.
    /// </summary>
    public static string NormalizeSearchQuery(string query)
    {
        if (string.IsNullOrWhiteSpace(query))
            return query;

        query = query.Trim();

        var email = TryExtractEmail(query);
        if (email != null)
        {
            var atIndex = email.LastIndexOf('@');
            if (atIndex > 0)
            {
                var localPart = email.Substring(0, atIndex);
                if (!string.IsNullOrWhiteSpace(localPart) && localPart.Length >= 2)
                    return localPart;
            }
        }

        return query;
    }

    public static void AddColumnsFromDataTable(ref DataTable sourceTable, DataTable columnSourceTable, string prefix)
    {
        foreach (DataColumn column in columnSourceTable.Columns)
        {
            if (!sourceTable.Columns.Contains(prefix + column.ColumnName))
            {
                sourceTable.Columns.Add(prefix + column.ColumnName, column.DataType);
            }
        }
    }

    public class VdiFolderInfo
    {
        public string DisplayName { get; set; } = string.Empty;
        public string UncPath { get; set; } = string.Empty;
        public bool Exists { get; set; }
        public double SizeGb { get; set; }
        public string Status { get; set; } = string.Empty;
    }

    public static VdiFolderInfo[] CheckVdiFolders(string login)
    {
        var results = new VdiFolderInfo[4];

        string[] paths =
        [
            $"\\\\corp.tander.ru\\vdidfs\\users\\{login}",
            $"\\\\corp.tander.ru\\vdiwrkdfs\\users\\{login}",
            $"\\\\svm-7\\vdi_arch_exchange\\{login}",
            $"\\\\svm-5\\arch_work\\{login}"
        ];

        string[] names =
        [
            "VDI OCO",
            "VDI Work2.0",
            "Диск I (архив Exchange)",
            "Диск H (архив Work)"
        ];

        for (int i = 0; i < paths.Length; i++)
        {
            results[i] = new VdiFolderInfo
            {
                DisplayName = names[i],
                UncPath = paths[i],
                Exists = false,
                SizeGb = 0,
                Status = "Не существует"
            };

            try
            {
                if (Directory.Exists(paths[i]))
                {
                    results[i].Exists = true;
                    results[i].Status = "Существует";

                    try
                    {
                        double sizeBytes = GetDirectorySize(paths[i]);
                        results[i].SizeGb = sizeBytes / (1024.0 * 1024.0 * 1024.0);
                    }
                    catch (Exception ex)
                    {
                        results[i].Status = $"Ошибка чтения: {ex.Message}";
                    }
                }
            }
            catch (Exception ex)
            {
                results[i].Status = $"Ошибка проверки: {ex.Message}";
            }
        }

        return results;
    }

    private static double GetDirectorySize(string path)
    {
        double totalSize = 0;
        try
        {
            var dirInfo = new DirectoryInfo(path);

            if (!dirInfo.Exists)
                return 0;

            try
            {
                foreach (var file in dirInfo.GetFiles("*", SearchOption.AllDirectories))
                {
                    try
                    {
                        totalSize += file.Length;
                    }
                    catch
                    {
                    }
                }
            }
            catch (IOException)
            {
                try
                {
                    foreach (var file in dirInfo.GetFiles("*", SearchOption.TopDirectoryOnly))
                    {
                        try
                        {
                            totalSize += file.Length;
                        }
                        catch
                        {
                        }
                    }
                }
                catch
                {
                }
            }
        }
        catch
        {
        }
        return totalSize;
    }

    public static string FormatVdiFoldersResult(VdiFolderInfo[] info)
    {
        var sb = new System.Text.StringBuilder();
        sb.AppendLine("Наличие VDI папок:");
        sb.AppendLine();

        foreach (var item in info)
        {
            string status = item.Exists ? "✓" : "✗";
            string size = item.Exists ? $" ({item.SizeGb:F2} ГБ)" : "";
            sb.AppendLine($"{status} {item.DisplayName}: {item.Status}{size}");
            sb.AppendLine($"  {item.UncPath}{size}");
        }

        return sb.ToString();
    }
}
