using System;
using System.Data;
using System.IO;

namespace GetGroupBoxMember.Services;

public static class Data
{
    public static string DC { get; set; } = "corp.tander.ru";
    
    public static string AdPath_Domain { get; set; } = "/DC=corp,DC=tander,DC=ru";

    public static void Log(DataTable userInfo)
    {
        try
        {
            string logDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                "Create_UZ_logs");

            if (!Directory.Exists(logDir))
            {
                Directory.CreateDirectory(logDir);
            }

            string fileName = $"log - {DateTime.Today:dd.MM.yyyy}.csv";
            string filePath = Path.Combine(logDir, fileName);
            bool isNewFile = !File.Exists(filePath);

            using var writer = new StreamWriter(filePath, append: true);
            
            if (isNewFile)
            {
                writer.WriteLine("\"Атрибут\",\"Значение\"");
            }

            foreach (DataColumn column in userInfo.Columns)
            {
                writer.Write($"\"{column.ColumnName}\",");
                writer.WriteLine($"\"{userInfo.Rows[0][column].ToString()?.Replace("\"", "\"\"")}\"");
            }

            writer.WriteLine(",");
            writer.WriteLine("\"----    ----    ----    ----    ----\",\"----    ----    ----    ----    ----    ----    ----    ----\"");
            writer.WriteLine(",");
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException($"Ошибка записи лога: {ex.Message}", ex);
        }
    }

    public static void Log(DataTable userInfo, string oldLocation, string incident)
    {
        try
        {
            string logDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                "Create_UZ_logs");

            if (!Directory.Exists(logDir))
            {
                Directory.CreateDirectory(logDir);
            }

            string fileName = $"log - {DateTime.Today:dd.MM.yyyy}.csv";
            string filePath = Path.Combine(logDir, fileName);
            bool isNewFile = !File.Exists(filePath);

            using var writer = new StreamWriter(filePath, append: true);

            if (isNewFile)
            {
                writer.WriteLine("\"Атрибут\",\"Значение\"");
            }

            writer.Write("\"Перемещение УЗ\",");
            writer.WriteLine($"\"{userInfo.Rows[0]["Фамилия"]} {userInfo.Rows[0]["Имя"]} {userInfo.Rows[0]["Отчество"]}\"");

            writer.Write("\"Логин\",");
            writer.WriteLine($"\"{userInfo.Rows[0]["Логин"]}\"");

            writer.Write("\"Перемещено из\",");
            writer.WriteLine($"\"{oldLocation}\"");

            writer.Write("\"в\",");
            writer.WriteLine($"\"{userInfo.Rows[0]["LDAP путь"]}\"");

            writer.Write("\"по инциденту\",");
            writer.WriteLine($"\"{incident}\"");

            writer.Write("\"Модифицировано\",");
            writer.WriteLine($"\"{userInfo.Rows[0]["Модифицирована"]}\"");

            writer.WriteLine(",");
            writer.WriteLine("\"----    ----    ----    ----    ----\",\"----    ----    ----    ----    ----    ----    ----    ----\"");
            writer.WriteLine(",");
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException($"Ошибка записи лога: {ex.Message}", ex);
        }
    }
}
