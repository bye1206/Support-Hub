using System;
using System.Collections.Generic;
using System.Data;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using ClosedXML.Excel;

namespace GetGroupBoxMember.Services;

internal class ExcelLog(string Path, bool Overwriting = true)
{
	private StreamWriter? _log;

	public Exception Open()
	{
		try
		{
			_log = new StreamWriter(Path, !Overwriting);
		}
		catch (Exception result)
		{
			_log?.Dispose();
			return result;
		}
		return null;
	}

	public Exception WriteLine(string Value)
	{
		try
		{
			_log?.WriteLine(Value);
		}
		catch (Exception result)
		{
			_log?.Dispose();
			return result;
		}
		return null;
	}

	private static string EscapeCsvField(string value)
	{
		if (value.Contains('"') || value.Contains(',') || value.Contains(';') || value.Contains('\n'))
		{
			return "\"" + value.Replace("\"", "\"\"") + "\"";
		}
		return value;
	}

	public Exception WriteCsv(DataTable ValueDT)
	{
		try
		{
			if (Overwriting)
			{
				var headers = ValueDT.Columns.Cast<DataColumn>().Select(c => EscapeCsvField(c.ColumnName));
				_log?.WriteLine(string.Join(",", headers));
			}
			foreach (DataRow row in ValueDT.Rows)
			{
				var fields = ValueDT.Columns.Cast<DataColumn>().Select((c, i) => EscapeCsvField(row[i]?.ToString() ?? ""));
				_log?.WriteLine(string.Join(",", fields));
			}
		}
		catch (Exception result)
		{
			_log?.Dispose();
			return result;
		}
		return null;
	}

	public Exception WriteExcel(DataTable ValueDT) => WriteXlsx(ValueDT);

	public Exception WriteXls(DataTable ValueDT) => WriteXlsx(ValueDT);

	public Exception WriteXlsx(DataTable ValueDT) => WriteXlsx(ValueDT, null);

	public Exception WriteXlsx(DataTable ValueDT, string[]? columnsToExport)
	{
		try
		{
			if (Overwriting && File.Exists(Path))
				File.Delete(Path);

			var workbook = new XLWorkbook();
			var sheetName = string.IsNullOrWhiteSpace(ValueDT.TableName) ? "Sheet1" : ValueDT.TableName;
			sheetName = Regex.Replace(sheetName, @"[\\/?*\[\]:]", "_");
			if (sheetName.Length > 31)
				sheetName = sheetName[..31];
			var worksheet = workbook.Worksheets.Add(sheetName);

			var columns = columnsToExport ?? ValueDT.Columns.Cast<DataColumn>().Select(c => c.ColumnName).ToArray();
			var columnIndices = new List<int>();
			for (var col = 0; col < columns.Length; col++)
			{
				if (string.IsNullOrEmpty(columns[col])) continue;
				var colName = Regex.Replace(columns[col]!, @"[\\/?*\[\]:]", "_");
				worksheet.Cell(1, col + 1).Value = colName;
				worksheet.Cell(1, col + 1).Style.Font.Bold = true;
				var sourceIndex = ValueDT.Columns.Contains(columns[col]) ? ValueDT.Columns[columns[col]].Ordinal : -1;
				columnIndices.Add(sourceIndex);
			}

			for (var row = 0; row < ValueDT.Rows.Count; row++)
			{
				for (var col = 0; col < columns.Length; col++)
				{
					var sourceIndex = columnIndices[col];
					if (sourceIndex >= 0)
					{
						var value = ValueDT.Rows[row][sourceIndex];
						if (value is not null and not DBNull)
						{
							var strValue = value.ToString() ?? "";
							if (strValue.Length > 32767)
								strValue = strValue[..32767];
							worksheet.Cell(row + 2, col + 1).Value = strValue;
						}
					}
				}
			}

			for (var col = 0; col < columns.Length; col++)
			{
				var colName = columns[col];
				if (string.IsNullOrEmpty(colName)) continue;
				var column = worksheet.Column(col + 1);

				if (colName == "Recipients")
					column.Width = 50;
				else if (colName == "MessageSubject")
					column.Width = 40;
				else if (colName == "MessageID" || colName == "MessageId")
					column.Width = 35;
				else if (colName == "Timestamp")
					column.Width = 20;
				else if (colName == "Sender")
					column.Width = 25;
				else
					column.Width = 15;
			}

			workbook.SaveAs(Path);
		}
		catch (Exception result)
		{
			return result;
		}
		return null;
	}

	public Exception WriteTxt(DataTable ValueDT)
	{
		try
		{
			if (Overwriting && File.Exists(Path))
				File.Delete(Path);

			using var writer = new StreamWriter(Path, false, Encoding.UTF8);

			var headers = ValueDT.Columns.Cast<DataColumn>().Select(c => c.ColumnName);
			writer.WriteLine(string.Join("\t", headers));

			foreach (DataRow row in ValueDT.Rows)
			{
				var values = row.ItemArray
					.Select(item => {
						var str = item?.ToString() ?? "";
						if (str.Length > 32767)
							str = str[..32767];
						return str.Replace("\t", " ").Replace("\r", "").Replace("\n", " ");
					})
					.ToList();
				writer.WriteLine(string.Join("\t", values));
			}
		}
		catch (Exception result)
		{
			return result;
		}
		return null;
	}

	public DataSet ReadXlsxAllSheets()
	{
		var dataSet = new DataSet();
		try
		{
			using var workbook = new XLWorkbook(Path);
			foreach (var worksheet in workbook.Worksheets)
			{
				var dataTable = new DataTable { TableName = worksheet.Name };

				var firstRow = worksheet.FirstRowUsed();
				if (firstRow == null) continue;

				var lastColumnUsed = worksheet.LastColumnUsed()?.ColumnNumber() ?? 0;
				for (var col = 1; col <= lastColumnUsed; col++)
				{
					var header = firstRow.Cell(col).GetString();
					dataTable.Columns.Add(string.IsNullOrWhiteSpace(header) ? $"Column{col}" : header);
				}

				var lastRowUsed = worksheet.LastRowUsed();
				if (lastRowUsed != null)
				{
					var lastRowNumber = lastRowUsed.RowNumber();
					for (var rowNum = firstRow.RowNumber() + 1; rowNum <= lastRowNumber; rowNum++)
					{
						var dataRow = dataTable.NewRow();
						for (var col = 1; col <= lastColumnUsed; col++)
						{
							var cell = worksheet.Cell(rowNum, col);
							dataRow[col - 1] = cell.IsEmpty() ? DBNull.Value : cell.Value;
						}
						dataTable.Rows.Add(dataRow);
					}
				}

				dataSet.Tables.Add(dataTable);
			}
		}
		catch (Exception)
		{
		}
		return dataSet;
	}

	public DataTable ReadExcelFirstSheets()
	{
		var dataTable = new DataTable();
		try
		{
			using var workbook = new XLWorkbook(Path);
			var worksheet = workbook.Worksheets.First();

			var firstRow = worksheet.FirstRowUsed();
			if (firstRow == null) return dataTable;

			var lastColumnUsed = worksheet.LastColumnUsed()?.ColumnNumber() ?? 0;
			for (var col = 1; col <= lastColumnUsed; col++)
			{
				var header = firstRow.Cell(col).GetString();
				dataTable.Columns.Add(string.IsNullOrWhiteSpace(header) ? $"Column{col}" : header);
			}

			var lastRowUsed = worksheet.LastRowUsed();
			if (lastRowUsed != null)
			{
				var lastRowNumber = lastRowUsed.RowNumber();
				for (var rowNum = firstRow.RowNumber() + 1; rowNum <= lastRowNumber; rowNum++)
				{
					var dataRow = dataTable.NewRow();
					for (var col = 1; col <= lastColumnUsed; col++)
					{
						var cell = worksheet.Cell(rowNum, col);
						dataRow[col - 1] = cell.IsEmpty() ? DBNull.Value : cell.Value;
					}
					dataTable.Rows.Add(dataRow);
				}
			}
		}
		catch (Exception)
		{
		}
		return dataTable;
	}

	public Exception Close()
	{
		try
		{
			_log?.Close();
		}
		catch (Exception result)
		{
			_log?.Dispose();
			return result;
		}
		return null;
	}
}
