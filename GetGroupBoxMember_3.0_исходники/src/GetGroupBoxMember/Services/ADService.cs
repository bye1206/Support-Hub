using System.Data;
using GetGroupBoxMember.Models;

namespace GetGroupBoxMember.Services;

public class ADService : IADService
{
    private readonly AD _ad = new();

    public async Task<List<UserInfo>> FastSearchAsync(string query, string entityType, CancellationToken cancellationToken = default, Action<string>? onProgress = null)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return new List<UserInfo>();
        }

        cancellationToken.ThrowIfCancellationRequested();

        switch (entityType)
        {
            case "User":
                return await FastSearchUsersAsync(query, onProgress, cancellationToken).ConfigureAwait(false);
            case "Group":
                onProgress?.Invoke("Поиск групп...");
                return await Task.Run(() => FastSearchGroups(query), cancellationToken).ConfigureAwait(false);
            case "MailList":
                onProgress?.Invoke("Поиск рассылок...");
                return await Task.Run(() => FastSearchMailLists(query), cancellationToken).ConfigureAwait(false);
            case "DynamicGroup":
                onProgress?.Invoke("Поиск динамических рассылок...");
                return await Task.Run(() => FastSearchDynamicGroups(query), cancellationToken).ConfigureAwait(false);
            case "Computer":
                onProgress?.Invoke("Поиск ПК...");
                return await Task.Run(() => FastSearchComputers(query), cancellationToken).ConfigureAwait(false);
            default:
                return await FastSearchUsersAsync(query, onProgress).ConfigureAwait(false);
        }
    }

    private static readonly System.Text.RegularExpressions.Regex PhoneRegex = 
        new(@"^(\+7|8|9\d{2})", 
            System.Text.RegularExpressions.RegexOptions.Compiled);

    private static readonly System.Text.RegularExpressions.Regex Guid1CRegex = 
        new(@"^\d{4,16}$", 
            System.Text.RegularExpressions.RegexOptions.Compiled);

    private static readonly System.Text.RegularExpressions.Regex GuidMDRegex = 
        new(@"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", 
            System.Text.RegularExpressions.RegexOptions.Compiled);

    private async Task<List<UserInfo>> FastSearchUsersAsync(string query, Action<string>? onProgress = null, CancellationToken cancellationToken = default)
    {
        if (GuidMDRegex.IsMatch(query))
        {
            var result = await Task.Run(() => FastSearchUsersByGuid(query)).ConfigureAwait(false);
            return result;
        }

        bool isGuid1CSearch = Guid1CRegex.IsMatch(query);
        if (isGuid1CSearch)
        {
            onProgress?.Invoke("Поиск по guid1C...");
            var result1C = await Task.Run(() => _ad.Fast_GetUserInfoOnGuid1C(query)).ConfigureAwait(false);
            var seenLogins1C = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var users = new List<UserInfo>();
            foreach (var user in ConvertDataTableToUserInfoList(result1C))
            {
                if (!string.IsNullOrWhiteSpace(user.Login) && seenLogins1C.Add(user.Login))
                    users.Add(user);
            }
            if (users.Count > 0)
                return users;
        }

        bool isPhoneSearch = PhoneRegex.IsMatch(query);
        if (isPhoneSearch)
        {
            onProgress?.Invoke("Поиск по телефону...");
            var phoneResults = await Task.Run(() => SearchByPhone(query)).ConfigureAwait(false);
            if (phoneResults.Count > 0)
            {
                onProgress?.Invoke($"Найдено: {phoneResults.Count}");
                return phoneResults;
            }
        }

        var seenLogins = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var allResults = new List<UserInfo>();

        async Task<DataTable> SearchWithTimeout(Func<DataTable> searchFunc, string attrName, string label)
        {
            cancellationToken.ThrowIfCancellationRequested();
            onProgress?.Invoke($"Поиск по {label}...");
            try
            {
                var result = await Task.Run(() => searchFunc()).ConfigureAwait(false);
                return result ?? new DataTable();
            }
            catch (Exception)
            {
                onProgress?.Invoke($"Ошибка: {label}");
                return new DataTable();
            }
        }

        var attrOrder = new[] 
        { 
            ("login", "логину", (Func<DataTable>)(() => _ad.Fast_GetUserInfoOnLogin(query))),
            ("sharedMailbox", "ГПЯ", (Func<DataTable>)(() => _ad.Fast_GetSharedMailboxInfoOnLogin(query))),
            ("mail", "почте", (Func<DataTable>)(() => _ad.Fast_GetUserInfoOnMail(query))),
            ("displayName", "отображаемому имени", (Func<DataTable>)(() => _ad.Fast_GetUserInfoOnDisplayName(query))),
        };

        foreach (var (attr, label, searchFunc) in attrOrder)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var result = await SearchWithTimeout(searchFunc, attr, label);
            
            var found = new List<UserInfo>();
            foreach (var user in ConvertDataTableToUserInfoList(result))
            {
                if (!string.IsNullOrWhiteSpace(user.Login) && seenLogins.Add(user.Login))
                {
                    found.Add(user);
                    allResults.Add(user);
                }
            }

            if (found.Count > 0)
            {
                onProgress?.Invoke($"Найдено: {found.Count}");
            }
            else
            {
                onProgress?.Invoke($"Не найдено, ищем дальше...");
            }
        }

        return allResults;
    }

    private List<UserInfo> SearchByPhone(string query)
    {
        try
        {
            var result = _ad.Fast_GetUserInfoOnMobilepers(query);
            var seenLogins = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var users = new List<UserInfo>();
            
            foreach (var user in ConvertDataTableToUserInfoList(result))
            {
                if (!string.IsNullOrWhiteSpace(user.Login) && seenLogins.Add(user.Login))
                {
                    users.Add(user);
                }
            }
            return users;
        }
        catch (Exception)
        {
            return new List<UserInfo>();
        }
    }

    private List<UserInfo> FastSearchUsersByGuid(string query)
    {
        try
        {
            var results1 = _ad.Fast_GetUserInfoOnGuid1C(query);
            var results2 = _ad.Fast_GetUserInfoOnGuidMD(query);
            
            var seenLogins = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var allResults = new List<UserInfo>();
            
            foreach (var user in ConvertDataTableToUserInfoList(results1))
            {
                if (!string.IsNullOrWhiteSpace(user.Login) && seenLogins.Add(user.Login))
                {
                    allResults.Add(user);
                }
            }
            
            foreach (var user in ConvertDataTableToUserInfoList(results2))
            {
                if (!string.IsNullOrWhiteSpace(user.Login) && seenLogins.Add(user.Login))
                {
                    allResults.Add(user);
                }
            }
            
            return allResults;
        }
        catch (Exception)
        {
            return new List<UserInfo>();
        }
    }

    private List<UserInfo> FastSearchGroups(string query)
    {
        try
        {
            var result = _ad.GetGroupInfo(query, out var error);
            return ConvertDataTableToUserInfoList(result);
        }
        catch (Exception)
        {
            return new List<UserInfo>();
        }
    }

    private List<UserInfo> FastSearchMailLists(string query)
    {
        try
        {
            var result = _ad.GetMaillistInfo(query);
            return ConvertDataTableToUserInfoList(result);
        }
        catch (Exception)
        {
            return new List<UserInfo>();
        }
    }

    private List<UserInfo> FastSearchDynamicGroups(string query)
    {
        try
        {
            var result = _ad.GetDynamicGroupInfo(query);
            return ConvertDataTableToUserInfoList(result);
        }
        catch (Exception)
        {
            return new List<UserInfo>();
        }
    }

    private List<UserInfo> FastSearchComputers(string query)
    {
        try
        {
            var result = _ad.Fast_GetComputerInfo(query);
            return ConvertDataTableToUserInfoList(result);
        }
        catch (Exception)
        {
            return new List<UserInfo>();
        }
    }

    public Task<List<UserInfo>> GetUserInfoAsync(string query, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            string type = GuidMDRegex.IsMatch(query) ? "guidMD"
                : Guid1CRegex.IsMatch(query) ? "guid1C"
                : PhoneRegex.IsMatch(query) ? "mobilepers"
                : "User";
            var results = _ad.GetUserInfo(query, type);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<UserMoreInfo?> GetUserMoreInfoAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetUserMoreInfo(login, out var error);
            if (error != null || results.Rows.Count == 0)
                return null;

            return ConvertDataRowToUserMoreInfo(results.Rows[0]);
        }, cancellationToken);
    }

    public Task<DataTable?> GetUserMoreInfoTableAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetUserMoreInfo(login, out var error);
            if (error != null || results.Rows.Count == 0)
                return null;

            return results;
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetGroupInfoAsync(string query, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetGroupInfo(query, out var error);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetGroupMembersAsync(string distinguishedName, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetGroupMembers(distinguishedName);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<DataTable> GetGroupMembersDataTableAsync(string distinguishedName, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetGroupMembers(distinguishedName);
            results.TableName = $"Участники группы: {GetGroupNameFromDN(distinguishedName)}";
            return results;
        }, cancellationToken);
    }

    public Task<DataTable> GetDynamicGroupMembersDataTableAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var moreInfo = _ad.GetDynamicDistributionGroupMoreInfo(login);
            string recipientContainer = "";
            string ldapRecipientFilter = "";
            if (moreInfo.Rows.Count > 0)
            {
                recipientContainer = moreInfo.Rows[0]["RecipientContainer"]?.ToString() ?? "";
                ldapRecipientFilter = moreInfo.Rows[0]["RecipientFilter"]?.ToString() ?? "";
            }
            if (string.IsNullOrEmpty(recipientContainer) || string.IsNullOrEmpty(ldapRecipientFilter))
            {
                return new DataTable();
            }
            var results = _ad.GetDynamicDistributionGroupMembers(recipientContainer, ldapRecipientFilter);
            if (results != null)
                results.TableName = $"Участники динамической рассылки: {login}";
            return results ?? new DataTable();
        }, cancellationToken);
    }

    private string GetGroupNameFromDN(string distinguishedName)
    {
        if (string.IsNullOrWhiteSpace(distinguishedName)) return "";
        var parts = distinguishedName.Split(',');
        foreach (var part in parts)
        {
            if (part.StartsWith("CN=", StringComparison.OrdinalIgnoreCase))
            {
                return part.Substring(3);
            }
        }
        return distinguishedName;
    }

    public Task<List<UserInfo>> GetMailListInfoAsync(string query, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetMaillistInfo(query);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetDynamicGroupInfoAsync(string query, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetDynamicGroupInfo(query);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<DataTable?> GetGroupInfoDataTableAsync(string query, string type, CancellationToken cancellationToken = default)
    {
        return Task.Run<DataTable?>(() =>
        {
            Exception? error;
            DataTable dt;
            if (type == "mail")
            {
                dt = _ad.GetGroupInfo(query, "mail", out error);
            }
            else
            {
                dt = _ad.GetGroupInfo(query, "cn", out error);
            }
            return dt;
        }, cancellationToken);
    }

    public Task<DataTable?> GetDynamicDistributionGroupInfoDataTableAsync(string query, string type, CancellationToken cancellationToken = default)
    {
        return Task.Run<DataTable?>(() =>
        {
            return _ad.GetDynamicDistributionGroupInfo(query, type);
        }, cancellationToken);
    }

    public Task<DataTable?> GetMailListInfoDataTableAsync(string query, CancellationToken cancellationToken = default)
    {
        return Task.Run<DataTable?>(() =>
        {
            return _ad.GetMaillistInfo(query);
        }, cancellationToken);
    }

    public Task<DataTable?> GetComputerInfoDataTableAsync(string query, CancellationToken cancellationToken = default)
    {
        return Task.Run<DataTable?>(() =>
        {
            return _ad.GetComputerInfo(query);
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetComputerInfoAsync(string query, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetComputerInfo(query);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<DataTable?> GetComputerInfoForInfoWindowAsync(string compName, CancellationToken cancellationToken = default, Action<string>? progress = null)
    {
        return Task.Run<DataTable?>(() =>
        {
            progress?.Invoke("Загрузка данных ПК...");
            var results = _ad.GetComputerInfo(compName);
            if (results == null || results.Rows.Count == 0)
                return null;

            results.TableName = $"Инфо: {compName}";

            var pcRow = results.Rows[0];
            var groupsValue = "";

            for (int i = 0; i < results.Columns.Count; i++)
            {
                if (results.Columns[i].ColumnName == "Состоит в группах")
                {
                    groupsValue = pcRow[i]?.ToString() ?? "";
                    break;
                }
            }

            var groupDns = new List<string>();
            if (!string.IsNullOrEmpty(groupsValue))
            {
                groupDns.AddRange(groupsValue.Split('|', StringSplitOptions.RemoveEmptyEntries));
            }

            if (groupDns.Count == 0)
            {
                results.ExtendedProperties["GroupDetails"] = new List<(string dn, string cn, string description)>();
                return results;
            }

            progress?.Invoke($"Загрузка {groupDns.Count} групп ПК...");

            var groupInfo = _ad.GetGroupsBatch(groupDns);

            var groupDetails = groupDns
                .Select(dn =>
                {
                    var cn = ExtractCNFromDN(dn);
                    if (groupInfo.TryGetValue(dn, out var info))
                    {
                        return (dn, cn: info.cn, description: info.description);
                    }
                    return (dn, cn, description: "");
                })
                .Where(g => !string.IsNullOrEmpty(g.cn))
                .OrderBy(g => g.cn, StringComparer.OrdinalIgnoreCase)
                .ToList();

            progress?.Invoke($"Загружено {groupDetails.Count} групп...");
            results.ExtendedProperties["GroupDetails"] = groupDetails;
            return results;
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetGroupBoxAccessAsync(string login, string distinguishedName, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetGroupBoxAccess(login, distinguishedName);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<DataTable> GetGroupBoxAccessDataTableAsync(string login, string distinguishedName, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetGroupBoxAccess(login, distinguishedName);
            results.TableName = $"Доступ к ящикам: {login}";
            return results;
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetMailboxAccessAsync(string login, string distinguishedName, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetMailboxAccess(login, distinguishedName);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<DataTable> GetMailboxAccessDataTableAsync(string login, string distinguishedName, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetMailboxAccess(login, distinguishedName);
            results.TableName = $"Рассылки: {login}";
            return results;
        }, cancellationToken);
    }

    public Task<DataTable> GetVladetelIsListAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            if (string.IsNullOrWhiteSpace(login))
            {
                return new DataTable("Empty");
            }
            
            var loginDT = new DataTable();
            loginDT.Columns.Add("Логин");
            loginDT.TableName = login + ": владение информационными системами.";
            var newRow = loginDT.NewRow();
            newRow[0] = login;
            loginDT.Rows.Add(newRow);
            
            var results = _ad.GetVladetelIsList(loginDT);
            
            if (results != null && results.Columns.Contains("Логин"))
            {
                results.Columns.Remove("Логин");
            }
            
            if (results != null)
            {
                return results;
            }
            else
            {
                return new DataTable("Empty");
            }
        }, cancellationToken);
    }

    public async Task<string?> GetQuotaDataAsync(string email, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(email))
        {
            return null;
        }

        string emailAddress = email;
        if (!emailAddress.Contains("@"))
            emailAddress = emailAddress + "@magnit.ru";
        emailAddress = emailAddress.Replace("'", "''");

        string tempFile = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"ggbm_quota_{Guid.NewGuid()}.ps1");

        try
        {
            string psScript = $@"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
try {{
    $sessionOption = New-PSSessionOption -UICulture 'ru-RU'
    $sess = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -SessionOption $sessionOption -ErrorAction Stop
    $stats = Invoke-Command -Session $sess -ScriptBlock {{ Get-MailboxStatistics -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList '{emailAddress}'
    Remove-PSSession $sess -ErrorAction SilentlyContinue
    
    if ($null -eq $stats) {{
        Write-Output 'NO_STATS'
        exit
    }}
    
    $sizeStr = ""$($stats.TotalItemSize)"" -replace '\s*\([\d,\s]+\s*bytes\)', ''
    Write-Output ('Used - ' + $sizeStr)
}}
catch {{
    Write-Output ('Error - ' + $_.Exception.Message)
}}
";
            System.IO.File.WriteAllText(tempFile, psScript, new System.Text.UTF8Encoding(true));

            var psi = new System.Diagnostics.ProcessStartInfo();
            psi.FileName = "powershell.exe";
            psi.Arguments = $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tempFile}\"";
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.StandardOutputEncoding = System.Text.Encoding.UTF8;
            psi.StandardErrorEncoding = System.Text.Encoding.UTF8;

            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc != null)
            {
                var waitTask = proc.WaitForExitAsync(cancellationToken);
                var timeoutTask = Task.Delay(30000, cancellationToken);
                var completedTask = await Task.WhenAny(waitTask, timeoutTask);

                if (completedTask == timeoutTask)
                {
                    try { proc.Kill(); } catch { }
                    return null;
                }

                string output = await proc.StandardOutput.ReadToEndAsync(cancellationToken);
                output = output.Trim();

                if (output.StartsWith("ERROR:") || output.StartsWith("NO_STATS") || output.Contains("not found"))
                {
                    return null;
                }

                if (!string.IsNullOrEmpty(output) && output.StartsWith("Used - "))
                {
                    return "Занято - " + output.Substring(6);
                }

                if (!string.IsNullOrEmpty(output) && !output.StartsWith("Error"))
                {
                    return "Занято - " + output;
                }
            }
        }
        catch { }
        finally
        {
            try { if (System.IO.File.Exists(tempFile)) System.IO.File.Delete(tempFile); } catch { }
        }

        return null;
    }

    public async Task<string?> GetRetentionPolicyAsync(string email, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(email))
            return null;

        var emailAddress = email.Contains('@') ? email : $"{email}@magnit.ru";

        try
        {
            var result = await _ad.GetRetentionPolicyAsync(emailAddress);
            if (!string.IsNullOrEmpty(result))
            {
                return result;
            }
        }
        catch { }

        return null;
    }

    public Task<string?> GetManagerInfoAsync(string managerDN, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            if (string.IsNullOrWhiteSpace(managerDN))
            {
                return (string?)null;
            }

            var dt = _ad.GetManagerInfo(managerDN);
            
            if (dt.Rows.Count > 0)
            {
                var displayName = dt.Rows[0]["DisplayName"]?.ToString() ?? "";
                var mail = dt.Rows[0]["Mail"]?.ToString() ?? "";
                
                if (!string.IsNullOrWhiteSpace(displayName))
                {
                    return !string.IsNullOrWhiteSpace(mail) 
                        ? $"{displayName} ({mail})" 
                        : displayName;
                }
                else if (!string.IsNullOrWhiteSpace(mail))
                {
                    return mail;
                }
            }
            
            return (string?)null;
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetEximMembersAsync(string mail, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetEximMembers(mail);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetExchangeMembersAsync(string mail, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetExchangeMembers(mail);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetMaillistExchangeMembersAsync(string mail, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var resultList = new List<UserInfo>();
            if (string.IsNullOrWhiteSpace(mail))
                return resultList;

            var groupInfo = _ad.GetGroupInfo(mail, "mail", out var error);
            if (error != null || groupInfo == null || groupInfo.Rows.Count == 0)
                return resultList;

            var groupDn = groupInfo.Rows[0]["distinguishedName"]?.ToString() ?? "";
            if (string.IsNullOrWhiteSpace(groupDn))
                return resultList;

            var members = _ad.GetGroupMembers(groupDn);
            return ConvertDataTableToUserInfoList(members);
        }, cancellationToken);
    }

    public Task<List<UserInfo>> GetMembersByDnListAsync(string memberDns, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var resultList = new List<UserInfo>();
            
            if (string.IsNullOrWhiteSpace(memberDns))
            {
                return resultList;
            }

            var dns = memberDns.Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries);
            
            foreach (var dn in dns)
            {
                try
                {
                    var userDt = _ad.GetUserByDN(dn);
                    var users = ConvertDataTableToUserInfoList(userDt);
                    resultList.AddRange(users);
                }
                catch
                {
                }
            }

            return resultList;
        }, cancellationToken);
    }

    public Task<DataTable> GetUserByDnAsync(string distinguishedName, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            return _ad.GetUserByDN(distinguishedName);
        }, cancellationToken);
    }

    public Task<DataTable?> GetHierarchyAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run<DataTable?>(() =>
        {
            var userInfo = _ad.GetUserInfo(login, "User");
            if (userInfo.Rows.Count > 0 && userInfo.Columns.Contains("distinguishedName"))
            {
                var dn = userInfo.Rows[0]["distinguishedName"]?.ToString();
                if (!string.IsNullOrWhiteSpace(dn))
                {
                    return _ad.GetFullHierarchy(dn);
                }
            }
            return null;
        }, cancellationToken);
    }

    public Task<List<UserInfo>> FindPCByOwnerAsync(string ownerLogin, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var results = _ad.GetComputerInfoByOwner(ownerLogin);
            return ConvertDataTableToUserInfoList(results);
        }, cancellationToken);
    }

    public Task<DataTable> GetRepadminInfoAttributeMetaDataAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            return _ad.GetRepadminInfoAttributeMetaData(login);
        }, cancellationToken);
    }

    public Task<DataTable> GetRepadminInfoValueMetaDataAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            return _ad.GetRepadminInfoValueMetaData(login);
        }, cancellationToken);
    }

    public Task<DataTable> GetUsersGroupComparisonAsync(string login1, string login2, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            return _ad.GetUsersGroupComparison(login1, login2);
        }, cancellationToken);
    }

    public Task<DataTable> GetGroupMoreInfoAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            return _ad.GetGroupMoreInfo(login);
        }, cancellationToken);
    }

    public Task<DataTable> GetMaillistMoreInfoAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            return _ad.GetMaillistMoreInfo(login);
        }, cancellationToken);
    }

    public Task<DataTable> GetDynamicGroupMoreInfoAsync(string login, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            return _ad.GetDynamicDistributionGroupMoreInfo(login);
        }, cancellationToken);
    }

    public async Task<(string lastLogonTime, string domainController)> GetUserLastLogonAsync(string login, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(login))
        {
            return ("Нет данных", "Нет данных");
        }

        string tempFile = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"ggbm_lastlogon_{Guid.NewGuid()}.ps1");

        string loginEscaped = login.Replace("'", "''");
        
        try
        {
            string psScript = @"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$u = '" + loginEscaped + @"'
Write-Output ('DEBUG: Starting LastLogon query for user: ' + $u)
try {
    $root = [adsi]""LDAP://RootDSE""
    $cfg = $root.configurationNamingContext[0]
    $site = [System.DirectoryServices.ActiveDirectory.ActiveDirectorySite]::GetComputerSite().Name
    Write-Output ('DEBUG: Current site: ' + $site)
    $s = [adsisearcher]""(objectClass=server)""
    $s.SearchRoot = [adsi]""LDAP://CN=Servers,CN=$site,CN=Sites,$cfg""
    $servers = $s.FindAll()
    Write-Output ('DEBUG: Found ' + $servers.Count + ' servers in site')
    $data = @()
    foreach ($srv in $servers) {
        try {
            $dc = $srv.Properties['dnshostname'][0]
            Write-Output ('DEBUG: Querying DC: ' + $dc)
            $q = [adsisearcher]""(&(sAMAccountName=$u)(objectClass=user))""
            $q.SearchRoot = [adsi]""LDAP://$dc""
            $q.PropertiesToLoad.Add('lastLogon') | Out-Null
            $r = $q.FindOne()
            $ll = 0
            if ($r) {
                $prop = $r.Properties['lastLogon']
                if ($prop) { $ll = [long]$prop[0] }
            }
            $data += [pscustomobject]@{ DC = $dc; LL = $ll }
        } catch {
            Write-Output ('DEBUG: DC skipped due to error: ' + $dc)
        }
    }
    $best = $data | Where-Object { $_.LL -gt 0 } | Sort-Object LL -Descending | Select-Object -First 1
    if ($best) {
        $dt = [DateTime]::FromFileTime($best.LL)
        Write-Output ('OK|' + $best.DC + '|' + $dt.ToString('dd.MM.yyyy HH:mm:ss'))
    } else {
        Write-Output 'NO_DATA'
    }
} catch {
    Write-Output ('ERROR|' + $_.Exception.Message)
}
";

            System.IO.File.WriteAllText(tempFile, psScript, new System.Text.UTF8Encoding(true));

            var psi = new System.Diagnostics.ProcessStartInfo();
            psi.FileName = "powershell.exe";
            psi.Arguments = $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tempFile}\"";
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.StandardOutputEncoding = System.Text.Encoding.UTF8;
            psi.StandardErrorEncoding = System.Text.Encoding.UTF8;

            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc != null)
            {
                var stderrTask = proc.StandardError.ReadToEndAsync();
                var waitTask = proc.WaitForExitAsync();
                var timeoutTask = Task.Delay(60000);
                var completedTask = await Task.WhenAny(waitTask, timeoutTask);

                string output;
                if (completedTask == timeoutTask)
                {
                    try { proc.Kill(); } catch { }
                    output = "";
                }
                else
                {
                    output = proc.StandardOutput.ReadToEnd().Trim();
                    try { await stderrTask; } catch { }
                }

                if (output.Contains("OK|"))
                {
                    var okLine = output.Split(new[] { Environment.NewLine }, StringSplitOptions.RemoveEmptyEntries)
                        .FirstOrDefault(l => l.StartsWith("OK|"));
                    if (okLine != null)
                    {
                        var parts = okLine.Substring(3).Split('|');
                        if (parts.Length >= 2)
                        {
                            return (parts[1], parts[0]);
                        }
                    }
                }
            }
        }
        catch (Exception)
        {
        }
        finally
        {
            try { if (System.IO.File.Exists(tempFile)) System.IO.File.Delete(tempFile); } catch { }
        }

        return ("Нет данных", "Нет данных");
    }

    public Task<DataTable?> GetUserInfoForInfoWindowAsync(string login, CancellationToken cancellationToken = default, Action<string>? progress = null)
    {
        return Task.Run<DataTable?>(() =>
        {
            progress?.Invoke("Загрузка данных пользователя...");
            var results = _ad.GetUserMoreInfo(login, out var error);
            if (error != null || results.Rows.Count == 0)
                return null;

            var userRow = results.Rows[0];
            var groupsValue = "";

            for (int i = 0; i < results.Columns.Count; i++)
            {
                if (results.Columns[i].ColumnName == "Состоит в группах")
                {
                    groupsValue = userRow[i]?.ToString() ?? "";
                    break;
                }
            }

            var groupDns = new List<string>();
            if (!string.IsNullOrEmpty(groupsValue))
            {
                groupDns.AddRange(groupsValue.Split('|', StringSplitOptions.RemoveEmptyEntries));
            }

            if (groupDns.Count == 0)
            {
                results.ExtendedProperties["GroupDetails"] = new List<(string dn, string cn, string description)>();
                return results;
            }

            progress?.Invoke($"Загрузка {groupDns.Count} групп пользователя...");

            var groupInfo = _ad.GetGroupsBatch(groupDns);

            var groupDetails = groupDns
                .Select(dn =>
                {
                    var cn = ExtractCNFromDN(dn);
                    if (groupInfo.TryGetValue(dn, out var info))
                    {
                        return (dn, cn: info.cn, description: info.description);
                    }
                    return (dn, cn, description: "");
                })
                .Where(g => !string.IsNullOrEmpty(g.cn))
                .OrderBy(g => g.cn, StringComparer.OrdinalIgnoreCase)
                .ToList();

            progress?.Invoke($"Загружено {groupDetails.Count} групп...");
            results.ExtendedProperties["GroupDetails"] = groupDetails;
            return results;
        }, cancellationToken);
    }

    private static string ExtractCNFromDN(string dn)
    {
        if (string.IsNullOrWhiteSpace(dn)) return "";
        var cnPart = dn.Replace("CN=", "", StringComparison.OrdinalIgnoreCase);
        var commaIndex = cnPart.IndexOf(",", StringComparison.Ordinal);
        if (commaIndex > 0)
            cnPart = cnPart[..commaIndex];
        return cnPart.Trim();
    }

    private List<UserInfo> ConvertDataTableToUserInfoList(DataTable dt)
    {
        var list = new List<UserInfo>();
        bool isComputerTable = dt.Columns.Contains("Имя") && !dt.Columns.Contains("Логин");
        
        foreach (DataRow row in dt.Rows)
        {
            var isSUMD = dt.Columns.Contains("СУМД") && row["СУМД"] != DBNull.Value && Convert.ToBoolean(row["СУМД"]);
            var statusUZ = dt.Columns.Contains("Статус УЗ") ? row["Статус УЗ"]?.ToString() ?? "" : "";

            list.Add(new UserInfo
            {
                Login = isComputerTable 
                    ? (dt.Columns.Contains("Имя") ? row["Имя"]?.ToString() ?? "" : "") 
                    : (dt.Columns.Contains("Логин") ? row["Логин"]?.ToString() ?? "" : ""),
                FIO = dt.Columns.Contains("Вывод. имя") ? row["Вывод. имя"]?.ToString() ?? "" : "",
                DisplayName = dt.Columns.Contains("Вывод. имя") ? row["Вывод. имя"]?.ToString() ?? "" : (dt.Columns.Contains("Имя") ? row["Имя"]?.ToString() ?? "" : ""),
                Email = dt.Columns.Contains("Почта") ? row["Почта"]?.ToString() ?? "" : "",
                Department = dt.Columns.Contains("Департамент") ? row["Департамент"]?.ToString() ?? "" : "",
                Company = dt.Columns.Contains("Компания") ? row["Компания"]?.ToString() ?? "" : "",
                Phone = dt.Columns.Contains("Телефон") ? row["Телефон"]?.ToString() ?? "" : "",
                MobilePhone = dt.Columns.Contains("Моб. телефон") ? row["Моб. телефон"]?.ToString() ?? "" : "",
                Description = dt.Columns.Contains("Описание") ? row["Описание"]?.ToString() ?? "" : "",
                Title = dt.Columns.Contains("Должность") ? row["Должность"]?.ToString() ?? "" : "",
                DN = dt.Columns.Contains("distinguishedName") ? row["distinguishedName"]?.ToString() ?? "" : "",
                Manager = dt.Columns.Contains("manager") ? row["manager"]?.ToString() ?? "" : "",
                Owner = (dt.Columns.Contains("Владелец") ? row["Владелец"]?.ToString() : null) 
                       ?? (dt.Columns.Contains("Владелец ящика") ? row["Владелец ящика"]?.ToString() : null) 
                       ?? "",
                EximMembers = dt.Columns.Contains("Члены рассылки Exim") ? row["Члены рассылки Exim"]?.ToString() ?? ""
                    : (dt.Columns.Contains("Члены ящика Exim") ? row["Члены ящика Exim"]?.ToString() ?? "" : ""),
                ExchangeMembers = dt.Columns.Contains("Члены ящика Exchange") ? row["Члены ящика Exchange"]?.ToString() ?? "" : "",
                MailHost = dt.Columns.Contains("Почтовый сервер") ? row["Почтовый сервер"]?.ToString() ?? "" : "",
                MailBoxLocation = dt.Columns.Contains("Расположение ящика") ? row["Расположение ящика"]?.ToString() ?? "" : "",
                Database = dt.Columns.Contains("Квота ящика") ? row["Квота ящика"]?.ToString() ?? "" : "",
                MigrateStatus = dt.Columns.Contains("Статус миграции в Exchange") ? row["Статус миграции в Exchange"]?.ToString() ?? "" : "",
                StatusUZ = statusUZ,
                StatusSMD = isSUMD ? "СУМД - Присутствует" : "СУМД - Отсутствует",
                IsSUMD = isSUMD,
                IsDisabled = statusUZ.StartsWith("DISABLE"),
                QuotaMailBox = dt.Columns.Contains("Квота ящика") ? row["Квота ящика"]?.ToString() ?? "" : "",
                Photo = dt.Columns.Contains("Photo") && row["Photo"] != DBNull.Value ? row["Photo"] as byte[] : null
            });
        }
        return list;
    }

    private UserMoreInfo? ConvertDataRowToUserMoreInfo(DataRow row)
    {
        return new UserMoreInfo
        {
            Login = row["Логин"]?.ToString() ?? "",
            FullName = row["ФИО"]?.ToString() ?? "",
            DisplayName = row["Вывод. имя"]?.ToString() ?? "",
            Email = row["Почта"]?.ToString() ?? "",
            Department = row["Отдел"]?.ToString() ?? "",
            Company = row["Компания"]?.ToString() ?? "",
            JobTitle = row["Должность"]?.ToString() ?? "",
            Phone = row["Телефон"]?.ToString() ?? "",
            MobilePhone = row["Моб. телефон"]?.ToString() ?? "",
            Manager = row["manager"]?.ToString() ?? "",
            DN = row["LDAP путь"]?.ToString() ?? "",
            AccountStatus = row["Статус УЗ"]?.ToString() ?? "",
            ExchangeMigrationStatus = row["Exchange - статус миграции"]?.ToString() ?? ""
        };
    }

    public Task<DataTable> GetVladetelIsListByFIOAsync(DataTable fioDT, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            return _ad.GetVladetelIsListByFIO(fioDT);
        }, cancellationToken);
    }

    public Task<DataTable> SearchByAttributeAsync(string attributeName, string attributeValue, CancellationToken cancellationToken = default)
    {
        return Task.Run(() =>
        {
            var result = _ad.SearchByAttribute(attributeName, attributeValue, out var ex);
            if (ex != null)
            {
                result.ExtendedProperties["Error"] = ex.Message;
            }
            return result;
        }, cancellationToken);
    }

    public Task<List<string>> GetSchemaAttributesAsync(CancellationToken cancellationToken = default)
    {
        return Task.Run(() => _ad.GetSchemaAttributes(), cancellationToken);
    }

    public Task<ADOperationResult> ChangeUserPasswordAsync(string userDN, string newPassword, CancellationToken cancellationToken = default)
    {
        return Task.Run(() => _ad.ChangeUserPassword(userDN, newPassword), cancellationToken);
    }

    public Task<ADOperationResult> ForcePasswordChangeAtNextLogonAsync(string userDN, bool force, CancellationToken cancellationToken = default)
    {
        return Task.Run(() => _ad.ForcePasswordChangeAtNextLogon(userDN, force), cancellationToken);
    }

    public Task<ADOperationResult> UnlockAccountAsync(string userDN, CancellationToken cancellationToken = default)
    {
        return Task.Run(() => _ad.UnlockAccount(userDN), cancellationToken);
    }

    public Task<PasswordStatusInfo> GetPasswordStatusAsync(string userDN, CancellationToken cancellationToken = default)
    {
        return Task.Run(() => _ad.GetPasswordStatus(userDN), cancellationToken);
    }

    public Task<AccountLockStatusInfo> GetAccountLockStatusAsync(string userDN, CancellationToken cancellationToken = default)
    {
        return Task.Run(() => _ad.GetAccountLockStatus(userDN), cancellationToken);
    }
}
