using System;
using System.Data;
using System.IO;
using Microsoft.Data.Sqlite;

namespace GetGroupBoxMember.Services;

public class QueryLogger
{
    private readonly string _connectionString;
    private readonly string _dbPath;

    public QueryLogger()
    {
        var tempPath = Path.GetTempPath();
        var appFolder = Path.Combine(tempPath, "GetGroupBoxMember");

        try
        {
            Directory.CreateDirectory(appFolder);
        }
        catch
        {
            appFolder = tempPath;
        }

        _dbPath = Path.Combine(appFolder, "queries.db");
        _connectionString = $"Data Source={_dbPath}";

        Initialize();
        CleanupOldEntries();
    }

    private void Initialize()
    {
        try
        {
            using var conn = new SqliteConnection(_connectionString);
            conn.Open();

            var cmd = conn.CreateCommand();
            cmd.CommandText = @"
                CREATE TABLE IF NOT EXISTS QueryLog (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    Timestamp DATETIME NOT NULL,
                    QueryText TEXT NOT NULL,
                    SearchType TEXT NOT NULL,
                    ResultCount INTEGER DEFAULT 0
                )";
            cmd.ExecuteNonQuery();

            cmd.CommandText = "CREATE INDEX IF NOT EXISTS idx_timestamp ON QueryLog(Timestamp)";
            cmd.ExecuteNonQuery();
        }
        catch { }
    }

    private void CleanupOldEntries()
    {
        try
        {
            using var conn = new SqliteConnection(_connectionString);
            conn.Open();

            var cmd = conn.CreateCommand();
            cmd.CommandText = @"DELETE FROM QueryLog WHERE Timestamp < datetime('now', '-7 days')";
            cmd.ExecuteNonQuery();
        }
        catch { }
    }

    public void Log(string queryText, string searchType, int resultCount = 0)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(queryText) || string.IsNullOrWhiteSpace(searchType))
                return;

            using var conn = new SqliteConnection(_connectionString);
            conn.Open();

            var cmd = conn.CreateCommand();
            cmd.CommandText = @"INSERT INTO QueryLog (Timestamp, QueryText, SearchType, ResultCount) VALUES (@timestamp, @queryText, @searchType, @resultCount)";

            cmd.Parameters.AddWithValue("@timestamp", DateTime.Now);
            cmd.Parameters.AddWithValue("@queryText", queryText);
            cmd.Parameters.AddWithValue("@searchType", searchType);
            cmd.Parameters.AddWithValue("@resultCount", resultCount);

            cmd.ExecuteNonQuery();
        }
        catch { }
    }

    public DataTable GetHistory()
    {
        var dt = new DataTable("History");

        dt.Columns.Add("Дата", typeof(string));
        dt.Columns.Add("Время", typeof(string));
        dt.Columns.Add("Запрос", typeof(string));
        dt.Columns.Add("Тип", typeof(string));
        dt.Columns.Add("Результатов", typeof(int));

        try
        {
            using var conn = new SqliteConnection(_connectionString);
            conn.Open();

            var cmd = conn.CreateCommand();
            cmd.CommandText = @"SELECT strftime('%d.%m.%Y', Timestamp), strftime('%H:%M:%S', Timestamp), QueryText, SearchType, ResultCount FROM QueryLog ORDER BY Timestamp DESC LIMIT 1000";

            using var reader = cmd.ExecuteReader();
            while (reader.Read())
            {
                dt.Rows.Add(
                    reader.GetString(0),
                    reader.GetString(1),
                    reader.GetString(2),
                    reader.GetString(3),
                    reader.GetInt32(4)
                );
            }
        }
        catch { }

        return dt;
    }
}
