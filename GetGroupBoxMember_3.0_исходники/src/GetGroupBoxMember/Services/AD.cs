using System;
using System.Collections.Generic;
using System.Data;
using System.DirectoryServices;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Xml;
using GetGroupBoxMember.Models;

namespace GetGroupBoxMember.Services;

public class AD
{
    [DllImport("netapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int DsGetDcName(
        [MarshalAs(UnmanagedType.LPWStr)] string computerName,
        [MarshalAs(UnmanagedType.LPWStr)] string domainName,
        IntPtr domainGuid,
        [MarshalAs(UnmanagedType.LPWStr)] string siteName,
        uint flags,
        out IntPtr domainControllerInfo);

    [DllImport("netapi32.dll", SetLastError = true)]
    private static extern int NetApiBufferFree(IntPtr buffer);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct DOMAIN_CONTROLLER_INFO
    {
        [MarshalAs(UnmanagedType.LPWStr)]
        public string DomainControllerName;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string DomainControllerAddress;
        public uint DomainControllerAddressType;
        public Guid DomainGuid;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string DomainName;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string DnsForestName;
        public uint Flags;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string DcSiteName;
        [MarshalAs(UnmanagedType.LPWStr)]
        public string ClientSiteName;
    }

    private const uint DS_GC_SERVER_REQUIRED = 0x00000004;
    private const uint DS_ONLY_LDAP_NEEDED = 0x00000020;
    private const uint DS_RETURN_DNS_NAME = 0x40000000;
    private const uint DS_AVOID_READONLY_SERVERS = 0x00004000;
    private const uint ERROR_SUCCESS = 0;

    private DirectoryEntry? _cachedRootEntry;
    private string? _cachedLdapPath;
    private readonly object _entryLock = new();
    private DateTime _lastSuccessfulConnection = DateTime.MinValue;
    private static readonly TimeSpan ConnectionHealthCheckInterval = TimeSpan.FromMinutes(5);
    public enum ConnectionResult
    {
        Unknown,
        Success,
        NoNetwork,
        NoAccessToServer,
        InvalidCredentials,
        ServerNotFound,
        Timeout,
        DnsResolutionFailed,
        PortBlocked,
        SslCertificateError,
        PartialSuccess
    }

    public class LdapConnectionInfo
    {
        public ConnectionResult Result { get; set; }
        public string StrategyUsed { get; set; } = string.Empty;
        public string ServerAttempted { get; set; } = string.Empty;
        public int PortAttempted { get; set; }
        public string ErrorMessage { get; set; } = string.Empty;
        public string SuggestedAction { get; set; } = string.Empty;
        public DateTime Timestamp { get; set; }
        public Exception? OriginalException { get; set; }

        public LdapConnectionInfo()
        {
            Timestamp = DateTime.Now;
        }

        public override string ToString()
        {
            return $"[{Timestamp:yyyy-MM-dd HH:mm:ss}] Strategy: {StrategyUsed}, Server: {ServerAttempted}:{PortAttempted}, Result: {Result}, Error: {ErrorMessage}";
        }
    }

    private enum ConnectionStrategy
    {
        RootDSE_AutoDiscovery,
        Direct_DC,
        GlobalCatalog,
        LDAPS_Port636,
        GC_Port3268
    }

    private static bool IsNetworkAvailable()
    {
        try
        {
            if (!NetworkInterface.GetIsNetworkAvailable())
                return false;

            if (string.IsNullOrWhiteSpace(Data.DC))
                return true;

            string dcHost = Data.DC.Split(':')[0];
            try
            {
                var hostEntry = Dns.GetHostEntry(dcHost);
                if (hostEntry.AddressList.Length == 0)
                    return false;
            }
            catch
            {
                return false;
            }

            return true;
        }
        catch
        {
            return false;
        }
    }

    private static bool CheckPortAvailability(string host, int port, int timeoutMs = 3000)
    {
        try
        {
            using var client = new System.Net.Sockets.TcpClient();
            var connectTask = client.ConnectAsync(host, port);
            if (!connectTask.Wait(timeoutMs))
                return false;
            return client.Connected;
        }
        catch
        {
            return false;
        }
    }

    private static string? GetOptimalDcFromWindows(string? domainName)
    {
        if (string.IsNullOrEmpty(domainName)) return null;
        
        IntPtr dcInfoPtr = IntPtr.Zero;
        try
        {
            int result = DsGetDcName(null, domainName, IntPtr.Zero, null, DS_RETURN_DNS_NAME | DS_GC_SERVER_REQUIRED | DS_AVOID_READONLY_SERVERS, out dcInfoPtr);
            if (result != ERROR_SUCCESS || dcInfoPtr == IntPtr.Zero)
                return null;

            DOMAIN_CONTROLLER_INFO dcInfo = Marshal.PtrToStructure<DOMAIN_CONTROLLER_INFO>(dcInfoPtr);
            if (string.IsNullOrEmpty(dcInfo.DomainControllerAddress))
                return null;

            string dcName = dcInfo.DomainControllerName ?? string.Empty;
            if (dcName.StartsWith("\\"))
                dcName = dcName.Substring(2);

            return dcName;
        }
        catch
        {
            return null;
        }
        finally
        {
            if (dcInfoPtr != IntPtr.Zero)
                NetApiBufferFree(dcInfoPtr);
        }
    }

    private static string? GetCurrentAdSite()
    {
        IntPtr dcInfoPtr = IntPtr.Zero;
        try
        {
            string? domainName = Data.AdPath_Domain;
            if (string.IsNullOrEmpty(domainName))
                return null;

            int result = DsGetDcName(null, domainName, IntPtr.Zero, null, DS_RETURN_DNS_NAME, out dcInfoPtr);
            if (result != ERROR_SUCCESS || dcInfoPtr == IntPtr.Zero)
                return null;

            DOMAIN_CONTROLLER_INFO dcInfo = Marshal.PtrToStructure<DOMAIN_CONTROLLER_INFO>(dcInfoPtr);
            return dcInfo.ClientSiteName;
        }
        catch
        {
            return null;
        }
        finally
        {
            if (dcInfoPtr != IntPtr.Zero)
                NetApiBufferFree(dcInfoPtr);
        }
    }

    private static bool PreCheckLdapPorts(string? dc, int timeoutMs = 2000)
    {
        if (string.IsNullOrEmpty(dc)) return false;
        
        string dcHost = dc.Split(':')[0];

        try
        {
            var hostEntry = Dns.GetHostEntry(dcHost);
            if (hostEntry.AddressList.Length == 0)
                return false;
        }
        catch
        {
            string[] dcParts = dcHost.Split('.');
            if (dcParts.Length > 0)
            {
                try
                {
                    var ipAddress = Dns.GetHostAddresses(dcHost);
                    if (ipAddress.Length == 0)
                        return false;
                }
                catch
                {
                    return false;
                }
            }
            else
            {
                return false;
            }
        }

        return true;
    }

    private static ConnectionResult MapExceptionToConnectionResult(Exception ex, out string suggestedAction)
    {
        suggestedAction = "Проверьте сетевое подключение и повторите попытку.";

        if (ex is DirectoryServicesCOMException dsEx)
        {
            int hResult = dsEx.ErrorCode;
            switch (hResult)
            {
                case -2147023167:
                case -2147022988:
                case -2147019886:
                    suggestedAction = "Не удается подключиться к контроллеру домена. Проверьте, что компьютер подключен к сети.";
                    return ConnectionResult.NoAccessToServer;
                case -2147023574:
                case -2147024891:
                    suggestedAction = "Отказано в доступе. Проверьте права текущего пользователя в Active Directory.";
                    return ConnectionResult.NoAccessToServer;
                case -2147024890:
                case -2147024893:
                    suggestedAction = "Учетные данные недействительны. Перезайдите в систему.";
                    return ConnectionResult.InvalidCredentials;
                case -2147012721:
                case -2146893023:
                    suggestedAction = "Ошибка SSL-сертификата. Обратитесь к администратору.";
                    return ConnectionResult.SslCertificateError;
                default:
                    if (hResult < 0)
                        suggestedAction = "Ошибка подключения к Active Directory. Код ошибки: " + hResult;
                    return ConnectionResult.Unknown;
            }
        }

        if (ex is COMException)
        {
            suggestedAction = "Контроллер домена недоступен. Проверьте сетевое подключение.";
            return ConnectionResult.ServerNotFound;
        }

        if (ex is System.Net.Sockets.SocketException sockEx)
        {
            switch (sockEx.SocketErrorCode)
            {
                case System.Net.Sockets.SocketError.TimedOut:
                    suggestedAction = "Превышен таймаут подключения. Проверьте сетевую связность.";
                    return ConnectionResult.Timeout;
                case System.Net.Sockets.SocketError.ConnectionRefused:
                    suggestedAction = "Порт заблокирован или служба не запущена на контроллере домена.";
                    return ConnectionResult.PortBlocked;
                case System.Net.Sockets.SocketError.HostUnreachable:
                case System.Net.Sockets.SocketError.NetworkUnreachable:
                    suggestedAction = "Сеть недоступна. Проверьте физическое подключение.";
                    return ConnectionResult.NoNetwork;
                default:
                    suggestedAction = "Сетевая ошибка: " + sockEx.Message;
                    return ConnectionResult.NoNetwork;
            }
        }

        if (ex is TimeoutException)
        {
            suggestedAction = "Превышен таймаут. Попробуйте подключиться позже или используйте VPN.";
            return ConnectionResult.Timeout;
        }

        if (ex is PlatformNotSupportedException)
        {
            suggestedAction = "Системная ошибка .NET Framework. Попробуйте переустановить компоненты.";
            return ConnectionResult.Unknown;
        }

        return ConnectionResult.Unknown;
    }

    private DirectoryEntry CreateEntryWithAuth(string path, AuthenticationTypes authType)
    {
        DirectoryEntry entry = new DirectoryEntry
        {
            Path = path,
            AuthenticationType = authType,
            UsePropertyCache = true,
            Username = null,
            Password = null
        };
        return entry;
    }

    private DirectoryEntry? TryConnectWithStrategy(ConnectionStrategy strategy, int timeoutMs, out LdapConnectionInfo info)
    {
        info = new LdapConnectionInfo
        {
            StrategyUsed = strategy.ToString() ?? string.Empty
        };

        string baseDN = Data.AdPath_Domain ?? "DC=corp,DC=tander,DC=ru";
        string dc = Data.DC ?? "localhost";

        string? path = null;
        AuthenticationTypes authType = AuthenticationTypes.Secure | AuthenticationTypes.Sealing | AuthenticationTypes.Signing;

        switch (strategy)
        {
            case ConnectionStrategy.RootDSE_AutoDiscovery:
                path = "LDAP://RootDSE";
                info.ServerAttempted = dc.Split(':')[0];
                info.PortAttempted = 389;
                break;

            case ConnectionStrategy.Direct_DC:
                path = $"LDAP://{dc}/{baseDN}";
                info.ServerAttempted = dc.Split(':')[0];
                info.PortAttempted = 389;
                break;

            case ConnectionStrategy.GlobalCatalog:
                path = $"GC://{dc.Split(':')[0]}:3268/{baseDN}";
                info.ServerAttempted = dc.Split(':')[0];
                info.PortAttempted = 3268;
                break;

            case ConnectionStrategy.LDAPS_Port636:
                path = $"LDAP://{dc}:636/{baseDN}";
                authType = AuthenticationTypes.SecureSocketsLayer | AuthenticationTypes.Secure | AuthenticationTypes.Signing | AuthenticationTypes.Sealing;
                info.ServerAttempted = dc.Split(':')[0];
                info.PortAttempted = 636;
                break;

            case ConnectionStrategy.GC_Port3268:
                path = $"LDAP://{dc}:3268/{baseDN}";
                info.ServerAttempted = dc.Split(':')[0];
                info.PortAttempted = 3268;
                break;
        }

        info.Result = ConnectionResult.Unknown;
        DirectoryEntry? entry = null;

        try
        {
            entry = CreateEntryWithAuth(path, authType);

            using DirectorySearcher searcher = new DirectorySearcher(entry)
            {
                ClientTimeout = TimeSpan.FromMilliseconds(timeoutMs),
                ServerTimeLimit = TimeSpan.FromMilliseconds(timeoutMs),
                Filter = "(objectClass=*)"
            };
            searcher.PropertiesToLoad.Add("defaultNamingContext");

            if (strategy == ConnectionStrategy.RootDSE_AutoDiscovery)
            {
                var result = searcher.FindOne();
                if (result != null && result.Properties["defaultNamingContext"].Count > 0)
                {
                    string namingContext = result.Properties["defaultNamingContext"][0]?.ToString() ?? string.Empty;
                    entry.Dispose();
                    info.Result = ConnectionResult.Success;
                    return CreateEntryWithAuth($"LDAP://{Data.DC}/{namingContext}", authType);
                }
                throw new InvalidOperationException("RootDSE не вернул defaultNamingContext");
            }

            searcher.FindOne();
            info.Result = ConnectionResult.Success;
            return entry;
        }
        catch (Exception ex)
        {
            info.OriginalException = ex;
            info.ErrorMessage = ex.Message;
            info.Result = MapExceptionToConnectionResult(ex, out string suggested);
            info.SuggestedAction = suggested;
            entry?.Dispose();
            return null;
        }
    }

    private DirectoryEntry? GetRootEntryOriginal(int timeoutMs = 30000)
    {
        string ldapPath = "LDAP://" + Data.DC + Data.AdPath_Domain;
        DirectoryEntry entry = new DirectoryEntry
        {
            Path = ldapPath,
            AuthenticationType = AuthenticationTypes.Secure,
            UsePropertyCache = true
        };

        try
        {
            using DirectorySearcher searcher = new DirectorySearcher(entry)
            {
                ClientTimeout = TimeSpan.FromMilliseconds(timeoutMs),
                ServerTimeLimit = TimeSpan.FromMilliseconds(timeoutMs),
                Filter = "(objectClass=*)",
                SearchScope = SearchScope.Base
            };
            searcher.PropertiesToLoad.Add("defaultNamingContext");
            searcher.FindOne();
            return entry;
        }
        catch
        {
            entry?.Dispose();
            throw;
        }
    }

    private DirectoryEntry? GetRootEntryWithRetry(out ConnectionResult result, out LdapConnectionInfo connectionInfo)
    {
        result = ConnectionResult.Unknown;
        connectionInfo = new LdapConnectionInfo();

        if (!IsNetworkAvailable())
        {
            result = ConnectionResult.NoNetwork;
            connectionInfo.Result = ConnectionResult.NoNetwork;
            connectionInfo.SuggestedAction = "Проверьте сетевое подключение и подключение к VPN.";
            return null;
        }

        var strategies = new[]
        {
            ConnectionStrategy.RootDSE_AutoDiscovery,
            ConnectionStrategy.Direct_DC,
            ConnectionStrategy.GlobalCatalog,
            ConnectionStrategy.LDAPS_Port636,
            ConnectionStrategy.GC_Port3268
        };

        int[] retryDelays = { 200, 500, 1000 };
        int timeoutPerAttempt = 10000;

        foreach (var strategy in strategies)
        {
            for (int attempt = 0; attempt <= 2; attempt++)
            {
                if (attempt > 0)
                {
                    Thread.Sleep(retryDelays[attempt - 1]);
                }

                DirectoryEntry? entry = TryConnectWithStrategy(strategy, timeoutPerAttempt, out connectionInfo);

                if (connectionInfo.Result == ConnectionResult.Success && entry != null)
                {
                    result = ConnectionResult.Success;
                    return entry;
                }

                if (connectionInfo.Result == ConnectionResult.InvalidCredentials ||
                    connectionInfo.Result == ConnectionResult.SslCertificateError)
                {
                    continue;
                }
            }
        }

        result = connectionInfo.Result;
        return null;
    }

    public void ResetConnectionCache()
    {
        lock (_entryLock)
        {
            _cachedRootEntry?.Dispose();
            _cachedRootEntry = null;
            _cachedLdapPath = null;
            _lastSuccessfulConnection = DateTime.MinValue;
        }
    }

    public void RefreshConnection(out ConnectionResult result, out string errorDetails)
    {
        ResetConnectionCache();
        result = ConnectionResult.Unknown;
        errorDetails = string.Empty;

        DirectoryEntry? entry = GetRootEntryWithRetry(out result, out var info);
        if (entry == null)
        {
            errorDetails = $"Не удалось подключиться к Active Directory.\n\n" +
                          $"Стратегия: {info.StrategyUsed}\n" +
                          $"Сервер: {info.ServerAttempted}:{info.PortAttempted}\n" +
                          $"Ошибка: {info.ErrorMessage}\n\n" +
                          $"Рекомендация: {info.SuggestedAction}";
            throw new InvalidOperationException(errorDetails);
        }
        else
        {
            entry.Dispose();
        }
    }

    private bool IsConnectionStale()
    {
        return DateTime.Now - _lastSuccessfulConnection > ConnectionHealthCheckInterval;
    }

    private void UpdateLastSuccessfulConnection()
    {
        _lastSuccessfulConnection = DateTime.Now;
    }

    [Flags]
    private enum AdsUserFlags
    {
        Script = 1,
        AccountDisabled = 2,
        HomeDirectoryRequired = 8,
        AccountLockedOut = 0x10,
        PasswordNotRequired = 0x20,
        PasswordCannotChange = 0x40,
        EncryptedTextPasswordAllowed = 0x80,
        TempDuplicateAccount = 0x100,
        NormalAccount = 0x200,
        InterDomainTrustAccount = 0x800,
        WorkstationTrustAccount = 0x1000,
        ServerTrustAccount = 0x2000,
        PasswordDoesNotExpire = 0x10000,
        MnsLogonAccount = 0x20000,
        SmartCardRequired = 0x40000,
        TrustedForDelegation = 0x80000,
        AccountNotDelegated = 0x100000,
        UseDesKeyOnly = 0x200000,
        DontRequirePreauth = 0x400000,
        PasswordExpired = 0x800000,
        TrustedToAuthenticateForDelegation = 0x1000000,
        NoAuthDataRequired = 0x2000000
    }

    [Flags]
    private enum AdsGroupFlags : long
    {
        SystemGroup = 1L,
        Global = 2L,
        DomainLocal = 4L,
        Universal = 8L,
        APP_BASIC = 0x10L,
        APP_QUERY = 0x20L,
        SecurityGroup = 0x80000000L
    }

    private readonly char[] _ldapFilterEscapeSequence = new char[5] { '\\', '(', ')', '\0', '/' };
    private readonly string[] _ldapFilterEscapeSequenceCharacter = new string[5] { "\\5c", "\\28", "\\29", "\\00", "\\2f" };

    private static string EscapeDnForLdapFilter(string dn)
    {
        if (string.IsNullOrEmpty(dn))
            return dn;
        return dn.Replace("\\", "\\5c").Replace(",", "\\,").Replace("=", "\\=");
    }

    private DirectoryEntry? GetRootEntry()
    {
        string dc = Data.DC ?? "localhost";
        string baseDN = Data.AdPath_Domain ?? "DC=corp,DC=tander,DC=ru";
        string ldapPath = "LDAP://" + dc + baseDN;

        lock (_entryLock)
        {
            if (_cachedRootEntry != null && _cachedLdapPath == ldapPath && !IsConnectionStale())
            {
                return _cachedRootEntry;
            }

            if (_cachedRootEntry != null && _cachedLdapPath != ldapPath)
            {
                _cachedRootEntry?.Dispose();
                _cachedRootEntry = null;
            }
        }

        DirectoryEntry? newEntry = null;
        string? lastError = null;
        ConnectionResult retryResult = ConnectionResult.Unknown;
        LdapConnectionInfo? retryInfo = null;

        if (PreCheckLdapPorts(dc))
        {
            try
            {
                newEntry = GetRootEntryOriginal(30000);
            }
            catch (Exception ex)
            {
                lastError = ex.Message;
            }
        }

        if (newEntry == null)
        {
            string? domainName = ExtractDomainFromBaseDn(baseDN);
            if (!string.IsNullOrEmpty(domainName))
            {
                string? optimalDc = GetOptimalDcFromWindows(domainName);
                if (!string.IsNullOrEmpty(optimalDc) && optimalDc != dc)
                {
                    string newLdapPath = "LDAP://" + optimalDc + baseDN;
                    try
                    {
                        DirectoryEntry testEntry = CreateEntrySimple(newLdapPath, 20000);
                        using DirectorySearcher searcher = new DirectorySearcher(testEntry)
                        {
                            ClientTimeout = TimeSpan.FromMilliseconds(20000),
                            ServerTimeLimit = TimeSpan.FromMilliseconds(20000),
                            Filter = "(objectClass=*)",
                            SearchScope = SearchScope.Base
                        };
                        searcher.PropertiesToLoad.Add("defaultNamingContext");
                        searcher.FindOne();
                        testEntry.Dispose();

                        newEntry = CreateEntrySimple(newLdapPath, 30000);
                    }
                    catch (Exception ex)
                    {
                        lastError = ex.Message;
                    }
                }
            }
        }

        if (newEntry == null)
        {
            newEntry = GetRootEntryWithRetry(out retryResult, out retryInfo);
        }

        if (newEntry == null)
        {
            string finalError = $"Не удалось подключиться к Active Directory.\n\n" +
                               $"Попробованы методы:\n" +
                               $"1. Подключение к {dc} (основной)\n" +
                               $"2. Поиск оптимального DC через Windows API\n" +
                               $"3. Альтернативные стратегии\n\n" +
                               $"Последняя ошибка: {lastError ?? retryInfo?.ErrorMessage ?? "неизвестно"}\n\n" +
                               $"Рекомендация: {retryInfo?.SuggestedAction ?? "Проверьте сетевое подключение и подключение к VPN."}";

            throw new InvalidOperationException(finalError);
        }

        lock (_entryLock)
        {
            _cachedRootEntry?.Dispose();
            _cachedRootEntry = newEntry;
            _cachedLdapPath = ldapPath;
            UpdateLastSuccessfulConnection();
            return _cachedRootEntry;
        }
    }

    private static string? ExtractDomainFromBaseDn(string? baseDn)
    {
        if (string.IsNullOrEmpty(baseDn))
            return null;

        var parts = baseDn.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);
        var dcParts = parts
            .Where(p => p.StartsWith("DC=", StringComparison.OrdinalIgnoreCase))
            .Select(p => p.Length > 3 ? p.Substring(3) : string.Empty)
            .ToArray();

        if (dcParts.Length > 0)
            return string.Join(".", dcParts);

        return null;
    }

    private DirectoryEntry CreateEntrySimple(string path, int timeoutMs)
    {
        DirectoryEntry entry = new DirectoryEntry
        {
            Path = path,
            AuthenticationType = AuthenticationTypes.Secure,
            UsePropertyCache = true
        };
        return entry;
    }

    public void RefreshConnection()
    {
        if (!Monitor.TryEnter(_entryLock, TimeSpan.FromSeconds(30)))
        {
            throw new TimeoutException("Timeout acquiring AD connection lock");
        }
        try
        {
            _cachedRootEntry?.Dispose();
            _cachedRootEntry = null;
            _cachedLdapPath = null;
            _lastSuccessfulConnection = DateTime.MinValue;
        }
        finally
        {
            Monitor.Exit(_entryLock);
        }
    }

    public bool TestConnection()
    {
        try
        {
            DirectoryEntry? entry = GetRootEntryWithRetry(out ConnectionResult result, out LdapConnectionInfo info);
            if (result == ConnectionResult.Success)
            {
                UpdateLastSuccessfulConnection();
                return true;
            }
            RefreshConnection();
            return false;
        }
        catch
        {
            RefreshConnection();
            return false;
        }
    }

    private const int DefaultSearchTimeout = 30000;
    private const int DefaultClientTimeout = 30000;

    private DirectorySearcher CreateSearcher()
    {
        DirectoryEntry? entry = GetRootEntry();
        DirectorySearcher searcher = new DirectorySearcher(entry)
        {
            ClientTimeout = TimeSpan.FromMilliseconds(DefaultClientTimeout),
            ServerTimeLimit = TimeSpan.FromMilliseconds(DefaultSearchTimeout),
            ReferralChasing = ReferralChasingOption.None
        };
        return searcher;
    }

    private DirectorySearcher CreateSearcherWithTimeout(int timeoutMs = DefaultSearchTimeout)
    {
        DirectoryEntry? entry = GetRootEntry();
        DirectorySearcher searcher = new DirectorySearcher(entry)
        {
            ClientTimeout = TimeSpan.FromMilliseconds(timeoutMs),
            ServerTimeLimit = TimeSpan.FromMilliseconds(timeoutMs),
            ReferralChasing = ReferralChasingOption.None
        };
        return searcher;
    }

    public string CanonicalizeStringForLdapFilter(string userInput)
    {
        if (string.IsNullOrEmpty(userInput))
        {
            return userInput;
        }
        string text = (string)userInput.Clone();
        for (int i = 0; i < _ldapFilterEscapeSequence.Length; i++)
        {
            int num = text.IndexOf(_ldapFilterEscapeSequence[i]);
            if (num != -1)
            {
                text = text.Replace(new string(_ldapFilterEscapeSequence[i], 1), _ldapFilterEscapeSequenceCharacter[i]);
            }
        }
        return text;
    }

    public string NormalizeMobilePhone(string phone)
    {
        if (string.IsNullOrWhiteSpace(phone))
        {
            return string.Empty;
        }
        string digits = new string(phone.Where(char.IsDigit).ToArray());
        if (digits.Length == 10)
        {
            return $"+7{digits}";
        }
        if (digits.Length == 11)
        {
            if (digits.StartsWith("7"))
            {
                return $"+{digits}";
            }
            if (digits.StartsWith("8"))
            {
                return $"+7{digits.Substring(1)}";
            }
        }
        if (digits.Length > 0)
        {
            return $"+7{digits.Substring(Math.Max(0, digits.Length - 10))}";
        }
        return string.Empty;
    }

    // NOTE: Due to file size, the rest of AD.cs methods will be added in subsequent batches.
    // Key methods remaining:
    // - GetObjectInfo_WithDistinguishedName
    // - GetUserInfo
    // - GetGroupInfo
    // - GetMaillistInfo
    // - GetComputerInfo
    // - GetRepadminInfoAttributeMetaData
    // - GetRepadminInfoValueMetaData
    // - And many more...

    public static string GetDaysWord(int days)
    {
        int absDays = Math.Abs(days);
        int lastTwo = absDays % 100;
        if (lastTwo >= 11 && lastTwo <= 14)
            return "дней";
        int lastOne = absDays % 10;
        if (lastOne == 1)
            return "день";
        if (lastOne >= 2 && lastOne <= 4)
            return "дня";
        return "дней";
    }

    public static string GetHoursWord(int hours)
    {
        int lastTwo = hours % 100;
        if (lastTwo >= 11 && lastTwo <= 14)
            return "часов";
        int lastOne = hours % 10;
        if (lastOne == 1)
            return "час";
        if (lastOne >= 2 && lastOne <= 4)
            return "часа";
        return "часов";
    }

    public static string GetMinutesWord(int minutes)
    {
        int lastTwo = minutes % 100;
        if (lastTwo >= 11 && lastTwo <= 14)
            return "минут";
        int lastOne = minutes % 10;
        if (lastOne == 1)
            return "минута";
        if (lastOne >= 2 && lastOne <= 4)
            return "минуты";
        return "минут";
    }

    private static DateTime? SafeFromFileTimeUtc(long filetime)
    {
        try
        {
            if (filetime <= 0 || filetime >= long.MaxValue)
                return null;
            if (filetime < 116444736000000000L)
                return null;
            return DateTime.FromFileTimeUtc(filetime);
        }
        catch
        {
            return null;
        }
    }

    private static DateTime? SafeFromFileTime(long filetime)
    {
        try
        {
            if (filetime <= 0 || filetime >= long.MaxValue)
                return null;
            if (filetime < 116444736000000000L)
                return null;
            return DateTime.FromFileTime(filetime);
        }
        catch
        {
            return null;
        }
    }

    private string LdapSearch(string query, string type)
    {
        return type switch
        {
            "guid1C" => $"(guid1C={query}*)",
            "login" => $"(sAMAccountName={query}*)",
            "mail" => $"(mail={query}*)",
            "FIO" => $"(&(sn=*{query}*)(givenName=*{query}*))",
            "displayName" => $"(displayName=*{query}*)",
            "cn" => $"(cn={query}*)",
            "guidMD" => $"(guidMD={query}*)",
            "mobilepers" => $"(mobilepers=*{query}*)",
            _ => $"(sAMAccountName={query}*)"
        };
    }

    private string EscapeLdapDnValue(string dn)
    {
        if (string.IsNullOrEmpty(dn)) return dn;
        var sb = new System.Text.StringBuilder(dn.Length + 10);
        foreach (char c in dn)
        {
            switch (c)
            {
                case '\\': sb.Append("\\5c"); break;
                case ',': sb.Append("\\,"); break;
                case '+': sb.Append("\\+"); break;
                case '"': sb.Append("\\\""); break;
                case '<': sb.Append("\\<"); break;
                case '>': sb.Append("\\>"); break;
                case ';': sb.Append("\\;"); break;
                case '=': sb.Append("\\="); break;
                default: sb.Append(c); break;
            }
        }
        return sb.ToString();
    }

    private string EscapeLdapFilterValue(string value)
    {
        if (string.IsNullOrEmpty(value)) return value;
        var sb = new System.Text.StringBuilder(value.Length + 10);
        foreach (char c in value)
        {
            switch (c)
            {
                case '\\': sb.Append("\\5c"); break;
                case '*': sb.Append("\\2a"); break;
                case '(': sb.Append("\\28"); break;
                case ')': sb.Append("\\29"); break;
                case '\0': sb.Append("\\00"); break;
                default: sb.Append(c); break;
            }
        }
        return sb.ToString();
    }

    public DataTable SearchByAttribute(string attributeName, string attributeValue, out Exception? ex)
    {
        ex = null;
        var dt = new DataTable();
        dt.Columns.Add("Имя");
        dt.Columns.Add("Логин");
        dt.Columns.Add("Почта");
        dt.Columns.Add("Описание");
        dt.Columns.Add("DN");

        try
        {
            if (string.IsNullOrWhiteSpace(attributeName))
            {
                ex = new ArgumentException("Имя атрибута не указано");
                return dt;
            }

            string safeAttr = new string(attributeName.Where(c => char.IsLetterOrDigit(c) || c == '-' || c == '_').ToArray());
            if (string.IsNullOrEmpty(safeAttr) || safeAttr != attributeName)
            {
                ex = new ArgumentException("Имя атрибута содержит недопустимые символы. Допускаются только буквы, цифры, дефис и подчёркивание.");
                return dt;
            }

            string escapedValue = EscapeLdapFilterValue(attributeValue ?? "");
            string filter = $"({safeAttr}={escapedValue}*)";

            using var searcher = CreateSearcherWithTimeout(30000);
            searcher.Filter = filter;
            searcher.SearchScope = SearchScope.Subtree;
            searcher.PageSize = 1000;
            searcher.SizeLimit = 0;
            searcher.PropertiesToLoad.AddRange(new[] { "name", "sAMAccountName", "mail", "description", "distinguishedName" });

            using var results = searcher.FindAll();
            foreach (SearchResult result in results)
            {
                string GetProp(string name)
                {
                    return result.Properties[name]?.Count > 0 ? result.Properties[name][0]?.ToString() ?? "" : "";
                }
                dt.Rows.Add(GetProp("name"), GetProp("sAMAccountName"), GetProp("mail"), GetProp("description"), GetProp("distinguishedName"));
            }
        }
        catch (Exception e)
        {
            ex = e;
        }

        return dt;
    }

    public List<string> GetSchemaAttributes()
    {
        var result = new List<string>();
        try
        {
            using var root = GetRootEntry();
            string? schemaNC = null;
            try
            {
                var schemaProp = root.Properties["schemaNamingContext"];
                if (schemaProp?.Count > 0)
                    schemaNC = schemaProp[0]?.ToString();
            }
            catch { }

            if (string.IsNullOrEmpty(schemaNC))
            {
                using var rootDse = new DirectoryEntry("LDAP://RootDSE");
                var prop = rootDse.Properties["schemaNamingContext"];
                if (prop?.Count > 0)
                    schemaNC = prop[0]?.ToString();
            }

            if (string.IsNullOrEmpty(schemaNC))
                return result;

            using var schemaEntry = new DirectoryEntry($"LDAP://{schemaNC}");
            using var searcher = new DirectorySearcher(schemaEntry)
            {
                Filter = "(objectClass=attributeSchema)",
                SearchScope = SearchScope.Subtree,
                PageSize = 1000,
                SizeLimit = 0
            };
            searcher.PropertiesToLoad.Add("lDAPDisplayName");
            using var results = searcher.FindAll();
            foreach (SearchResult sr in results)
            {
                if (sr.Properties["lDAPDisplayName"]?.Count > 0)
                {
                    var name = sr.Properties["lDAPDisplayName"][0]?.ToString();
                    if (!string.IsNullOrEmpty(name))
                        result.Add(name);
                }
            }
            result.Sort(StringComparer.OrdinalIgnoreCase);
        }
        catch { }
        return result;
    }

    private static string GetCnFromDistinguishedName(string dn)
    {
        if (string.IsNullOrEmpty(dn)) return dn;
        var prefix = "CN=";
        var idx = dn.IndexOf(prefix, StringComparison.OrdinalIgnoreCase);
        if (idx == -1) return dn;
        var start = idx + prefix.Length;
        var comma = dn.IndexOf(',', start);
        return comma == -1 ? dn.Substring(start) : dn.Substring(start, comma - start);
    }

    private string GetWhileListExim(string mail)
    {
        string path = "LDAP://" + Data.DC + Data.AdPath_Domain;
        string result = string.Empty;
        try
        {
            using DirectoryEntry searchRoot = new DirectoryEntry(path);
            using DirectorySearcher directorySearcher = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(|(objectClass=group)(objectClass=msExchDynamicDistributionList))(mail={mail}))"
            };
            directorySearcher.PropertiesToLoad.Add("authOrig");
            SearchResult? searchResult = directorySearcher.FindOne();
            if (searchResult != null && searchResult.Properties["authOrig"].Count > 0)
            {
                foreach (object item in searchResult.Properties["authOrig"])
                {
                    result += item.ToString() + "|";
                }
                result = result.TrimEnd('|');
            }
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException("Ошибка получения белого списка!", ex);
        }
        return result;
    }

    public DataTable GetUserInfo(string inParm, string type)
    {
        DataTable dataTable = new DataTable();
        inParm = CanonicalizeStringForLdapFilter(inParm);
        string filter = LdapSearch(inParm, type);
        try
        {
            string[] props = new string[30]
            {
                "guidMD", "sAMAccountName", "displayName", "distinguishedName", "description", "mail", "createTimeStamp", "extensionAttribute10", "eximMailhost", "telephoneNumber",
                "eximAdminDescription", "eximFullControlMember", "msExchDelegateListLink", "info", "userAccountControl", "cn", "company", "extensionAttribute4", "homeMDB", "mobilepers", "manager", "thumbnailPhoto", "extensionAttribute8", "msDS-UserPasswordExpiryTimeComputed", "accountExpires", "pwdLastSet", "LockedOut", "proxyAddresses", "title", "department"
            };

            using DirectorySearcher directorySearcher = CreateSearcher();
            directorySearcher.SearchScope = SearchScope.Subtree;
            directorySearcher.Filter = $"(&(objectClass=user)(objectCategory=user){filter})";
            directorySearcher.PageSize = 51;
            directorySearcher.SizeLimit = 50;
            directorySearcher.PropertiesToLoad.AddRange(props);

            using SearchResultCollection results = directorySearcher.FindAll();

            dataTable.Columns.Add("Логин");
            dataTable.Columns.Add("СУМД", typeof(bool));
            dataTable.Columns.Add("distinguishedName");
            dataTable.Columns.Add("Вывод. имя");
            dataTable.Columns.Add("Описание");
            dataTable.Columns.Add("Департамент");
            dataTable.Columns.Add("Компания");
            dataTable.Columns.Add("Должность");
            dataTable.Columns.Add("Отдел");
            dataTable.Columns.Add("Телефон");
            dataTable.Columns.Add("Моб. телефон");
            dataTable.Columns.Add("Владелец ящика");
            dataTable.Columns.Add("Члены ящика Exim");
            dataTable.Columns.Add("Члены ящика Exchange");
            dataTable.Columns.Add("Почта");
            dataTable.Columns.Add("Почтовый сервер");
            dataTable.Columns.Add("Расположение ящика");
            dataTable.Columns.Add("Квота ящика");
            dataTable.Columns.Add("Статус миграции в Exchange");
            dataTable.Columns.Add("Создана");
            dataTable.Columns.Add("Статус УЗ");
            dataTable.Columns.Add("manager");
            dataTable.Columns.Add("Photo", typeof(byte[]));

            foreach (SearchResult sr in results)
            {
                DataRow row = dataTable.NewRow();
                row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["Владелец ящика"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                row["СУМД"] = sr.Properties["guidMD"].Count > 0;
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Телефон"] = sr.Properties["telephoneNumber"].Count > 0 ? sr.Properties["telephoneNumber"][0]?.ToString() ?? "" : "";
                row["Моб. телефон"] = sr.Properties["mobilepers"].Count > 0 ? sr.Properties["mobilepers"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Департамент"] = sr.Properties["extensionAttribute4"].Count > 0 ? sr.Properties["extensionAttribute4"][0]?.ToString() ?? "" : "";
                row["Компания"] = sr.Properties["company"].Count > 0 ? sr.Properties["company"][0]?.ToString() ?? "" : "";
                row["Должность"] = sr.Properties["title"].Count > 0 ? sr.Properties["title"][0]?.ToString() ?? "" : "";
                row["Отдел"] = sr.Properties["department"].Count > 0 ? sr.Properties["department"][0]?.ToString() ?? "" : "";

                string eximMembers = "";
                if (sr.Properties["eximFullControlMember"].Count > 0)
                {
                    foreach (object item in sr.Properties["eximFullControlMember"])
                    {
                        string itemStr = item?.ToString() ?? "";
                        if (!itemStr.Contains("svc_eximmigrate", StringComparison.OrdinalIgnoreCase) && !itemStr.Contains("cn=deleted objects,", StringComparison.OrdinalIgnoreCase))
                        {
                            eximMembers += itemStr + ";";
                        }
                    }
                }
                row["Члены ящика Exim"] = eximMembers.TrimEnd(';');

                string exchnageMembers = "";
                if (sr.Properties["msExchDelegateListLink"].Count > 0)
                {
                    foreach (object item in sr.Properties["msExchDelegateListLink"])
                    {
                        string itemStr = item?.ToString() ?? "";
                        if (!itemStr.Contains("svc_eximmigrate", StringComparison.OrdinalIgnoreCase) && !itemStr.Contains("cn=deleted objects,", StringComparison.OrdinalIgnoreCase))
                        {
                            exchnageMembers += itemStr + ";";
                        }
                    }
                }
                row["Члены ящика Exchange"] = exchnageMembers.TrimEnd(';');

                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Почтовый сервер"] = sr.Properties["eximMailhost"].Count > 0 ? sr.Properties["eximMailhost"][0]?.ToString() ?? "" : "";

                string locationValue;
                if (sr.Properties["homeMDB"].Count > 0)
                {
                    locationValue = "Exchange";
                }
                else
                {
                    bool hasSmtpInProxy = false;
                    if (sr.Properties["proxyAddresses"].Count > 0)
                    {
                        foreach (object proxy in sr.Properties["proxyAddresses"])
                        {
                            var proxyStr = proxy?.ToString() ?? "";
                            if (proxyStr.StartsWith("SMTP:", StringComparison.OrdinalIgnoreCase))
                            {
                                hasSmtpInProxy = true;
                                break;
                            }
                        }
                    }
                    locationValue = hasSmtpInProxy ? "Exim" : "Нет признаков п/я";
                }
                row["Расположение ящика"] = locationValue;

                if (sr.Properties["homeMDB"].Count > 0)
                {
                    string homeMDB = sr.Properties["homeMDB"][0]?.ToString() ?? "";
                    int cnIndex = homeMDB.IndexOf("CN=", StringComparison.Ordinal);
                    string quotaValue = "";
                    if (cnIndex >= 0)
                    {
                        string afterCN = homeMDB.Substring(cnIndex + 3);
                        int commaIndex = afterCN.IndexOf(",");
                        quotaValue = commaIndex > 0 ? afterCN.Substring(0, commaIndex) : afterCN;
                    }
                    row["Квота ящика"] = quotaValue;
                }

                row["Статус миграции в Exchange"] = sr.Properties["extensionAttribute10"].Count > 0 ? sr.Properties["extensionAttribute10"][0]?.ToString() ?? "" : "";
                row["Создана"] = sr.Properties["createTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["createTimeStamp"][0]).ToLocalTime().ToString() : "";

                int uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
                string owner = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString() ?? "" : "";
                bool isSharedMailbox = !string.IsNullOrWhiteSpace(owner);
                string hrStatus = sr.Properties["extensionAttribute8"].Count > 0 ? sr.Properties["extensionAttribute8"][0]?.ToString() ?? "" : "";

                string passwordDaysStr = "";
                if (!isSharedMailbox && sr.Properties["msDS-UserPasswordExpiryTimeComputed"].Count > 0)
                {
                    long expiryTime = Convert.ToInt64(sr.Properties["msDS-UserPasswordExpiryTimeComputed"][0]?.ToString() ?? "0");
                    if (expiryTime == 0)
                        passwordDaysStr = "Пароль - требует смены";
                    else if (expiryTime == -1)
                        passwordDaysStr = "Пароль - не установлен";
                    else
                    {
                        var expiryDate = SafeFromFileTimeUtc(expiryTime)?.ToLocalTime();
                        if (expiryDate.HasValue)
                        {
                            var timeLeft = expiryDate.Value - DateTime.Now;
                            if (timeLeft.TotalMilliseconds < 0)
                                passwordDaysStr = "Пароль истёк!";
                            else if (timeLeft.TotalDays < 1)
                            {
                                int hours = (int)timeLeft.TotalHours;
                                int minutes = timeLeft.Minutes;
                                if (hours == 0 && minutes > 0)
                                    passwordDaysStr = $"Пароль - осталось {minutes} {GetMinutesWord(minutes)}";
                                else if (minutes == 0 && hours > 0)
                                    passwordDaysStr = $"Пароль - осталось {hours} {GetHoursWord(hours)}";
                                else if (hours > 0 && minutes > 0)
                                    passwordDaysStr = $"Пароль - осталось {hours} {GetHoursWord(hours)} {minutes} {GetMinutesWord(minutes)}";
                                else
                                    passwordDaysStr = "Пароль истекает сегодня";
                            }
                            else
                            {
                                int daysUntil = (int)timeLeft.TotalDays;
                                passwordDaysStr = $"Пароль - осталось {daysUntil} {GetDaysWord(daysUntil)}";
                            }
                        }
                        else
                            passwordDaysStr = "N/D";
                    }
                }

                string lockedStr = "Блок по паролю: нет";
                if (!isSharedMailbox && sr.Properties["LockedOut"].Count > 0 && Convert.ToBoolean(sr.Properties["LockedOut"][0]))
                    lockedStr = "Блок по паролю: да";

                string hrStatusStr = !string.IsNullOrWhiteSpace(hrStatus) ? $"HR статус - {hrStatus}" : "HR статус - Работает";
                string expiredStr = "";
                if (!isSharedMailbox && sr.Properties["accountExpires"].Count > 0)
                {
                    long accountExp = Convert.ToInt64(sr.Properties["accountExpires"][0]?.ToString() ?? "0");
                    var accountExpDate = SafeFromFileTimeUtc(accountExp);
                    if (accountExpDate.HasValue && accountExpDate.Value < DateTime.Now)
                        expiredStr = "Срок действия УЗ истёк!";
                }

                if (isSharedMailbox)
                {
                    row["Статус УЗ"] = (uac & 2) != 0 ? "DISABLE" : "NORMAL";
                }
                else if ((uac & 2) != 0)
                    row["Статус УЗ"] = $"DISABLE, {hrStatusStr}{(expiredStr.Length > 0 ? ", " + expiredStr : "")}";
                else
                    row["Статус УЗ"] = string.Join(", ", new[] { "NORMAL", hrStatusStr, passwordDaysStr, lockedStr });

                row["manager"] = sr.Properties["manager"].Count > 0 ? sr.Properties["manager"][0]?.ToString() ?? "" : "";

                if (sr.Properties["thumbnailPhoto"].Count > 0)
                    row["Photo"] = sr.Properties["thumbnailPhoto"][0] as byte[];

                dataTable.Rows.Add(row);
            }
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException("Ошибка получения инфо о пользователе!", ex);
        }
        return dataTable;
    }

    public DataTable GetUserMoreInfo(string login, out Exception? error)
    {
        DataTable dataTable = new DataTable();
        error = null;
        login = CanonicalizeStringForLdapFilter(login);
        try
        {
            string[] props = new string[51]
            {
                "objectClass", "sAMAccountName", "sn", "givenName", "middleName", "displayName", "description", "mail", "title", "department",
                "company", "guid1C", "guidMD", "objectSid", "distinguishedName", "createTimeStamp", "modifyTimeStamp", "lastLogonTimestamp", "userAccountControl", "memberOf", "info",
                "pwdLastSet", "extensionAttribute10", "extensionAttribute14", "eximMaildir", "telephoneNumber", "eximMailhost", "eximAdminDescription", "mDBUseDefaults", "mDBStorageQuota",
                "mDBOverQuotaLimit", "mDBOverHardQuotaLimit", "cn", "msExchHideFromAddressLists", "eximCanReceiveFromAlien", "eximCanSendToAlien", "eximRecipientType", "msDS-UserPasswordExpiryTimeComputed", "accountExpires", "extensionAttribute2",
                "extensionAttribute3", "extensionAttribute4", "extensionAttribute5", "extensionAttribute6", "extensionAttribute7", "extensionAttribute8", "extensionAttribute11", "homeMDB", "mobilepers", "manager", "thumbnailPhoto"
            };

            using DirectorySearcher ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=user)(|(sAMAccountName={login})(cn={login})))";
            ds.PageSize = 301;
            ds.SizeLimit = 300;
            ds.PropertiesToLoad.AddRange(props);

            dataTable.Columns.Add("Логин");
            dataTable.Columns.Add("Фамилия");
            dataTable.Columns.Add("Имя");
            dataTable.Columns.Add("Отчество");
            dataTable.Columns.Add("ФИО");
            dataTable.Columns.Add("Вывод. имя");
            dataTable.Columns.Add("Описание");
            dataTable.Columns.Add("Телефон");
            dataTable.Columns.Add("Моб. телефон");
            dataTable.Columns.Add("Владелец");
            dataTable.Columns.Add("Почта");
            dataTable.Columns.Add("Почтовый сервер");
            dataTable.Columns.Add("Почтовое хранилище");
            dataTable.Columns.Add("Расположение ящика");
            dataTable.Columns.Add("Руководитель");
            dataTable.Columns.Add("Должность");
            dataTable.Columns.Add("Отдел");
            dataTable.Columns.Add("Компания");
            dataTable.Columns.Add("guid1C");
            dataTable.Columns.Add("guidMD");
            dataTable.Columns.Add("SID");
            dataTable.Columns.Add("Т_Дирекция");
            dataTable.Columns.Add("Т_Департамент");
            dataTable.Columns.Add("Т_Управление/Функция");
            dataTable.Columns.Add("Т_Направление/Служба");
            dataTable.Columns.Add("Т_Отдел");
            dataTable.Columns.Add("Т_Сектор");
            dataTable.Columns.Add("Т_Должность");
            dataTable.Columns.Add("Exchange - статус миграции");
            dataTable.Columns.Add("Заметки");
            dataTable.Columns.Add("LDAP путь");
            dataTable.Columns.Add("Состоит в группах");
            dataTable.Columns.Add("Срок действия УЗ истекает");
            dataTable.Columns.Add("Статус УЗ");
            dataTable.Columns.Add("Создана");
            dataTable.Columns.Add("Модифицирована");
            dataTable.Columns.Add("Требовать смену пароля");
            dataTable.Columns.Add("Пароль изменён");
            dataTable.Columns.Add("Пароль истекает");
            dataTable.Columns.Add("Последняя авторизация");
            dataTable.Columns.Add("Photo", typeof(byte[]));

            foreach (SearchResult sr in ds.FindAll())
            {
                DataRow row = dataTable.NewRow();
                row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["Фамилия"] = sr.Properties["sn"].Count > 0 ? sr.Properties["sn"][0]?.ToString() ?? "" : "";
                row["Имя"] = sr.Properties["givenName"].Count > 0 ? sr.Properties["givenName"][0]?.ToString() ?? "" : "";
                row["Отчество"] = sr.Properties["middleName"].Count > 0 ? sr.Properties["middleName"][0]?.ToString() ?? "" : "";
                row["ФИО"] = $"{row["Фамилия"]} {row["Имя"]} {row["Отчество"]}".Trim();
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Телефон"] = sr.Properties["telephoneNumber"].Count > 0 ? sr.Properties["telephoneNumber"][0]?.ToString() ?? "" : "";
                row["Моб. телефон"] = sr.Properties["mobilepers"].Count > 0 ? sr.Properties["mobilepers"][0]?.ToString() ?? "" : "";
                row["Владелец"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Почтовый сервер"] = sr.Properties["eximMailhost"].Count > 0 ? sr.Properties["eximMailhost"][0]?.ToString() ?? "" : "";
                row["Почтовое хранилище"] = sr.Properties["eximMaildir"].Count > 0 ? sr.Properties["eximMaildir"][0]?.ToString() ?? "" : "";
                row["Расположение ящика"] = sr.Properties["homeMDB"].Count > 0 ? "On-prem" : "Cloud";
                
                string managerDN = sr.Properties["manager"].Count > 0 ? sr.Properties["manager"][0]?.ToString() ?? "" : "";
                if (!string.IsNullOrWhiteSpace(managerDN))
                {
                    var managerInfo = GetManagerDisplayInfo(managerDN);
                    row["Руководитель"] = managerInfo;
                }
                
                row["Должность"] = sr.Properties["title"].Count > 0 ? sr.Properties["title"][0]?.ToString() ?? "" : "";
                row["Отдел"] = sr.Properties["department"].Count > 0 ? sr.Properties["department"][0]?.ToString() ?? "" : "";
                row["Компания"] = sr.Properties["company"].Count > 0 ? sr.Properties["company"][0]?.ToString() ?? "" : "";
                row["guid1C"] = sr.Properties["guid1C"].Count > 0 ? sr.Properties["guid1C"][0]?.ToString() ?? "" : "";
                row["guidMD"] = sr.Properties["guidMD"].Count > 0 ? sr.Properties["guidMD"][0]?.ToString() ?? "" : "";

                if (sr.Properties["objectSid"].Count > 0 && sr.Properties["objectSid"][0] is byte[] sidBytes)
                    row["SID"] = new System.Security.Principal.SecurityIdentifier(sidBytes, 0).Value;

                row["Т_Дирекция"] = sr.Properties["extensionAttribute2"].Count > 0 ? sr.Properties["extensionAttribute2"][0]?.ToString() ?? "" : "";
                row["Т_Департамент"] = sr.Properties["extensionAttribute4"].Count > 0 ? sr.Properties["extensionAttribute4"][0]?.ToString() ?? "" : "";
                row["Т_Управление/Функция"] = sr.Properties["extensionAttribute3"].Count > 0 ? sr.Properties["extensionAttribute3"][0]?.ToString() ?? "" : "";
                row["Т_Направление/Служба"] = sr.Properties["extensionAttribute5"].Count > 0 ? sr.Properties["extensionAttribute5"][0]?.ToString() ?? "" : "";
                row["Т_Отдел"] = sr.Properties["extensionAttribute6"].Count > 0 ? sr.Properties["extensionAttribute6"][0]?.ToString() ?? "" : "";
                row["Т_Сектор"] = sr.Properties["extensionAttribute7"].Count > 0 ? sr.Properties["extensionAttribute7"][0]?.ToString() ?? "" : "";
                row["Т_Должность"] = sr.Properties["extensionAttribute11"].Count > 0 ? sr.Properties["extensionAttribute11"][0]?.ToString() ?? "" : "";

                row["Exchange - статус миграции"] = sr.Properties["extensionAttribute10"].Count > 0 ? sr.Properties["extensionAttribute10"][0]?.ToString() ?? "" : "";
                row["Заметки"] = sr.Properties["info"].Count > 0 ? sr.Properties["info"][0]?.ToString() ?? "" : "";
                row["LDAP путь"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";

                string groups = "";
                foreach (object g in sr.Properties["memberOf"])
                    groups += g?.ToString() + "|";
                row["Состоит в группах"] = groups.TrimEnd('|');

                row["Срок действия УЗ истекает"] = sr.Properties["accountExpires"].Count > 0
                    ? SafeFromFileTimeUtc(Convert.ToInt64(sr.Properties["accountExpires"][0]?.ToString() ?? "0"))?.ToLocalTime().ToString() ?? "Никогда"
                    : "Никогда";

                row["Создана"] = sr.Properties["createTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["createTimeStamp"][0]).ToLocalTime().ToString() : "";
                row["Модифицирована"] = sr.Properties["modifyTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["modifyTimeStamp"][0]).ToLocalTime().ToString() : "";

                string pwdLastSetVal = sr.Properties["pwdLastSet"].Count > 0 ? sr.Properties["pwdLastSet"][0]?.ToString() ?? "" : "";
                row["Требовать смену пароля"] = (pwdLastSetVal == "0" || string.IsNullOrWhiteSpace(pwdLastSetVal)) ? "Флаг установлен" : "Флаг НЕ установлен";

                long pwdLastSetTicks = 0;
                if (long.TryParse(pwdLastSetVal, out pwdLastSetTicks) && pwdLastSetTicks != 0)
                {
                    var pwdDate = SafeFromFileTimeUtc(pwdLastSetTicks)?.ToLocalTime();
                    row["Пароль изменён"] = pwdDate?.ToString() ?? "";
                }
                else
                {
                    row["Пароль изменён"] = "";
                }

                string lastLogonVal = sr.Properties["lastLogonTimestamp"].Count > 0 ? sr.Properties["lastLogonTimestamp"][0]?.ToString() ?? "0" : "0";
                long lastLogonTicks = 0;
                if (long.TryParse(lastLogonVal, out lastLogonTicks))
                {
                    var lastLogonDate = SafeFromFileTime(lastLogonTicks);
                    row["Последняя авторизация"] = lastLogonDate?.ToString() ?? "";
                }
                else
                {
                    row["Последняя авторизация"] = "";
                }

                int uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
                string hrStatus = sr.Properties["extensionAttribute8"].Count > 0 ? sr.Properties["extensionAttribute8"][0]?.ToString() ?? "" : "";
                string hrStatusStr = !string.IsNullOrWhiteSpace(hrStatus) ? $", Кадровый статус - {hrStatus}" : "";

                if ((uac & 0x10000) != 0)
                    row["Пароль истекает"] = "Бессрочный пароль";
                else if (sr.Properties["msDS-UserPasswordExpiryTimeComputed"].Count > 0)
                {
                    long expVal = Convert.ToInt64(sr.Properties["msDS-UserPasswordExpiryTimeComputed"][0]?.ToString() ?? "0");
                    row["Пароль истекает"] = SafeFromFileTimeUtc(expVal)?.ToLocalTime().ToString() ?? "N/D";
                }

                if ((uac & 2) != 0)
                    row["Статус УЗ"] = "DISABLE" + hrStatusStr;
                else
                    row["Статус УЗ"] = "NORMAL" + hrStatusStr;

                if (sr.Properties["thumbnailPhoto"].Count > 0)
                    row["Photo"] = sr.Properties["thumbnailPhoto"][0] as byte[];

                dataTable.Rows.Add(row);
            }
        }
        catch (Exception ex)
        {
            error = ex;
        }
        return dataTable;
    }

    public DataTable GetGroupMembers(string distinguishedName)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(distinguishedName))
            return dt;

        try
        {
            var props = new[] {
                "sAMAccountName", "sn", "givenName", "middleName", "displayName", "mail", "description",
                "eximMailhost", "title", "department", "company", "extensionAttribute10",
                "userAccountControl", "extensionAttribute8", "distinguishedName", "guidMD",
                "objectCategory", "objectClass", "cn"
            };
            using var searchRoot = new DirectoryEntry("LDAP://" + Data.DC + "/" + distinguishedName);
            using var ds = new DirectorySearcher(searchRoot, "(|(objectClass=user)(objectClass=maillist)(objectClass=msExchDynamicDistributionList))")
            {
                SearchScope = SearchScope.Base,
                ReferralChasing = ReferralChasingOption.None,
                AttributeScopeQuery = "member"
            };
            ds.PageSize = 100;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("СУМД", typeof(bool));
            dt.Columns.Add("Логин");
            dt.Columns.Add("ФИО");
            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Почта");
            dt.Columns.Add("Почтовый сервер");
            dt.Columns.Add("Должность");
            dt.Columns.Add("Отдел");
            dt.Columns.Add("Компания");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Статус миграции в Exchange");
            dt.Columns.Add("Статус УЗ");
            dt.Columns.Add("distinguishedName");

            foreach (SearchResult result in ds.FindAll())
            {
                string objectCategory = result.Properties["objectCategory"].Count > 0 ? result.Properties["objectCategory"][0]?.ToString() ?? "" : "";
                string entityType = "";
                if (objectCategory.ToLower().Contains("computer")) entityType = "ПК";
                else if (objectCategory.ToLower().Contains("person")) entityType = "Сотрудник";
                else if (objectCategory.ToLower().Contains("maillist")) entityType = "Рассылка";
                else if (objectCategory.ToLower().Contains("ms-exch-dynamic-distribution-list")) entityType = "Динамическая рассылка";

                var row = dt.NewRow();
                if (entityType == "ПК")
                    row["Логин"] = result.Properties["cn"].Count > 0 ? result.Properties["cn"][0]?.ToString() ?? "" : "";
                else
                    row["Логин"] = result.Properties["sAMAccountName"].Count > 0 ? result.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";

                string sn = result.Properties["sn"].Count > 0 ? result.Properties["sn"][0]?.ToString() ?? "" : "";
                string givenName = result.Properties["givenName"].Count > 0 ? result.Properties["givenName"][0]?.ToString() ?? "" : "";
                string middleName = result.Properties["middleName"].Count > 0 ? result.Properties["middleName"][0]?.ToString() ?? "" : "";
                row["ФИО"] = $"{sn} {givenName} {middleName}".Trim();
                row["Вывод. имя"] = result.Properties["displayName"].Count > 0 ? result.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Почта"] = result.Properties["mail"].Count > 0 ? result.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Почтовый сервер"] = result.Properties["eximMailhost"].Count > 0 ? result.Properties["eximMailhost"][0]?.ToString() ?? "" : "";
                row["Должность"] = result.Properties["title"].Count > 0 ? result.Properties["title"][0]?.ToString() ?? "" : "";
                row["Отдел"] = result.Properties["department"].Count > 0 ? result.Properties["department"][0]?.ToString() ?? "" : "";
                row["Компания"] = result.Properties["company"].Count > 0 ? result.Properties["company"][0]?.ToString() ?? "" : "";
                row["Описание"] = result.Properties["description"].Count > 0 ? result.Properties["description"][0]?.ToString() ?? "" : "";
                row["Статус миграции в Exchange"] = result.Properties["extensionAttribute10"].Count > 0 ? result.Properties["extensionAttribute10"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = result.Properties["distinguishedName"].Count > 0 ? result.Properties["distinguishedName"][0]?.ToString() ?? "" : "";

                int uac = result.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(result.Properties["userAccountControl"][0]) : 0;
                string hrStatus = result.Properties["extensionAttribute8"].Count > 0 ? result.Properties["extensionAttribute8"][0]?.ToString() ?? "" : "";
                string hrStatusStr = !string.IsNullOrWhiteSpace(hrStatus) ? $"HR статус - {hrStatus}" : "HR статус - Работает";

                if ((uac & 2) != 0)
                    row["Статус УЗ"] = $"DISABLE, {hrStatusStr}";
                else
                    row["Статус УЗ"] = $"NORMAL, {hrStatusStr}";

                row["СУМД"] = result.Properties["guidMD"].Count > 0;
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable GetMaillistInfo(string query)
    {
        var dt = new DataTable();
        query = CanonicalizeStringForLdapFilter(query);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        var queryForCn = query;
        var atIndex = query.IndexOf('@');
        if (atIndex > 0)
            queryForCn = query.Substring(0, atIndex);

        try
        {
            var props = new[] { "cn", "displayName", "distinguishedName", "description", "mail", "eximMaillistOwner", "eximSendTo" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=eximMaillist)(|(cn=*{queryForCn}*)(mail={query}*)(displayName=*{query}*)))"
            };
            ds.PageSize = 51;
            ds.SizeLimit = 50;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Логин");
            dt.Columns.Add("distinguishedName");
            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Владелец");
            dt.Columns.Add("Члены рассылки Exim");
            dt.Columns.Add("Почта");

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Логин"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";

                if (sr.Properties["eximMaillistOwner"].Count > 0)
                    row["Владелец"] = string.Join(";", sr.Properties["eximMaillistOwner"].Cast<object>().Where(o => !o.ToString()!.Contains("cn=deleted objects", StringComparison.OrdinalIgnoreCase)));

                if (sr.Properties["eximSendTo"].Count > 0)
                    row["Члены рассылки Exim"] = string.Join(";", sr.Properties["eximSendTo"].Cast<object>());

                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable GetDynamicGroupInfo(string query)
    {
        var dt = new DataTable();
        query = CanonicalizeStringForLdapFilter(query);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        var queryForCn = query;
        var atIndex = query.IndexOf('@');
        if (atIndex > 0)
            queryForCn = query.Substring(0, atIndex);

        try
        {
            var props = new[] { "cn", "displayName", "distinguishedName", "info", "mail", "managedBy" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=msExchDynamicDistributionList)(|(cn=*{queryForCn}*)(mail={query}*)(displayName=*{query}*)))"
            };
            ds.PageSize = 51;
            ds.SizeLimit = 50;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Логин");
            dt.Columns.Add("distinguishedName");
            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Владелец");
            dt.Columns.Add("Почта");

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Логин"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["info"].Count > 0 ? sr.Properties["info"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable GetComputerInfo(string compName)
    {
        var dt = new DataTable();
        compName = CanonicalizeStringForLdapFilter(compName);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            var props = new[] { "cn", "sAMAccountName", "distinguishedName", "operatingSystem", "whenCreated", "userAccountControl", "operatingSystemVersion", "whenChanged", "memberOf", "operatingSystemServicePack" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=computer)(objectCategory=computer)(|(cn={compName}*)(sAMAccountName={compName}*)(sAMAccountName={compName})))"
            };
            ds.PageSize = 51;
            ds.SizeLimit = 50;
            ds.ClientTimeout = TimeSpan.FromSeconds(10);
            ds.ServerTimeLimit = TimeSpan.FromSeconds(10);
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Имя");
            dt.Columns.Add("ОС");
            dt.Columns.Add("Сервис пак");
            dt.Columns.Add("Пакет обновления");
            dt.Columns.Add("Состоит в группах");
            dt.Columns.Add("distinguishedName");
            dt.Columns.Add("Создана");
            dt.Columns.Add("Модифицирована");
            dt.Columns.Add("Статус УЗ");

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Имя"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["ОС"] = sr.Properties["operatingSystem"].Count > 0 ? sr.Properties["operatingSystem"][0]?.ToString() ?? "" : "";
                row["Сервис пак"] = sr.Properties["operatingSystemServicePack"].Count > 0 ? sr.Properties["operatingSystemServicePack"][0]?.ToString() ?? "" : "";
                row["Пакет обновления"] = sr.Properties["operatingSystemVersion"].Count > 0 ? sr.Properties["operatingSystemVersion"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";

                if (sr.Properties["memberOf"].Count > 0)
                    row["Состоит в группах"] = string.Join("|", sr.Properties["memberOf"].Cast<object>());

                row["Модифицирована"] = sr.Properties["whenChanged"].Count > 0 ? Convert.ToDateTime(sr.Properties["whenChanged"][0]).ToLocalTime().ToString() : "";
                row["Создана"] = sr.Properties["whenCreated"].Count > 0 ? Convert.ToDateTime(sr.Properties["whenCreated"][0]).ToLocalTime().ToString() : "";

                var uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
                row["Статус УЗ"] = (uac & 2) != 0 ? "DISABLE" : "NORMAL";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable GetComputerInfoByOwner(string ownerLogin)
    {
        var dt = new DataTable();
        ownerLogin = CanonicalizeStringForLdapFilter(ownerLogin);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            using var userSearchRoot = new DirectoryEntry(path);
            using var userDs = new DirectorySearcher(userSearchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(objectCategory=person)(sAMAccountName={ownerLogin}))"
            };
            userDs.PropertiesToLoad.Add("distinguishedName");

            string? ownerDn = null;
            var userResult = userDs.FindOne();
            if (userResult != null)
            {
                ownerDn = userResult.Properties["distinguishedName"][0]?.ToString();
            }

            if (string.IsNullOrEmpty(ownerDn))
            {
                ownerDn = ownerLogin;
            }

            var props = new[] { "cn", "distinguishedName", "operatingSystem", "whenCreated", "userAccountControl", "operatingSystemVersion", "whenChanged", "memberOf", "operatingSystemServicePack", "managedBy", "description" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=computer)(managedBy={ownerDn}))"
            };
            ds.PageSize = 51;
            ds.SizeLimit = 50;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Имя");
            dt.Columns.Add("ОС");
            dt.Columns.Add("Сервис пак");
            dt.Columns.Add("Пакет обновления");
            dt.Columns.Add("Состоит в группах");
            dt.Columns.Add("distinguishedName");
            dt.Columns.Add("Создана");
            dt.Columns.Add("Модифицирована");
            dt.Columns.Add("Статус УЗ");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Владелец");

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Имя"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["ОС"] = sr.Properties["operatingSystem"].Count > 0 ? sr.Properties["operatingSystem"][0]?.ToString() ?? "" : "";
                row["Сервис пак"] = sr.Properties["operatingSystemServicePack"].Count > 0 ? sr.Properties["operatingSystemServicePack"][0]?.ToString() ?? "" : "";
                row["Пакет обновления"] = sr.Properties["operatingSystemVersion"].Count > 0 ? sr.Properties["operatingSystemVersion"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Владелец"] = ownerLogin;

                if (sr.Properties["memberOf"].Count > 0)
                    row["Состоит в группах"] = string.Join("|", sr.Properties["memberOf"].Cast<object>());

                row["Модифицирована"] = sr.Properties["whenChanged"].Count > 0 ? Convert.ToDateTime(sr.Properties["whenChanged"][0]).ToLocalTime().ToString() : "";
                row["Создана"] = sr.Properties["whenCreated"].Count > 0 ? Convert.ToDateTime(sr.Properties["whenCreated"][0]).ToLocalTime().ToString() : "";

                var uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
                row["Статус УЗ"] = (uac & 2) != 0 ? "DISABLE" : "NORMAL";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable GetAllGroupBox(string distinguishedName)
    {
        var dt = new DataTable();
        try
        {
            var props = new[] { "sAMAccountName", "displayName", "description", "mail", "createTimeStamp", "extensionAttribute10", "eximMailhost", "eximAdminDescription", "eximFullControlMember", "msExchDelegateListLink" };
            using var searchRoot = GetRootEntry();
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                Filter = $"(&(objectClass=user)(objectCategory=person)(|(eximFullControlMember={distinguishedName})(msExchDelegateListLink={distinguishedName})))",
                ReferralChasing = ReferralChasingOption.None,
            };
            ds.PageSize = 50;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Присутствует в системе");
            dt.Columns.Add("Логин");
            dt.Columns.Add("Почта");
            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Владелец ящика");
            dt.Columns.Add("Почтовый сервер");
            dt.Columns.Add("Статус миграции в Exchange");

            var results = ds.FindAll();
            foreach (SearchResult sr in results)
            {
                var eximMembers = "";
                var exchangeMembers = "";

                if (sr.Properties["eximFullControlMember"].Count > 0)
                {
                    var memberList = new List<string>();
                    foreach (var item in sr.Properties["eximFullControlMember"])
                    {
                        var itemStr = item?.ToString() ?? "";
                        if (itemStr.ToLower().IndexOf("svc_eximmigrate") <= 0 && itemStr.ToLower().IndexOf("cn=deleted objects,") <= 0)
                        {
                            memberList.Add(itemStr);
                        }
                    }
                    eximMembers = string.Join(";", memberList);
                }

                if (sr.Properties["msExchDelegateListLink"].Count > 0)
                {
                    var memberList = new List<string>();
                    foreach (var item in sr.Properties["msExchDelegateListLink"])
                    {
                        var itemStr = item?.ToString() ?? "";
                        if (itemStr.ToLower().IndexOf("svc_eximmigrate") <= 0 && itemStr.ToLower().IndexOf("cn=deleted objects,") <= 0)
                        {
                            memberList.Add(itemStr);
                        }
                    }
                    exchangeMembers = string.Join(";", memberList);
                }

                bool hasExchange = !string.IsNullOrEmpty(exchangeMembers) && exchangeMembers.Contains(distinguishedName, StringComparison.OrdinalIgnoreCase);
                bool hasExim = !string.IsNullOrEmpty(eximMembers) && eximMembers.Contains(distinguishedName, StringComparison.OrdinalIgnoreCase);

                var row = dt.NewRow();
                if (hasExchange && hasExim)
                    row["Присутствует в системе"] = "Exchange/Exim";
                else if (hasExchange)
                    row["Присутствует в системе"] = "Exchange";
                else
                    row["Присутствует в системе"] = "Exim";

                row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Владелец ящика"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                row["Почтовый сервер"] = sr.Properties["eximMailhost"].Count > 0 ? sr.Properties["eximMailhost"][0]?.ToString() ?? "" : "";
                row["Статус миграции в Exchange"] = sr.Properties["extensionAttribute10"].Count > 0 ? sr.Properties["extensionAttribute10"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch
        {
        }
        return dt;
    }

    public DataTable GetAllMaillistWithOwner(string distinguishedName)
    {
        var dataTable = new DataTable();
        var dataTable2 = new DataTable();
        var dataTable3 = new DataTable();

        try
        {
            using var directoryEntry = new DirectoryEntry($"LDAP://{Data.DC}/{distinguishedName}");
            var list = new List<string>();

            if (directoryEntry.Properties["eximAltMail"].Count > 0)
            {
                foreach (var item in directoryEntry.Properties["eximAltMail"])
                {
                    list.Add(item?.ToString() ?? "");
                }
            }
            if (directoryEntry.Properties["proxyAddresses"].Count > 0)
            {
                foreach (var item in directoryEntry.Properties["proxyAddresses"])
                {
                    list.Add(item?.ToString()?.ToLower().Replace("smtp:", "") ?? "");
                }
            }

            if (directoryEntry.Properties["mail"].Count <= 0)
            {
                return dataTable3;
            }

            list.Add(directoryEntry.Properties["mail"][0]?.ToString() ?? "");
            list = list.Distinct().ToList();

            var filterBuilder = new System.Text.StringBuilder();
            foreach (var email in list)
            {
                if (filterBuilder.Length > 0) filterBuilder.Append(" OR ");
                filterBuilder.Append($"(eximSendTo={email})");
            }

            var props = new[] { "cn", "displayName", "description", "mail", "eximMaillistOwner" };
            using var searchRoot = GetRootEntry();
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                Filter = $"(&(objectClass=eximMaillist)(objectCategory=eximMaillist)(|{filterBuilder}))",
                ReferralChasing = ReferralChasingOption.None,
            };
            ds.PageSize = 300;
            ds.PropertiesToLoad.AddRange(props);

            dataTable.Columns.Add("Логин");
            dataTable.Columns.Add("Вывод. имя");
            dataTable.Columns.Add("Описание");
            dataTable.Columns.Add("Владелец");
            dataTable.Columns.Add("Почта");

            var results = ds.FindAll();
            foreach (SearchResult sr in results)
            {
                var row = dataTable.NewRow();
                row["Логин"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";

                var ownerList = new List<string>();
                if (sr.Properties["eximMaillistOwner"].Count > 0)
                {
                    foreach (var item in sr.Properties["eximMaillistOwner"])
                    {
                        var itemStr = item?.ToString() ?? "";
                        if (itemStr.ToLower().IndexOf("cn=deleted objects,") <= 0)
                        {
                            ownerList.Add(itemStr);
                        }
                    }
                }
                row["Владелец"] = string.Join(";", ownerList);
                dataTable.Rows.Add(row);
            }

            dataTable2.Columns.Add("Логин");
            dataTable2.Columns.Add("Вывод. имя");
            dataTable2.Columns.Add("Описание");
            dataTable2.Columns.Add("Почта");

            if (directoryEntry.Properties["memberOf"].Count > 0)
            {
                foreach (var item in directoryEntry.Properties["memberOf"])
                {
                    var groupInfo = GetGroupInfoOnDistName(item?.ToString() ?? "");
                    foreach (DataRow groupRow in groupInfo.Rows)
                    {
                        var newRow = dataTable2.NewRow();
                        newRow["Логин"] = groupRow["GroupName"]?.ToString() ?? "";
                        newRow["Вывод. имя"] = groupRow["Вывод. имя"]?.ToString() ?? "";
                        newRow["Описание"] = groupRow["Описание"]?.ToString() ?? "";
                        newRow["Почта"] = groupRow["Почта"]?.ToString() ?? "";

                        if (newRow["Логин"].ToString()?.ToLower().Contains("_dg") == true && !string.IsNullOrWhiteSpace(newRow["Почта"].ToString()))
                        {
                            dataTable2.Rows.Add(newRow);
                        }
                    }
                }
            }

            dataTable3.Columns.Add("Присутствует в системе");
            dataTable3.Columns.Add("Логин");
            dataTable3.Columns.Add("Вывод. имя");
            dataTable3.Columns.Add("Описание");
            dataTable3.Columns.Add("Владелец");
            dataTable3.Columns.Add("Почта");

            foreach (DataRow row2 in dataTable.Rows)
            {
                var newRow = dataTable3.NewRow();
                var existingInTable2 = dataTable2.Select($"[Почта] = '{row2["Почта"]?.ToString()?.Replace("'", "''")}'");
                if (existingInTable2.Length != 0)
                {
                    newRow["Присутствует в системе"] = "Exchange/Exim";
                }
                else
                {
                    newRow["Присутствует в системе"] = "Exim";
                }

                newRow["Логин"] = row2["Логин"];
                newRow["Вывод. имя"] = row2["Вывод. имя"];
                newRow["Описание"] = row2["Описание"];
                newRow["Почта"] = row2["Почта"];

                var ownerDNs = row2["Владелец"]?.ToString()?.Split(';', StringSplitOptions.RemoveEmptyEntries) ?? Array.Empty<string>();
                var ownerNames = new List<string>();
                foreach (var ownerDN in ownerDNs)
                {
                    try
                    {
                        using var ownerEntry = new DirectoryEntry($"LDAP://{Data.DC}/{ownerDN}");
                        var ownerFio = ownerEntry.Properties["displayName"].Count > 0 ? ownerEntry.Properties["displayName"][0]?.ToString() ?? "" : "";
                        var ownerMail = ownerEntry.Properties["mail"].Count > 0 ? ownerEntry.Properties["mail"][0]?.ToString() ?? "" : "";
                        if (!string.IsNullOrWhiteSpace(ownerFio) || !string.IsNullOrWhiteSpace(ownerMail))
                        {
                            ownerNames.Add($"{ownerFio} ({ownerMail})");
                        }
                    }
                    catch { }
                }
                newRow["Владелец"] = string.Join("; ", ownerNames);
                dataTable3.Rows.Add(newRow);
            }

            foreach (DataRow row3 in dataTable2.Rows)
            {
                var existingInTable = dataTable.Select($"[Почта] = '{row3["Почта"]?.ToString()?.Replace("'", "''")}'");
                if (existingInTable.Length == 0)
                {
                    var newRow = dataTable3.NewRow();
                    newRow["Присутствует в системе"] = "Exchange";
                    newRow["Логин"] = row3["Логин"];
                    newRow["Вывод. имя"] = row3["Вывод. имя"];
                    newRow["Описание"] = row3["Описание"];
                    newRow["Почта"] = row3["Почта"];
                    dataTable3.Rows.Add(newRow);
                }
            }
        }
        catch
        {
        }

        return dataTable3;
    }

    public DataTable GetGroupBoxAccess(string login, string distinguishedName)
    {
        return GetAllGroupBox(distinguishedName);
    }

    public DataTable GetMailboxAccess(string login, string distinguishedName)
    {
        return GetAllMaillistWithOwner(distinguishedName);
    }

    public DataTable GetVladetelIs(string login)
    {
        var dt = new DataTable();
        var path = $"LDAP://{Data.DC}/{Data.AdPath_Domain}";

        try
        {
            var ldapFilter = $"(&(objectClass=user)(eximAdminDescription=*{login}*))";
            
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.Subordinate,
                Filter = ldapFilter
            };
            ds.PageSize = 50;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "mail", "eximAdminDescription" });

            dt.Columns.Add("Логин");
            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Владелец");
            dt.Columns.Add("Почта");

            int rowCount = 0;
            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                var sAMAccountName = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                var displayName = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                var description = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                var eximAdminDescription = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                var mail = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                
                row["Логин"] = sAMAccountName;
                row["Вывод. имя"] = displayName;
                row["Описание"] = description;
                row["Владелец"] = eximAdminDescription;
                row["Почта"] = mail;
                dt.Rows.Add(row);
                
                rowCount++;
            }
        }
        catch
        {
        }
        
        return dt;
    }
    
    private string? GetUserDnByMail(string mail)
    {
        try
        {
            var path = "LDAP://" + Data.DC + Data.AdPath_Domain;
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(mail={mail})"
            };
            ds.PropertiesToLoad.Add("distinguishedName");
            var result = ds.FindOne();
            if (result != null && result.Properties["distinguishedName"].Count > 0)
            {
                return result.Properties["distinguishedName"][0]?.ToString();
            }
        }
        catch
        {
        }
        return null;
    }

    public DataTable GetEximMembers(string mail)
    {
        var dt = new DataTable();
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Почта");
        dt.Columns.Add("Описание");

        if (string.IsNullOrWhiteSpace(mail))
            return dt;

        try
        {
            var userDn = GetUserDnByMail(mail);
            if (string.IsNullOrWhiteSpace(userDn))
            {
                return dt;
            }

            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(objectCategory=person)(eximFullControlMember={userDn}))"
            };
            ds.PageSize = 50;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "mail", "description" });

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch
        {
        }
        return dt;
    }

    public DataTable GetExchangeMembers(string mail)
    {
        var dt = new DataTable();
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Почта");
        dt.Columns.Add("Описание");

        if (string.IsNullOrWhiteSpace(mail))
            return dt;

        try
        {
            var userDn = GetUserDnByMail(mail);
            if (string.IsNullOrWhiteSpace(userDn))
            {
                return dt;
            }

            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(objectCategory=person)(msExchDelegateListLink={userDn}))"
            };
            ds.PageSize = 50;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "mail", "description" });

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch
        {
        }
        return dt;
    }

    public string GetObjectInfo_WithDistinguishedName(List<string> distinguishedNameList)
    {
        var resultList = new List<string>();
        foreach (var distinguishedName in distinguishedNameList)
        {
            try
            {
                using var entry = new DirectoryEntry("LDAP://" + Data.DC + distinguishedName);
                var sn = entry.Properties["sn"].Count > 0 ? entry.Properties["sn"][0]?.ToString() + " " : "";
                var givenName = entry.Properties["givenName"].Count > 0 ? entry.Properties["givenName"][0]?.ToString() + " " : "";
                var middleName = entry.Properties["middleName"].Count > 0 ? entry.Properties["middleName"][0]?.ToString() : "";
                var displayName = entry.Properties["displayName"].Count > 0 ? entry.Properties["displayName"][0]?.ToString() : "";
                var mail = entry.Properties["mail"].Count > 0 ? entry.Properties["mail"][0]?.ToString() : "";
                var name = string.IsNullOrWhiteSpace(sn + givenName + middleName) ? displayName : sn + givenName + middleName;
                mail = string.IsNullOrWhiteSpace(mail) ? "not mail" : mail;
                resultList.Add(name.Trim() + " (" + mail + ")");
            }
            catch
            {
                resultList.Add(distinguishedName);
            }
        }
        return string.Join("|", resultList.Distinct());
    }

    public DataTable GetObjectInfo_WithMailList(List<string> mailList)
    {
        var dt = new DataTable();
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;
        var props = new[] { "sn", "givenName", "middleName", "displayName", "mail", "cn", "description" };
        dt.Columns.Add("Логин");
        dt.Columns.Add("ФИО");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Почта");

        foreach (var mail in mailList.Distinct())
        {
            try
            {
                using var searchRoot = new DirectoryEntry(path);
                using var ds = new DirectorySearcher(searchRoot)
                {
                    SearchScope = SearchScope.Subtree,
                    ReferralChasing = ReferralChasingOption.None,
                    Filter = $"(|(mail={mail})(eximAltMail={mail})(proxyAddresses=smtp:{mail}))"
                };
                ds.PropertiesToLoad.AddRange(props);
                var result = ds.FindOne();
                if (result != null)
                {
                    var sn = result.Properties["sn"].Count > 0 ? result.Properties["sn"][0]?.ToString() + " " : "";
                    var givenName = result.Properties["givenName"].Count > 0 ? result.Properties["givenName"][0]?.ToString() + " " : "";
                    var middleName = result.Properties["middleName"].Count > 0 ? result.Properties["middleName"][0]?.ToString() : "";
                    var cn = result.Properties["cn"].Count > 0 ? result.Properties["cn"][0]?.ToString() : "";
                    var displayName = result.Properties["displayName"].Count > 0 ? result.Properties["displayName"][0]?.ToString() : "";
                    var descr = result.Properties["description"].Count > 0 ? result.Properties["description"][0]?.ToString() : "";

                    if (dt.Select($"[Логин]='{cn}'").Length == 0)
                    {
                        var row = dt.NewRow();
                        row["Логин"] = cn;
                        row["ФИО"] = sn + givenName + middleName;
                        row["Вывод. имя"] = displayName;
                        row["Описание"] = descr;
                        row["Почта"] = mail;
                        dt.Rows.Add(row);
                    }
                }
            }
            catch { }
        }
        return dt;
    }

    public string GetObjectInfo_WithMail(List<string> mailList)
    {
        var resultList = new List<string>();
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;
        var props = new[] { "sn", "givenName", "middleName", "displayName", "mail" };

        foreach (var mail in mailList)
        {
            try
            {
                using var searchRoot = new DirectoryEntry(path);
                using var ds = new DirectorySearcher(searchRoot)
                {
                    SearchScope = SearchScope.Subtree,
                    ReferralChasing = ReferralChasingOption.None,
                    Filter = $"(|(mail={mail})(eximAltMail={mail})(proxyAddresses=smtp:{mail}))"
                };
                ds.PropertiesToLoad.AddRange(props);
                var result = ds.FindOne();
                if (result != null)
                {
                    var sn = result.Properties["sn"].Count > 0 ? result.Properties["sn"][0]?.ToString() + " " : "";
                    var givenName = result.Properties["givenName"].Count > 0 ? result.Properties["givenName"][0]?.ToString() + " " : "";
                    var middleName = result.Properties["middleName"].Count > 0 ? result.Properties["middleName"][0]?.ToString() : "";
                    var displayName = result.Properties["displayName"].Count > 0 ? result.Properties["displayName"][0]?.ToString() : "";
                    var mailVal = result.Properties["mail"].Count > 0 ? result.Properties["mail"][0]?.ToString() : "";
                    var name = string.IsNullOrWhiteSpace(sn + givenName + middleName) ? displayName : sn + givenName + middleName;
                    mailVal = string.IsNullOrWhiteSpace(mailVal) ? "not mail" : mailVal;
                    resultList.Add(name.Trim() + " (" + mailVal + ")");
                }
            }
            catch { }
        }
        return string.Join("|", resultList.Distinct());
    }

    public DataTable GetManagerInfo(string managerDN)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(managerDN))
            return dt;

        var props = new[] { "displayName", "mail", "title", "department", "sAMAccountName" };

        try
        {
            DirectoryEntry? searchRoot = GetRootEntry();
            
            var escapedDn = managerDN.Replace(",", "\\,").Replace("=", "\\=");
            var filterByDn = $"(&(objectClass=user)(distinguishedName={escapedDn}))";
            
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                ClientTimeout = TimeSpan.FromSeconds(10),
                ServerTimeLimit = TimeSpan.FromSeconds(10),
                Filter = filterByDn
            };
            ds.PropertiesToLoad.AddRange(props);
            var result = ds.FindOne();

            if (result != null)
            {
                dt.Columns.Add("DisplayName");
                dt.Columns.Add("Mail");
                dt.Columns.Add("Title");
                dt.Columns.Add("Department");
                dt.Columns.Add("SamAccountName");

                var row = dt.NewRow();
                row["DisplayName"] = result.Properties["displayName"].Count > 0 ? result.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Mail"] = result.Properties["mail"].Count > 0 ? result.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Title"] = result.Properties["title"].Count > 0 ? result.Properties["title"][0]?.ToString() ?? "" : "";
                row["Department"] = result.Properties["department"].Count > 0 ? result.Properties["department"][0]?.ToString() ?? "" : "";
                row["SamAccountName"] = result.Properties["sAMAccountName"].Count > 0 ? result.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
                return dt;
            }
            
            var cnMatch = System.Text.RegularExpressions.Regex.Match(managerDN, @"^CN=([^,]+)", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            if (cnMatch.Success)
            {
                var login = cnMatch.Groups[1].Value;
                var filterByLogin = $"(sAMAccountName={EscapeDnForLdapFilter(login)})";
                
                using var ds2 = new DirectorySearcher(searchRoot)
                {
                    SearchScope = SearchScope.Subtree,
                    ReferralChasing = ReferralChasingOption.None,
                    ClientTimeout = TimeSpan.FromSeconds(10),
                    ServerTimeLimit = TimeSpan.FromSeconds(10),
                    Filter = filterByLogin
                };
                ds2.PropertiesToLoad.AddRange(props);
                var result2 = ds2.FindOne();
                
                if (result2 != null)
                {
                    dt.Columns.Add("DisplayName");
                    dt.Columns.Add("Mail");
                    dt.Columns.Add("Title");
                    dt.Columns.Add("Department");
                    dt.Columns.Add("SamAccountName");

                    var row = dt.NewRow();
                    row["DisplayName"] = result2.Properties["displayName"].Count > 0 ? result2.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Mail"] = result2.Properties["mail"].Count > 0 ? result2.Properties["mail"][0]?.ToString() ?? "" : "";
                    row["Title"] = result2.Properties["title"].Count > 0 ? result2.Properties["title"][0]?.ToString() ?? "" : "";
                    row["Department"] = result2.Properties["department"].Count > 0 ? result2.Properties["department"][0]?.ToString() ?? "" : "";
                    row["SamAccountName"] = result2.Properties["sAMAccountName"].Count > 0 ? result2.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public string GetManagerDisplayInfo(string managerDN)
    {
        if (string.IsNullOrWhiteSpace(managerDN))
            return "";
        
        try
        {
            var props = new[] { "displayName", "mail" };
            DirectoryEntry? searchRoot = GetRootEntry();
            
            if (searchRoot == null)
                return "";
            
            string? login = null;
            var cnMatch = System.Text.RegularExpressions.Regex.Match(managerDN, @"^CN=([^,]+)", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            if (cnMatch.Success)
                login = cnMatch.Groups[1].Value;
            
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                ClientTimeout = TimeSpan.FromSeconds(10),
                ServerTimeLimit = TimeSpan.FromSeconds(10)
            };
            
            SearchResult? result = null;
            
            var escapedDn = managerDN.Replace(",", "\\,").Replace("=", "\\=");
            ds.Filter = $"(&(objectClass=user)(distinguishedName={escapedDn}))";
            ds.PropertiesToLoad.AddRange(props);
            result = ds.FindOne();
            
            if (result == null && !string.IsNullOrWhiteSpace(login))
            {
                ds.Filter = $"(sAMAccountName={EscapeDnForLdapFilter(login)})";
                result = ds.FindOne();
            }
            
            if (result != null)
            {
                var displayName = result.Properties["displayName"].Count > 0 ? result.Properties["displayName"][0]?.ToString() ?? "" : "";
                var mail = result.Properties["mail"].Count > 0 ? result.Properties["mail"][0]?.ToString() ?? "" : "";
                
                if (!string.IsNullOrWhiteSpace(displayName))
                {
                    if (!string.IsNullOrWhiteSpace(mail))
                        return $"{displayName} ({mail})";
                    return displayName;
                }
            }
        }
        catch { }
        
        return "";
    }

    public DataTable GetDirectReports(string distinguishedName)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(distinguishedName))
            return dt;

        var canonicalDn = distinguishedName;
        try
        {
            using var entry = new DirectoryEntry("LDAP://" + distinguishedName);
            if (entry.Properties["distinguishedName"].Count > 0)
            {
                canonicalDn = entry.Properties["distinguishedName"][0]?.ToString() ?? distinguishedName;
            }
        }
        catch { }

        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;
        var props = new[] { "displayName", "mail", "title", "department", "sAMAccountName", "distinguishedName", "mobilePers" };

        dt.Columns.Add("DisplayName");
        dt.Columns.Add("Mail");
        dt.Columns.Add("Title");
        dt.Columns.Add("Department");
        dt.Columns.Add("SamAccountName");
        dt.Columns.Add("DistinguishedName");
        dt.Columns.Add("MobilePers");

        var escapedDn = EscapeLdapFilterValue(canonicalDn);
        var filter = $"(&(objectClass=user)(objectCategory=person)(manager={escapedDn}))";

        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = filter
            };
            ds.PropertiesToLoad.AddRange(props);

            int count = 0;
            foreach (SearchResult result in ds.FindAll())
            {
                var dn = result.Properties["distinguishedName"].Count > 0 ? result.Properties["distinguishedName"][0]?.ToString() : "N/A";
                var name = result.Properties["displayName"].Count > 0 ? result.Properties["displayName"][0]?.ToString() : "N/A";
                count++;

                var row = dt.NewRow();
                row["DisplayName"] = result.Properties["displayName"].Count > 0 ? result.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Mail"] = result.Properties["mail"].Count > 0 ? result.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Title"] = result.Properties["title"].Count > 0 ? result.Properties["title"][0]?.ToString() ?? "" : "";
                row["Department"] = result.Properties["department"].Count > 0 ? result.Properties["department"][0]?.ToString() ?? "" : "";
                row["SamAccountName"] = result.Properties["sAMAccountName"].Count > 0 ? result.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["DistinguishedName"] = result.Properties["distinguishedName"].Count > 0 ? result.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["MobilePers"] = result.Properties["mobilePers"].Count > 0 ? result.Properties["mobilePers"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch
        {
        }
        return dt;
    }

    public DataTable GetFullHierarchy(string distinguishedName)
    {
        var dt = new DataTable();
        dt.Columns.Add("Уровень", typeof(int));
        dt.Columns.Add("Имя");
        dt.Columns.Add("Должность");
        dt.Columns.Add("Почта");
        dt.Columns.Add("Тип");
        dt.Columns.Add("DistinguishedName");
        dt.Columns.Add("Моб. телефон");

        var visitedDNs = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { distinguishedName };

        AddUserToHierarchy(distinguishedName, dt, 0, "Текущий");

        var managerDN = GetManagerDN(distinguishedName);
        if (!string.IsNullOrWhiteSpace(managerDN))
        {
            try
            {
                BuildHierarchyUp(managerDN, dt, -1, visitedDNs);
            }
            catch
            {
            }
        }

        visitedDNs.Remove(distinguishedName);
        try
        {
            BuildHierarchyDown(distinguishedName, dt, 1, visitedDNs);
        }
        catch
        {
        }

        return dt;
    }

    private string? GetManagerDN(string distinguishedName)
    {
        try
        {
            using var entry = new DirectoryEntry("LDAP://" + distinguishedName);
            if (entry.Properties["manager"].Count > 0)
            {
                var result = entry.Properties["manager"][0]?.ToString();
                return result;
            }
        }
        catch
        {
        }
        return null;
    }

    private void AddUserToHierarchy(string dn, DataTable dt, int level, string type)
    {
        if (string.IsNullOrWhiteSpace(dn)) return;

        try
        {
            using var entry = new DirectoryEntry("LDAP://" + dn);
            var displayName = entry.Properties["displayName"].Count > 0 ? entry.Properties["displayName"][0]?.ToString() : "";
            if (string.IsNullOrWhiteSpace(displayName)) displayName = dn;
            var mobilePhone = entry.Properties["mobilePers"].Count > 0 ? entry.Properties["mobilePers"][0]?.ToString() : "";

            var row = dt.NewRow();
            row["Уровень"] = level;
            row["Имя"] = displayName;
            row["Должность"] = entry.Properties["title"].Count > 0 ? entry.Properties["title"][0]?.ToString() ?? "" : "";
            row["Почта"] = entry.Properties["mail"].Count > 0 ? entry.Properties["mail"][0]?.ToString() ?? "" : "";
            row["Тип"] = type;
            row["DistinguishedName"] = dn;
            row["Моб. телефон"] = mobilePhone;
            dt.Rows.Add(row);
        }
        catch (Exception ex)
        {
            var row = dt.NewRow();
            row["Уровень"] = level;
            row["Имя"] = type == "Текущий" ? "Текущий пользователь не найден" : "Пользователь не найден";
            row["Тип"] = type;
            row["DistinguishedName"] = dn;
            dt.Rows.Add(row);
        }
    }

    private void BuildHierarchyUp(string dn, DataTable dt, int level, HashSet<string> visitedDNs)
    {
        if (string.IsNullOrWhiteSpace(dn) || visitedDNs.Contains(dn)) return;
        visitedDNs.Add(dn);

        try
        {
            using var entry = new DirectoryEntry("LDAP://" + dn);
            var displayName = entry.Properties["displayName"].Count > 0 ? entry.Properties["displayName"][0]?.ToString() : "";
            if (string.IsNullOrWhiteSpace(displayName)) displayName = dn;
            var mobilePhone = entry.Properties["mobilePers"].Count > 0 ? entry.Properties["mobilePers"][0]?.ToString() : "";

            var row = dt.NewRow();
            row["Уровень"] = level;
            row["Имя"] = displayName;
            row["Должность"] = entry.Properties["title"].Count > 0 ? entry.Properties["title"][0]?.ToString() ?? "" : "";
            row["Почта"] = entry.Properties["mail"].Count > 0 ? entry.Properties["mail"][0]?.ToString() ?? "" : "";
            row["Тип"] = "Руководитель";
            row["DistinguishedName"] = dn;
            row["Моб. телефон"] = mobilePhone;
            dt.Rows.Add(row);

            if (entry.Properties["manager"].Count > 0 && entry.Properties["manager"][0] != null)
            {
                var nextManager = entry.Properties["manager"][0]?.ToString();
                if (!string.IsNullOrWhiteSpace(nextManager))
                    BuildHierarchyUp(nextManager, dt, level - 1, visitedDNs);
            }
        }
        catch
        {
            var row = dt.NewRow();
            row["Уровень"] = level;
            row["Имя"] = "Руководитель не найден";
            row["Тип"] = "Руководитель";
            row["DistinguishedName"] = dn;
            dt.Rows.Add(row);
        }
    }

    private void BuildHierarchyDown(string dn, DataTable dt, int level, HashSet<string> visitedDNs)
    {
        if (string.IsNullOrWhiteSpace(dn) || visitedDNs.Contains(dn))
        {
            return;
        }
        visitedDNs.Add(dn);

        var directReports = GetDirectReports(dn);

        foreach (System.Data.DataRow repRow in directReports.Rows)
        {
            var mobilePhone = repRow["MobilePers"]?.ToString() ?? "";
            var displayName = repRow["DisplayName"]?.ToString() ?? "";
            if (string.IsNullOrWhiteSpace(displayName))
                displayName = repRow["DistinguishedName"]?.ToString() ?? "Подчиненный не найден";

            var row = dt.NewRow();
            row["Уровень"] = level;
            row["Имя"] = displayName;
            row["Должность"] = repRow["Title"]?.ToString() ?? "";
            row["Почта"] = repRow["Mail"]?.ToString() ?? "";
            row["Тип"] = "Подчиненный";
            row["DistinguishedName"] = repRow["DistinguishedName"]?.ToString() ?? "";
            row["Моб. телефон"] = mobilePhone;
            dt.Rows.Add(row);

            var nextDN = repRow["DistinguishedName"]?.ToString() ?? "";
            if (!string.IsNullOrWhiteSpace(nextDN))
                BuildHierarchyDown(nextDN, dt, level + 1, visitedDNs);
        }
    }

    public DataTable Fast_GetUserInfoOnGuid1C(string guid1C)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(guid1C)) return dt;
        guid1C = CanonicalizeStringForLdapFilter(guid1C);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        dt.Columns.Add("Логин");
        dt.Columns.Add("СУМД", typeof(bool));
        dt.Columns.Add("distinguishedName");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Департамент");
        dt.Columns.Add("Компания");
        dt.Columns.Add("Телефон");
        dt.Columns.Add("Моб. телефон");
        dt.Columns.Add("Почта");
        dt.Columns.Add("guidMD");
        dt.Columns.Add("guid1C");

        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(objectCategory=user)(guid1C={guid1C}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "telephoneNumber", "mobilepers", "mail", "company", "extensionAttribute4", "guidMD", "guid1C", "userAccountControl" });

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Телефон"] = sr.Properties["telephoneNumber"].Count > 0 ? sr.Properties["telephoneNumber"][0]?.ToString() ?? "" : "";
                row["Моб. телефон"] = sr.Properties["mobilepers"].Count > 0 ? sr.Properties["mobilepers"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Компания"] = sr.Properties["company"].Count > 0 ? sr.Properties["company"][0]?.ToString() ?? "" : "";
                row["Департамент"] = sr.Properties["extensionAttribute4"].Count > 0 ? sr.Properties["extensionAttribute4"][0]?.ToString() ?? "" : "";
                row["guidMD"] = sr.Properties["guidMD"].Count > 0 ? sr.Properties["guidMD"][0]?.ToString() ?? "" : "";
                row["guid1C"] = sr.Properties["guid1C"].Count > 0 ? sr.Properties["guid1C"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                var uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
                row["СУМД"] = (uac & 0x00000001) != 0;
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetUserInfoOnGuidMD(string guidMD)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(guidMD)) return dt;
        guidMD = CanonicalizeStringForLdapFilter(guidMD);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        dt.Columns.Add("Логин");
        dt.Columns.Add("СУМД", typeof(bool));
        dt.Columns.Add("distinguishedName");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Департамент");
        dt.Columns.Add("Компания");
        dt.Columns.Add("Телефон");
        dt.Columns.Add("Моб. телефон");
        dt.Columns.Add("Почта");
        dt.Columns.Add("guidMD");
        dt.Columns.Add("guid1C");

        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(objectCategory=user)(guidMD={guidMD}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "telephoneNumber", "mobilepers", "mail", "company", "extensionAttribute4", "guidMD", "guid1C", "userAccountControl" });

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Телефон"] = sr.Properties["telephoneNumber"].Count > 0 ? sr.Properties["telephoneNumber"][0]?.ToString() ?? "" : "";
                row["Моб. телефон"] = sr.Properties["mobilepers"].Count > 0 ? sr.Properties["mobilepers"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Компания"] = sr.Properties["company"].Count > 0 ? sr.Properties["company"][0]?.ToString() ?? "" : "";
                row["Департамент"] = sr.Properties["extensionAttribute4"].Count > 0 ? sr.Properties["extensionAttribute4"][0]?.ToString() ?? "" : "";
                row["guidMD"] = sr.Properties["guidMD"].Count > 0 ? sr.Properties["guidMD"][0]?.ToString() ?? "" : "";
                row["guid1C"] = sr.Properties["guid1C"].Count > 0 ? sr.Properties["guid1C"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                var uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
                row["СУМД"] = (uac & 0x00000001) != 0;
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetUserInfoOnMail(string mail)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(mail)) return dt;
        mail = CanonicalizeStringForLdapFilter(mail);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        dt.Columns.Add("Логин");
        dt.Columns.Add("Почта");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Владелец");

        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(objectCategory=user)(mail={mail}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "mail", "displayName", "description", "eximAdminDescription" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["mail"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                    row["Почта"] = sr.Properties["mail"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Владелец"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetUserInfoOnLogin(string login)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(login)) return dt;
        login = CanonicalizeStringForLdapFilter(login);

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Владелец");

        try
        {
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=user)(|(objectCategory=user)(objectCategory=person))(|(sAMAccountName={login}*)(cn={login}*)))";
            ds.PageSize = 100;
            ds.SizeLimit = 50;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "eximAdminDescription" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["sAMAccountName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Владелец"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetMailMailboxInfoOnLogin(string login)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(login)) return dt;
        login = CanonicalizeStringForLdapFilter(login);

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Владелец");

        try
        {
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=user)(objectCategory=person)(|(sAMAccountName={login}*)(cn={login}*)))";
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "eximAdminDescription" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["sAMAccountName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Владелец"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetMailMailboxInfoOnDisplayName(string displayName)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(displayName)) return dt;
        displayName = CanonicalizeStringForLdapFilter(displayName);

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Владелец");

        try
        {
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=user)(objectCategory=person)(displayName={displayName}*))";
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "eximAdminDescription" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["sAMAccountName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Владелец"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetMailMailboxInfoOnFio(string fio)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(fio)) return dt;

        var parts = fio.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        for (int i = 0; i < parts.Length; i++)
            parts[i] = CanonicalizeStringForLdapFilter(parts[i]);

        var filter = parts.Length switch
        {
            1 => $"(sn={parts[0]}*)",
            2 => $"(&(sn={parts[0]})(givenName={parts[1]}*))",
            _ => $"(&(sn={parts[0]})(givenName={parts[1]})(middleName={string.Join(" ", parts.Skip(2))}*))"
        };

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Владелец");

        try
        {
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=user)(objectCategory=person){filter})";
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "eximAdminDescription" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["sAMAccountName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Владелец"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetUserInfoOnFio(string fio)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(fio)) return dt;

        var parts = fio.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        for (int i = 0; i < parts.Length; i++)
            parts[i] = CanonicalizeStringForLdapFilter(parts[i]);

        var filter = parts.Length switch
        {
            1 => $"(sn={parts[0]}*)",
            2 => $"(&(sn={parts[0]})(givenName={parts[1]}*))",
            _ => $"(&(sn={parts[0]})(givenName={parts[1]})(middleName={string.Join(" ", parts.Skip(2))}*))"
        };

        dt.Columns.Add("ФИО");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Логин");

        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;
        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(objectCategory=user){filter})"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sn", "givenName", "middleName", "displayName", "description", "sAMAccountName" });

            foreach (SearchResult sr in ds.FindAll())
            {
                var sn = sr.Properties["sn"].Count > 0 ? sr.Properties["sn"][0]?.ToString() + " " : "";
                var givenName = sr.Properties["givenName"].Count > 0 ? sr.Properties["givenName"][0]?.ToString() + " " : "";
                var middleName = sr.Properties["middleName"].Count > 0 ? sr.Properties["middleName"][0]?.ToString() : "";
                var fullName = (sn + givenName + middleName).Trim();

                if (!string.IsNullOrWhiteSpace(fullName))
                {
                    var row = dt.NewRow();
                    row["ФИО"] = fullName;
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetSharedMailboxInfoOnLogin(string loginQuery)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(loginQuery)) return dt;
        loginQuery = CanonicalizeStringForLdapFilter(loginQuery);

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Владелец");

        try
        {
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=user)(objectCategory=user)(cn=m_*)(|(sAMAccountName=m_{loginQuery}*)(sAMAccountName={loginQuery}*)))";
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "eximAdminDescription" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["sAMAccountName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Владелец"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetSharedMailboxInfoOnOwner(string ownerQuery)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(ownerQuery)) return dt;
        ownerQuery = CanonicalizeStringForLdapFilter(ownerQuery);

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Владелец");

        try
        {
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=user)(objectCategory=user)(cn=m_*)(eximAdminDescription=*{ownerQuery}*))";
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "description", "eximAdminDescription" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["sAMAccountName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Владелец"] = sr.Properties["eximAdminDescription"].Count > 0 ? sr.Properties["eximAdminDescription"][0]?.ToString()?.Replace("\n", "; ") ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetUserInfoOnDisplayName(string displayName)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(displayName)) return dt;
        displayName = CanonicalizeStringForLdapFilter(displayName);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Логин");

        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(|(objectCategory=user)(objectCategory=person))(displayName=*{displayName}*))"
            };
            ds.PageSize = 100;
            ds.SizeLimit = 50;
            ds.PropertiesToLoad.AddRange(new[] { "displayName", "description", "sAMAccountName" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["displayName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Вывод. имя"] = sr.Properties["displayName"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetUserInfoOnMobilepers(string phone)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(phone)) return dt;
        phone = NormalizeMobilePhone(phone);
        if (string.IsNullOrWhiteSpace(phone)) return dt;
        phone = CanonicalizeStringForLdapFilter(phone);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Моб. телефон");
        dt.Columns.Add("Описание");

        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=user)(|(objectCategory=user)(objectCategory=person))(mobilepers={phone}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "displayName", "mobilepers", "description" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["sAMAccountName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Моб. телефон"] = sr.Properties["mobilepers"].Count > 0 ? sr.Properties["mobilepers"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable GetGroupInfo(string query, out Exception? error)
    {
        var dt = new DataTable();
        error = null;
        var queryEscaped = CanonicalizeStringForLdapFilter(query);
        var cnFilter = LdapSearch(queryEscaped, "cn");
        var samFilter = LdapSearch(queryEscaped, "login");

        try
        {
            var props = new[] { "sAMAccountName", "distinguishedName", "description", "mail", "createTimeStamp", "info", "displayName", "modifyTimeStamp", "cn" };
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=group)(objectCategory=group)(|{cnFilter}{samFilter}))";
            ds.PageSize = 51;
            ds.SizeLimit = 50;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Логин");
            dt.Columns.Add("Почта");
            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Владелец");
            dt.Columns.Add("distinguishedName");
            dt.Columns.Add("Создана");
            dt.Columns.Add("Модифицирована");

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                var samAccountName = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                var cn = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["Логин"] = !string.IsNullOrEmpty(samAccountName) ? samAccountName : cn;
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                var displayNameGroup = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = !string.IsNullOrWhiteSpace(displayNameGroup) ? displayNameGroup : (!string.IsNullOrEmpty(samAccountName) ? samAccountName : cn);
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Владелец"] = sr.Properties["info"].Count > 0 ? sr.Properties["info"][0]?.ToString() ?? "" : "";
                row["Создана"] = sr.Properties["createTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["createTimeStamp"][0]).ToLocalTime().ToString() : "";
                row["Модифицирована"] = sr.Properties["modifyTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["modifyTimeStamp"][0]).ToLocalTime().ToString() : "";
                dt.Rows.Add(row);
            }

            if (dt.Rows.Count == 0 && query.Contains('='))
            {
                var cnFromDn = GetCnFromDistinguishedName(query);
                var dnFilter = $"(name={EscapeLdapDnValue(cnFromDn)})";
                using var ds2 = CreateSearcher();
                ds2.SearchScope = SearchScope.Subtree;
                ds2.Filter = $"(&(objectClass=group)(objectCategory=group){dnFilter})";
                ds2.PageSize = 2;
                ds2.SizeLimit = 2;
                ds2.PropertiesToLoad.AddRange(props);

                foreach (SearchResult sr in ds2.FindAll())
                {
                    var row = dt.NewRow();
                    var samAccountName = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                    var cn = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                    row["Логин"] = !string.IsNullOrEmpty(samAccountName) ? samAccountName : cn;
                    row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                    row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                    var displayNameGroup = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                    row["Вывод. имя"] = !string.IsNullOrWhiteSpace(displayNameGroup) ? displayNameGroup : (!string.IsNullOrEmpty(samAccountName) ? samAccountName : cn);
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    row["Владелец"] = sr.Properties["info"].Count > 0 ? sr.Properties["info"][0]?.ToString() ?? "" : "";
                    row["Создана"] = sr.Properties["createTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["createTimeStamp"][0]).ToLocalTime().ToString() : "";
                    row["Модифицирована"] = sr.Properties["modifyTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["modifyTimeStamp"][0]).ToLocalTime().ToString() : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch (Exception ex)
        {
            error = ex;
        }
        return dt;
    }

    public DataTable GetGroupInfo(string query, string type, out Exception? error)
    {
        var dt = new DataTable();
        error = null;
        var queryEscaped = CanonicalizeStringForLdapFilter(query);

        try
        {
            string filter;
            if (type == "mail")
            {
                filter = $"(mail=*{queryEscaped}*)";
            }
            else
            {
                filter = LdapSearch(queryEscaped, "cn");
            }

            var props = new[] { "sAMAccountName", "distinguishedName", "description", "mail", "createTimeStamp", "info", "displayName", "modifyTimeStamp", "cn" };
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=group)(objectCategory=group){filter})";
            ds.PageSize = 51;
            ds.SizeLimit = 50;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Логин");
            dt.Columns.Add("Почта");
            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Владелец");
            dt.Columns.Add("distinguishedName");
            dt.Columns.Add("Создана");
            dt.Columns.Add("Модифицирована");

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                var samAccountName = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                var cn = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["Логин"] = !string.IsNullOrEmpty(samAccountName) ? samAccountName : cn;
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                var displayNameGroup = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = !string.IsNullOrWhiteSpace(displayNameGroup) ? displayNameGroup : (!string.IsNullOrEmpty(samAccountName) ? samAccountName : cn);
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Владелец"] = sr.Properties["info"].Count > 0 ? sr.Properties["info"][0]?.ToString() ?? "" : "";
                row["Создана"] = sr.Properties["createTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["createTimeStamp"][0]).ToLocalTime().ToString() : "";
                row["Модифицирована"] = sr.Properties["modifyTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["modifyTimeStamp"][0]).ToLocalTime().ToString() : "";
                dt.Rows.Add(row);
            }
        }
        catch (Exception ex)
        {
            error = ex;
        }
        return dt;
    }

    public DataTable GetAllMaillist(string distinguishedName)
    {
        var dt = new DataTable();
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            using var entry = new DirectoryEntry("LDAP://" + Data.DC + distinguishedName);
            var mailList = new List<string>();

            if (entry.Properties["eximAltMail"].Count > 0)
                foreach (object item in entry.Properties["eximAltMail"])
                    mailList.Add(item?.ToString() ?? "");

            if (entry.Properties["proxyAddresses"].Count > 0)
                foreach (object item in entry.Properties["proxyAddresses"])
                    mailList.Add(item?.ToString()?.ToLower().Replace("smtp:", "") ?? "");

            if (entry.Properties["mail"].Count > 0)
                mailList.Add(entry.Properties["mail"][0]?.ToString() ?? "");

            if (mailList.Count == 0) return dt;

            mailList = mailList.Distinct().ToList();
            var mailFilters = string.Join("", mailList.Select(m => $"(eximSendTo={m})"));

            var props = new[] { "cn", "displayName", "description", "mail", "eximMaillistOwner" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=eximMaillist)(objectCategory=eximMaillist)|{mailFilters})"
            };
            ds.PageSize = 300;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Логин");
            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");
            dt.Columns.Add("Владелец");
            dt.Columns.Add("Почта");

            foreach (SearchResult sr in ds.FindAll())
            {
                var owners = "";
                if (sr.Properties["eximMaillistOwner"].Count > 0)
                {
                    foreach (object item in sr.Properties["eximMaillistOwner"])
                        if (!(item?.ToString()?.Contains("cn=deleted objects", StringComparison.OrdinalIgnoreCase) ?? false))
                            owners += item?.ToString() + ";";
                }

                var row = dt.NewRow();
                row["Логин"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Владелец"] = owners.TrimEnd(';');
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public string GetCompanyFromUnit(string unitName)
    {
        if (string.IsNullOrWhiteSpace(unitName)) return "";
        var path = "LDAP://" + Data.DC + unitName;

        try
        {
            using var entry = new DirectoryEntry(path);
            if (entry.Properties["company"].Count > 0)
                return entry.Properties["company"][0]?.ToString() ?? "";
        }
        catch { }
        return "";
    }

    public DataTable GetGroupInfoOnDistName(string distinguishedName)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(distinguishedName)) return dt;

        var props = new[] { "distinguishedName", "sAMAccountName", "description", "info", "displayName", "mail", "whenCreated" };
        dt.Columns.Add("distname");
        dt.Columns.Add("groupname");
        dt.Columns.Add("info");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Почта");
        dt.Columns.Add("Когда");

        try
        {
            using var searchRoot = new DirectoryEntry("LDAP://" + Data.DC + Data.AdPath_Domain);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = "(&(objectCategory=group)(objectClass=group)(distinguishedName=" + distinguishedName + "))"
            };
            ds.PageSize = 2;
            ds.SizeLimit = 1;
            ds.PropertiesToLoad.AddRange(props);

            var result = ds.FindOne();
            if (result != null)
            {
                var row = dt.NewRow();
                row["distname"] = result.Properties["distinguishedName"].Count > 0 ? result.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["groupname"] = result.Properties["sAMAccountName"].Count > 0 ? result.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                row["info"] = result.Properties["info"].Count > 0 ? result.Properties["info"][0]?.ToString() ?? "" : "";
                row["Описание"] = result.Properties["description"].Count > 0 ? result.Properties["description"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = result.Properties["displayName"].Count > 0 ? result.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Почта"] = result.Properties["mail"].Count > 0 ? result.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Когда"] = result.Properties["whenCreated"].Count > 0 && result.Properties["whenCreated"][0] != null
                    ? Convert.ToDateTime(result.Properties["whenCreated"][0]).ToLocalTime().ToString()
                    : "";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetMaillistInfoOnMail(string mail)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(mail)) return dt;
        mail = CanonicalizeStringForLdapFilter(mail);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        dt.Columns.Add("Логин");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Почта");

        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=eximMaillist)(mail={mail}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "cn", "displayName", "description", "mail" });

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Логин"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetGroupInfoOnCn(string cn)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(cn)) return dt;
        cn = CanonicalizeStringForLdapFilter(cn);

        dt.Columns.Add("Логин");
        dt.Columns.Add("Описание");

        try
        {
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = $"(&(objectClass=group)(cn={cn}*))";
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(new[] { "sAMAccountName", "description" });

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["sAMAccountName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["sAMAccountName"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public bool IsMaillistMember(string distinguishedName)
    {
        if (string.IsNullOrWhiteSpace(distinguishedName)) return false;

        try
        {
            using var entry = new DirectoryEntry("LDAP://" + Data.DC + distinguishedName);
            return entry.Properties["eximMaillistMember"].Count > 0;
        }
        catch { }
        return false;
    }

    public DataTable GetContainerInfo(string ou)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(ou)) return dt;

        var path = "LDAP://" + Data.DC + ou;
        var props = new[] { "ou", "description", "distinguishedName" };

        dt.Columns.Add("ou");
        dt.Columns.Add("description");
        dt.Columns.Add("distinguishedName");

        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.OneLevel,
                ReferralChasing = ReferralChasingOption.None,
                Filter = "(objectClass=organizationalUnit)"
            };
            ds.PropertiesToLoad.AddRange(props);

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["ou"] = sr.Properties["ou"].Count > 0 ? sr.Properties["ou"][0]?.ToString() ?? "" : "";
                row["description"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    public DataTable GetRepadminInfoAttributeMetaData(string login)
    {
        DataTable dataTable = new DataTable();
        try
        {
            login = CanonicalizeStringForLdapFilter(login);
            string path = "LDAP://" + Data.DC + Data.AdPath_Domain;
            uint rangeSize = 1000u;
            uint rangeStart = 0u;
            uint rangeEnd = rangeStart + (rangeSize - 1);
            bool hasMoreRanges = false;
            bool rangeComplete = false;
            List<string> metadataList = new List<string>();
            string attrName = "msDS-ReplAttributeMetaData;range=0-*";
            dataTable.Columns.Add("Атрибут");
            dataTable.Columns.Add("Контроллер домена");
            dataTable.Columns.Add("Изменён", typeof(DateTime));
            dataTable.Columns.Add("Изменений всего", typeof(int));
            using DirectoryEntry searchRoot = new DirectoryEntry(path);
            using DirectorySearcher directorySearcher = new DirectorySearcher(searchRoot);
            directorySearcher.SearchScope = SearchScope.Subtree;
            directorySearcher.ReferralChasing = ReferralChasingOption.None;
            directorySearcher.Filter = "(|(sAMAccountName=" + login + ")(cn=" + login + "))";
            do
            {
                string rangeName = hasMoreRanges ? $"msDS-ReplAttributeMetaData;range={rangeStart}-*" : $"msDS-ReplAttributeMetaData;range={rangeStart}-{rangeEnd}";
                directorySearcher.PropertiesToLoad.Clear();
                directorySearcher.PropertiesToLoad.Add(rangeName);
                SearchResult searchResult = directorySearcher.FindOne();
                if (searchResult == null)
                {
                    throw new InvalidOperationException("Объект в АД не найден.");
                }
                bool hasMetadata = false;
                foreach (object propertyName in searchResult.Properties.PropertyNames)
                {
                    if (propertyName.ToString().ToLower().Contains("msds-replattributemetadata"))
                    {
                        hasMetadata = true;
                        break;
                    }
                }
                if (!hasMetadata)
                {
                    throw new InvalidOperationException("Атрибут msDS-ReplAttributeMetaData пуст.");
                }
                if (searchResult.Properties.Contains(attrName))
                {
                    foreach (object item in searchResult.Properties[attrName])
                    {
                        metadataList.Add(item.ToString());
                    }
                    break;
                }
                if (searchResult.Properties.Contains(rangeName))
                {
                    foreach (object item in searchResult.Properties[rangeName])
                    {
                        metadataList.Add(item.ToString());
                    }
                    if (hasMoreRanges)
                    {
                        rangeComplete = true;
                    }
                }
                else
                {
                    hasMoreRanges = true;
                }
                if (!hasMoreRanges)
                {
                    rangeStart = rangeEnd + 1;
                    rangeEnd = rangeStart + (rangeSize - 1);
                }
            }
            while (!rangeComplete);
            XmlDocument xmlDocument = new XmlDocument();
            foreach (string metadataXml in metadataList)
            {
                xmlDocument.LoadXml(metadataXml);
                DataRow row = dataTable.NewRow();
                row["Атрибут"] = xmlDocument.DocumentElement["pszAttributeName"].InnerText;
                string innerText = xmlDocument.DocumentElement["pszLastOriginatingDsaDN"].InnerText;
                if (!string.IsNullOrWhiteSpace(innerText))
                {
                    innerText = innerText.Remove(0, 20);
                    innerText = innerText.Remove(innerText.IndexOf(","));
                    row["Контроллер домена"] = innerText;
                }
                row["Изменён"] = Convert.ToDateTime(xmlDocument.DocumentElement["ftimeLastOriginatingChange"].InnerText);
                row["Изменений всего"] = int.Parse(xmlDocument.DocumentElement["dwVersion"].InnerText);
                dataTable.Rows.Add(row);
            }
            dataTable.DefaultView.Sort = dataTable.Columns[0].ColumnName ?? "";
            dataTable = dataTable.DefaultView.ToTable();
        }
        catch
        {
        }
        return dataTable;
    }

    public DataTable GetUsersGroupComparison(string login1, string login2)
    {
        var dataTable = new DataTable();
        dataTable.Columns.Add("Группа");
        dataTable.Columns.Add("Только у " + login1);
        dataTable.Columns.Add("Только у " + login2);
        dataTable.Columns.Add("Общая");
        dataTable.Columns.Add("Описание");

        var props = new[] { "memberOf", "description" };
        var login1Canonical = CanonicalizeStringForLdapFilter(login1);
        var login2Canonical = CanonicalizeStringForLdapFilter(login2);

        using var ds1 = CreateSearcher();
        ds1.SearchScope = SearchScope.Subtree;
        ds1.Filter = $"(&(objectClass=user)(|(sAMAccountName={login1Canonical})(cn={login1Canonical})))";
        ds1.PropertiesToLoad.AddRange(props);
        SearchResult? result1 = ds1.FindOne();

        using var ds2 = CreateSearcher();
        ds2.SearchScope = SearchScope.Subtree;
        ds2.Filter = $"(&(objectClass=user)(|(sAMAccountName={login2Canonical})(cn={login2Canonical})))";
        ds2.PropertiesToLoad.AddRange(props);
        SearchResult? result2 = ds2.FindOne();

        var groups1 = new HashSet<string>();
        var groups2 = new HashSet<string>();

        if (result1?.Properties["memberOf"].Count > 0)
        {
            foreach (string g in result1.Properties["memberOf"].Cast<string>())
            {
                groups1.Add(g);
            }
        }

        if (result2?.Properties["memberOf"].Count > 0)
        {
            foreach (string g in result2.Properties["memberOf"].Cast<string>())
            {
                groups2.Add(g);
            }
        }

        var onlyIn1 = new HashSet<string>(groups1);
        onlyIn1.ExceptWith(groups2);

        var onlyIn2 = new HashSet<string>(groups2);
        onlyIn2.ExceptWith(groups1);

        var common = new HashSet<string>(groups1);
        common.IntersectWith(groups2);

        var allGroups = new HashSet<string>(groups1);
        allGroups.UnionWith(groups2);

        var groupInfoBatch = GetGroupsBatch(allGroups);

        var groupDescriptions = new Dictionary<string, string>();
        var groupDisplayNames = new Dictionary<string, string>();
        foreach (var dn in allGroups)
        {
            if (groupInfoBatch.TryGetValue(dn, out var info))
            {
                groupDescriptions[dn] = info.description;
                groupDisplayNames[dn] = !string.IsNullOrWhiteSpace(info.displayName) ? info.displayName : info.cn;
            }
            else
            {
                groupDescriptions[dn] = "";
                int commaIndex = dn.IndexOf(',');
                groupDisplayNames[dn] = commaIndex > 0 ? dn[3..commaIndex] : dn;
            }
        }

        var sortedAll = allGroups.OrderBy(x => groupDisplayNames[x]);
        foreach (string dn in sortedAll)
        {
            DataRow row = dataTable.NewRow();
            row["Группа"] = groupDisplayNames[dn];
            row["Только у " + login1] = onlyIn1.Contains(dn) ? "✓" : "";
            row["Только у " + login2] = onlyIn2.Contains(dn) ? "✓" : "";
            row["Общая"] = common.Contains(dn) ? "✓" : "";
            row["Описание"] = groupDescriptions[dn];
            dataTable.Rows.Add(row);
        }

        return dataTable;
    }

    public DataTable GetRepadminInfoValueMetaData(string login)
    {
        DataTable dataTable = new DataTable();
        try
        {
            login = CanonicalizeStringForLdapFilter(login);
            string path = "LDAP://" + Data.DC + Data.AdPath_Domain;
            uint rangeSize = 1000u;
            uint rangeStart = 0u;
            uint rangeEnd = rangeStart + (rangeSize - 1);
            bool hasMoreRanges = false;
            bool rangeComplete = false;
            List<string> metadataList = new List<string>();
            string attrName = "msDS-ReplValueMetaData;range=0-*";
            dataTable.Columns.Add("Атрибут");
            dataTable.Columns.Add("cn");
            dataTable.Columns.Add("Состояние");
            dataTable.Columns.Add("Контроллер домена");
            dataTable.Columns.Add("Добавлен впервые", typeof(DateTime));
            dataTable.Columns.Add("Крайняя операция", typeof(DateTime));
            dataTable.Columns.Add("Операций всего", typeof(int));
            dataTable.Columns.Add("distinguishedName");
            using DirectoryEntry searchRoot = new DirectoryEntry(path);
            using DirectorySearcher directorySearcher = new DirectorySearcher(searchRoot);
            directorySearcher.SearchScope = SearchScope.Subtree;
            directorySearcher.ReferralChasing = ReferralChasingOption.None;
            directorySearcher.Filter = "(|(sAMAccountName=" + login + ")(cn=" + login + "))";
            do
            {
                string rangeName = hasMoreRanges ? $"msDS-ReplValueMetaData;range={rangeStart}-*" : $"msDS-ReplValueMetaData;range={rangeStart}-{rangeEnd}";
                directorySearcher.PropertiesToLoad.Clear();
                directorySearcher.PropertiesToLoad.Add(rangeName);
                SearchResult searchResult = directorySearcher.FindOne();
                if (searchResult == null)
                {
                    throw new InvalidOperationException("Объект в АД не найден.");
                }
                bool hasMetadata = false;
                foreach (object propertyName in searchResult.Properties.PropertyNames)
                {
                    if (propertyName.ToString().ToLower().Contains("msds-replvaluemetadata"))
                    {
                        hasMetadata = true;
                        break;
                    }
                }
                if (!hasMetadata)
                {
                    throw new InvalidOperationException("Атрибут msDS-ReplValueMetaData пуст.");
                }
                if (searchResult.Properties.Contains(attrName))
                {
                    foreach (object item in searchResult.Properties[attrName])
                    {
                        metadataList.Add(item.ToString());
                    }
                    break;
                }
                if (searchResult.Properties.Contains(rangeName))
                {
                    foreach (object item in searchResult.Properties[rangeName])
                    {
                        metadataList.Add(item.ToString());
                    }
                    if (hasMoreRanges)
                    {
                        rangeComplete = true;
                    }
                }
                else
                {
                    hasMoreRanges = true;
                }
                if (!hasMoreRanges)
                {
                    rangeStart = rangeEnd + 1;
                    rangeEnd = rangeStart + (rangeSize - 1);
                }
            }
            while (!rangeComplete);
            XmlDocument xmlDocument = new XmlDocument();
            foreach (string metadataXml in metadataList)
            {
                xmlDocument.LoadXml(metadataXml);
                DataRow row = dataTable.NewRow();
                row["Атрибут"] = xmlDocument.DocumentElement["pszAttributeName"].InnerText;
                row["distinguishedName"] = xmlDocument.DocumentElement["pszObjectDn"].InnerText;
                if (xmlDocument.DocumentElement["ftimeDeleted"].InnerText.Equals("1601-01-01T00:00:00Z"))
                {
                    row["Состояние"] = "Присутствует";
                }
                else
                {
                    row["Состояние"] = "Отсутствует";
                }
                string innerText = xmlDocument.DocumentElement["pszLastOriginatingDsaDN"].InnerText;
                if (!string.IsNullOrWhiteSpace(innerText))
                {
                    innerText = innerText.Remove(0, 20);
                    innerText = innerText.Remove(innerText.IndexOf(","));
                    row["Контроллер домена"] = innerText;
                }
                row["Добавлен впервые"] = Convert.ToDateTime(xmlDocument.DocumentElement["ftimeCreated"].InnerText);
                row["Крайняя операция"] = Convert.ToDateTime(xmlDocument.DocumentElement["ftimeLastOriginatingChange"].InnerText);
                row["Операций всего"] = int.Parse(xmlDocument.DocumentElement["dwVersion"].InnerText);
                dataTable.Rows.Add(row);
            }
            foreach (DataRow row in dataTable.Rows)
            {
                string dn = row["distinguishedName"].ToString();
                if (dn.Contains("cn=delete"))
                {
                    row["cn"] = "Объект удален из AD";
                    continue;
                }
                string cn = dn.ToLower().Replace("cn=", "");
                int commaIndex = cn.IndexOf(",");
                row["cn"] = commaIndex > 0 ? cn.Remove(commaIndex) : cn;
            }
            dataTable.DefaultView.Sort = dataTable.Columns[0].ColumnName ?? "";
            dataTable = dataTable.DefaultView.ToTable();
        }
        catch
        {
        }
        return dataTable;
    }

    public DataTable GetMaillistMoreInfo(string login)
    {
        var dataTable = new DataTable();
        login = CanonicalizeStringForLdapFilter(login);
        
        var props = new[] 
        { 
            "displayName", "description", "mail", "distinguishedName", "createTimeStamp", 
            "modifyTimeStamp", "userAccountControl", "eximMaillistOwner", "cn",
            "eximCanReceiveFromAlien", "eximMaillistWhite" 
        };

        using var searcher = CreateSearcher();
        searcher.SearchScope = SearchScope.Subtree;
        searcher.Filter = $"(&(objectClass=eximMaillist)(|(sAMAccountName={login})(cn={login})))";
        searcher.PageSize = 301;
        searcher.SizeLimit = 300;
        searcher.PropertiesToLoad.AddRange(props);

        using var results = searcher.FindAll();
        
        dataTable.Columns.Add("Логин");
        dataTable.Columns.Add("Вывод. имя");
        dataTable.Columns.Add("Описание");
        dataTable.Columns.Add("Владелец");
        dataTable.Columns.Add("Почта");
        dataTable.Columns.Add("Exim - получать письма с внешних адресов");
        dataTable.Columns.Add("Exim - белый список");
        dataTable.Columns.Add("LDAP путь");
        dataTable.Columns.Add("Статус рассылки");
        dataTable.Columns.Add("Создана");
        dataTable.Columns.Add("Модифицирована");

        foreach (SearchResult sr in results)
        {
            var row = dataTable.NewRow();
            row["Логин"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
            row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
            row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
            
            var owners = new List<string>();
            foreach (string o in sr.Properties["eximMaillistOwner"].Cast<string>())
            {
                owners.Add(o);
            }
            row["Владелец"] = GetObjectInfo_WithDistinguishedName(owners);
            row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
            
            var canReceive = sr.Properties["eximCanReceiveFromAlien"].Count > 0 ? sr.Properties["eximCanReceiveFromAlien"][0]?.ToString() ?? "" : "";
            row["Exim - получать письма с внешних адресов"] = string.IsNullOrWhiteSpace(canReceive) || canReceive.Equals("false", StringComparison.OrdinalIgnoreCase)
                ? "Разрешено"
                : "Запрещено";
            
            var whitelist = new List<string>();
            if (sr.Properties["eximMaillistWhite"].Count > 0)
            {
                var parts = sr.Properties["eximMaillistWhite"][0]?.ToString()?.Split(new[] { "; " }, StringSplitOptions.RemoveEmptyEntries) ?? Array.Empty<string>();
                whitelist.AddRange(parts.Select(p => p ?? ""));
            }
            row["Exim - белый список"] = GetObjectInfo_WithMail(whitelist);
            row["LDAP путь"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
            
            var uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
            row["Статус рассылки"] = (uac & 2) != 0 ? "DISABLE" : "NORMAL";
            row["Создана"] = sr.Properties["createTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["createTimeStamp"][0]).ToLocalTime().ToString() : "";
            row["Модифицирована"] = sr.Properties["modifyTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["modifyTimeStamp"][0]).ToLocalTime().ToString() : "";
            
            dataTable.Rows.Add(row);
        }
        
        return dataTable;
    }

    public DataTable GetGroupMoreInfo(string login)
    {
        var dataTable = new DataTable();
        login = CanonicalizeStringForLdapFilter(login);

        var props = new[]
        {
            "sAMAccountName", "distinguishedName", "description", "msExchRequireAuthToSendTo", "mail",
            "createTimeStamp", "info", "displayName", "modifyTimeStamp", "groupType",
            "authOrig", "dLMemSubmitPerms", "msExchEnableModeration", "msExchModeratedByLink", "msExchBypassModerationLink"
        };

        using var ds = CreateSearcher();
        ds.SearchScope = SearchScope.Subtree;
        ds.Filter = $"(&(objectClass=group)(|(sAMAccountName={login})(cn={login})))";
        ds.PageSize = 301;
        ds.SizeLimit = 300;
        ds.PropertiesToLoad.AddRange(props);

        using var results = ds.FindAll();

        dataTable.Columns.Add("DN");
        dataTable.Columns.Add("Логин");
        dataTable.Columns.Add("Вывод. имя");
        dataTable.Columns.Add("Описание");
        dataTable.Columns.Add("Владелец");
        dataTable.Columns.Add("Тип");
        dataTable.Columns.Add("Почта");
        dataTable.Columns.Add("Exchange - получать письма с внешних адресов");
        dataTable.Columns.Add("Exchange - белый список");
        dataTable.Columns.Add("Модерация");
        dataTable.Columns.Add("Модератор");
        dataTable.Columns.Add("Вип отправитель, модерация не производится");
        dataTable.Columns.Add("LDAP путь");
        dataTable.Columns.Add("Статус группы");
        dataTable.Columns.Add("Создана");
        dataTable.Columns.Add("Модифицирована");

        foreach (SearchResult sr in results)
        {
            var row = dataTable.NewRow();
            row["DN"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
            row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
            row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
            row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
            row["Владелец"] = sr.Properties["info"].Count > 0 ? sr.Properties["info"][0]?.ToString() ?? "" : "";

            var groupType = sr.Properties["groupType"].Count > 0 ? Convert.ToInt64(sr.Properties["groupType"][0]) : 0L;
            row["Тип"] = (groupType & 0x80000000L) != 0 ? "Группа безопасности" : "Группа распространения";

            if (row["Тип"].ToString()!.Equals("Группа распространения"))
            {
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";

                var authToSend = sr.Properties["msExchRequireAuthToSendTo"].Count > 0 ? sr.Properties["msExchRequireAuthToSendTo"][0]?.ToString() ?? "" : "";
                row["Exchange - получать письма с внешних адресов"] = !string.IsNullOrWhiteSpace(authToSend) && authToSend.Equals("true", StringComparison.OrdinalIgnoreCase) ? "Запрещено" : "Разрешено";

                var whitelist = new List<string>();
                foreach (string? item in sr.Properties["authOrig"].Cast<string?>())
                {
                    whitelist.Add(item!);
                }
                foreach (string? item in sr.Properties["dLMemSubmitPerms"].Cast<string?>())
                {
                    whitelist.Add(item!);
                }
                row["Exchange - белый список"] = GetObjectInfo_WithDistinguishedName(whitelist);

                var moderationEnabled = sr.Properties["msExchEnableModeration"].Count > 0 ? sr.Properties["msExchEnableModeration"][0]?.ToString() ?? "" : "";
                if (!string.IsNullOrWhiteSpace(moderationEnabled) && moderationEnabled.Equals("true", StringComparison.OrdinalIgnoreCase))
                {
                    row["Модерация"] = "Включена";

                    var moderators = new List<string>();
                    foreach (string? item in sr.Properties["msExchModeratedByLink"].Cast<string?>())
                    {
                        moderators.Add(item!);
                    }
                    row["Модератор"] = GetObjectInfo_WithDistinguishedName(moderators);

                    var bypassList = new List<string>();
                    foreach (string? item in sr.Properties["msExchBypassModerationLink"].Cast<string?>())
                    {
                        bypassList.Add(item!);
                    }
                    row["Вип отправитель, модерация не производится"] = GetObjectInfo_WithDistinguishedName(bypassList);
                }
                else
                {
                    row["Модерация"] = "Выключена";
                }
            }
            else
            {
                row["Почта"] = "Недоступно для данного типа группы";
                row["Exchange - получать письма с внешних адресов"] = "Недоступно для данного типа группы";
                row["Exchange - белый список"] = "Недоступно для данного типа группы";
                row["Модерация"] = "Недоступно для данного типа группы";
                row["Модератор"] = "Недоступно для данного типа группы";
                row["Вип отправитель, модерация не производится"] = "Недоступно для данного типа группы";
            }

            row["LDAP путь"] = sr.Properties["distinguishedName"][0]?.ToString() ?? "";

            var uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
            row["Статус группы"] = (uac & 2) != 0 ? "DISABLE" : "NORMAL";

            row["Создана"] = sr.Properties["createTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["createTimeStamp"][0]).ToLocalTime().ToString() : "";
            row["Модифицирована"] = sr.Properties["modifyTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["modifyTimeStamp"][0]).ToLocalTime().ToString() : "";

            dataTable.Rows.Add(row);
        }
        
        return dataTable;
    }

    public (string cn, string displayName, string description) GetGroupInfoByDN(string distinguishedName)
    {
        if (string.IsNullOrWhiteSpace(distinguishedName))
            return ("", "", "");

        try
        {
            string path;
            if (distinguishedName.StartsWith("LDAP://", StringComparison.OrdinalIgnoreCase))
                path = distinguishedName;
            else if (distinguishedName.StartsWith("/"))
                path = "LDAP://" + Data.DC + distinguishedName;
            else
                path = "LDAP://" + Data.DC + "/" + distinguishedName;

            using var entry = new DirectoryEntry(path);
            var displayNameGroup = entry.Properties["displayName"].Count > 0 ? entry.Properties["displayName"][0]?.ToString() ?? "" : "";
            var cn = entry.Properties["cn"].Count > 0 ? entry.Properties["cn"][0]?.ToString() ?? "" : "";
            var finalName = !string.IsNullOrWhiteSpace(displayNameGroup) ? displayNameGroup : cn;
            var description = entry.Properties["description"].Count > 0 ? entry.Properties["description"][0]?.ToString() ?? "" : "";
            return (cn, finalName, description);
        }
        catch
        {
            return ("", "", "");
        }
    }

    public Dictionary<string, (string cn, string displayName, string description)> GetGroupsBatch(IEnumerable<string> distinguishedNames)
    {
        var results = new Dictionary<string, (string cn, string displayName, string description)>(StringComparer.OrdinalIgnoreCase);
        var dnsList = distinguishedNames.Where(d => !string.IsNullOrWhiteSpace(d)).ToList();
        
        if (dnsList.Count == 0)
            return results;

        try
        {
            string path = "LDAP://" + Data.DC + Data.AdPath_Domain;
            using var searchRoot = new DirectoryEntry(path);
            using var searcher = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None
            };

            var dnFilters = dnsList.Select(dn => EscapeLdapFilterValue(dn)).ToList();
            var filter = $"(&(objectClass=group)(|{string.Join("", dnFilters.Select(dn => $"(distinguishedName={dn})"))}))";
            searcher.Filter = filter;
            searcher.PropertiesToLoad.AddRange(new[] { "distinguishedName", "cn", "displayName", "description" });

            using var searchResults = searcher.FindAll();
            foreach (SearchResult sr in searchResults)
            {
                var dn = sr.Properties["distinguishedName"][0]?.ToString();
                if (string.IsNullOrWhiteSpace(dn))
                    continue;

                var cn = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                var displayName = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                var desc = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";

                results[dn] = (cn, displayName, desc);
            }
        }
        catch
        {
        }

        return results;
    }

    public List<string> GetUserTokenGroups(string distinguishedName)
    {
        var groups = new List<string>();
        if (string.IsNullOrWhiteSpace(distinguishedName))
            return groups;

        try
        {
            var path = "LDAP://" + Data.DC + "/" + distinguishedName;
            using var entry = new DirectoryEntry(path);
            if (entry.Properties["tokenGroups"].Count > 0)
            {
                foreach (byte[] sidBytes in entry.Properties["tokenGroups"])
                {
                    try
                    {
                        var sid = new System.Security.Principal.SecurityIdentifier(sidBytes, 0);
                        groups.Add(sid.Value);
                    }
                    catch { }
                }
            }
        }
        catch { }
        return groups;
    }

    public List<string> GetGroupNamesFromSIDs(List<string> sids)
    {
        var groups = new List<string>();
        foreach (var sid in sids)
        {
            try
            {
                var path = "LDAP://" + Data.DC + Data.AdPath_Domain;
                using var searchRoot = new DirectoryEntry(path);
                using var searcher = new DirectorySearcher(searchRoot)
                {
                    Filter = $"(objectSid={sid})",
                    ReferralChasing = ReferralChasingOption.None,
                    SearchScope = SearchScope.Subtree
                };
                searcher.PropertiesToLoad.Add("distinguishedName");
                var result = searcher.FindOne();
                if (result != null)
                {
                    var dn = result.Properties["distinguishedName"][0]?.ToString();
                    if (!string.IsNullOrEmpty(dn))
                        groups.Add(dn);
                }
            }
            catch { }
        }
        return groups;
    }

    public DataTable GetDynamicDistributionGroupInfo(string inParm, string type)
    {
        DataTable dataTable = new DataTable();
        inParm = CanonicalizeStringForLdapFilter(inParm);
        string filter = LdapSearch(inParm, type);
        string path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        string[] props = new string[8] { "cn", "displayName", "distinguishedName", "info", "mail", "managedBy", "msExchDynamicDLBaseDN", "msExchDynamicDLFilter" };

        using DirectoryEntry searchRoot = new DirectoryEntry(path);
        using DirectorySearcher directorySearcher = new DirectorySearcher(searchRoot)
        {
            SearchScope = SearchScope.Subtree,
            ReferralChasing = ReferralChasingOption.None,
            Filter = $"(&(objectClass=msExchDynamicDistributionList){filter})",
            PageSize = 51,
            SizeLimit = 50
        };
        directorySearcher.PropertiesToLoad.AddRange(props);

        using SearchResultCollection results = directorySearcher.FindAll();

        dataTable.Columns.Add("Логин");
        dataTable.Columns.Add("distinguishedName");
        dataTable.Columns.Add("Вывод. имя");
        dataTable.Columns.Add("Описание");
        dataTable.Columns.Add("Владелец");
        dataTable.Columns.Add("RecipientContainer");
        dataTable.Columns.Add("LdapRecipientFilter");
        dataTable.Columns.Add("Почта");

        foreach (SearchResult sr in results)
        {
            DataRow row = dataTable.NewRow();
            row["Логин"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
            row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
            row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
            row["Описание"] = sr.Properties["info"].Count > 0 ? sr.Properties["info"][0]?.ToString() ?? "" : "";

            var managedByList = new List<string>();
            foreach (object item in sr.Properties["managedBy"])
            {
                managedByList.Add(item?.ToString() ?? string.Empty);
            }
            row["Владелец"] = GetObjectInfo_WithDistinguishedName(managedByList);
            row["RecipientContainer"] = sr.Properties["msExchDynamicDLBaseDN"].Count > 0 ? sr.Properties["msExchDynamicDLBaseDN"][0]?.ToString() ?? "" : "";
            row["LdapRecipientFilter"] = sr.Properties["msExchDynamicDLFilter"].Count > 0 ? sr.Properties["msExchDynamicDLFilter"][0]?.ToString() ?? "" : "";
            row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
            dataTable.Rows.Add(row);
        }

        return dataTable;
    }

    public DataTable GetDynamicDistributionGroupMoreInfo(string login)
    {
        DataTable dataTable = new DataTable();
        login = CanonicalizeStringForLdapFilter(login);

        string[] props = new string[17]
        {
            "cn", "displayName", "mail", "distinguishedName", "msExchRequireAuthToSendTo", "managedBy", "authOrig", "createTimeStamp", "modifyTimeStamp", "info",
            "msExchEnableModeration", "msExchModeratedByLink", "msExchBypassModerationLink", "msExchDynamicDLBaseDN", "msExchDynamicDLFilter", "msExchQueryFilter", "dLMemSubmitPerms"
        };

        using DirectorySearcher directorySearcher = CreateSearcher();
        directorySearcher.SearchScope = SearchScope.Subtree;
        directorySearcher.Filter = $"(&(objectClass=msExchDynamicDistributionList)(|(sAMAccountName={login})(cn={login})))";
        directorySearcher.PageSize = 301;
        directorySearcher.SizeLimit = 300;
        directorySearcher.PropertiesToLoad.AddRange(props);

        using SearchResultCollection results = directorySearcher.FindAll();

        dataTable.Columns.Add("Логин");
        dataTable.Columns.Add("Вывод. имя");
        dataTable.Columns.Add("Описание");
        dataTable.Columns.Add("Владелец");
        dataTable.Columns.Add("Почта");
        dataTable.Columns.Add("Получать письма с внешних адресов");
        dataTable.Columns.Add("Белый список");
        dataTable.Columns.Add("Модерация");
        dataTable.Columns.Add("Модератор");
        dataTable.Columns.Add("Вип отправитель, модерация не производится");
        dataTable.Columns.Add("LDAP путь");
        dataTable.Columns.Add("RecipientContainer");
        dataTable.Columns.Add("RecipientFilter");
        dataTable.Columns.Add("Статус динамической рассылки");
        dataTable.Columns.Add("Создана");
        dataTable.Columns.Add("Модифицирована");

        foreach (SearchResult sr in results)
        {
            DataRow row = dataTable.NewRow();
            row["Логин"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
            row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
            row["Описание"] = sr.Properties["info"].Count > 0 ? sr.Properties["info"][0]?.ToString() ?? "" : "";

            var managedByList = new List<string>();
            foreach (object item in sr.Properties["managedBy"])
            {
                managedByList.Add(item?.ToString() ?? string.Empty);
            }
            row["Владелец"] = GetObjectInfo_WithDistinguishedName(managedByList);
            row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";

            string requireAuth = sr.Properties["msExchRequireAuthToSendTo"].Count > 0 ? sr.Properties["msExchRequireAuthToSendTo"][0]?.ToString() ?? string.Empty : string.Empty;
            row["Получать письма с внешних адресов"] = !string.IsNullOrWhiteSpace(requireAuth) && requireAuth.Equals("true", StringComparison.OrdinalIgnoreCase) ? "Запрещено" : "Разрешено";

            var whitelist = new List<string>();
            foreach (object item in sr.Properties["authOrig"])
            {
                whitelist.Add(item?.ToString() ?? string.Empty);
            }
            foreach (object item in sr.Properties["dLMemSubmitPerms"])
            {
                whitelist.Add(item?.ToString() ?? string.Empty);
            }
            row["Белый список"] = GetObjectInfo_WithDistinguishedName(whitelist);

            string moderationEnabled = sr.Properties["msExchEnableModeration"].Count > 0 ? sr.Properties["msExchEnableModeration"][0]?.ToString() ?? string.Empty : string.Empty;
            if (!string.IsNullOrWhiteSpace(moderationEnabled) && moderationEnabled.Equals("true", StringComparison.OrdinalIgnoreCase))
            {
                row["Модерация"] = "Включена";
                var moderators = new List<string>();
                foreach (object item in sr.Properties["msExchModeratedByLink"])
                {
                    moderators.Add(item?.ToString() ?? string.Empty);
                }
                row["Модератор"] = GetObjectInfo_WithDistinguishedName(moderators);
                var bypassModeration = new List<string>();
                foreach (object item in sr.Properties["msExchBypassModerationLink"])
                {
                    bypassModeration.Add(item?.ToString() ?? string.Empty);
                }
                row["Вип отправитель, модерация не производится"] = GetObjectInfo_WithDistinguishedName(bypassModeration);
            }
            else
            {
                row["Модерация"] = "Выключена";
            }

            row["LDAP путь"] = sr.Properties["distinguishedName"][0]?.ToString() ?? "";
            row["RecipientContainer"] = sr.Properties["msExchDynamicDLBaseDN"].Count > 0 ? sr.Properties["msExchDynamicDLBaseDN"][0]?.ToString() ?? "" : "";
            row["RecipientFilter"] = sr.Properties["msExchDynamicDLFilter"].Count > 0 ? sr.Properties["msExchDynamicDLFilter"][0]?.ToString() ?? "" : "";

            int uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
            row["Статус динамической рассылки"] = (uac & 2) != 0 ? "DISABLE" : "NORMAL";
            row["Создана"] = sr.Properties["createTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["createTimeStamp"][0]).ToLocalTime().ToString() : "";
            row["Модифицирована"] = sr.Properties["modifyTimeStamp"].Count > 0 ? Convert.ToDateTime(sr.Properties["modifyTimeStamp"][0]).ToLocalTime().ToString() : "";
            dataTable.Rows.Add(row);
        }

        return dataTable;
    }

    public DataTable GetUserInfo(string distinguishedName)
    {
        var dataTable = new DataTable();
        var path = "LDAP://" + Data.DC + distinguishedName;

        try
        {
            using var directoryEntry = new DirectoryEntry(path);
            directoryEntry.RefreshCache(new[] { "guidMD", "sAMAccountName", "objectClass", "sn", "givenName", "middleName", "telephoneNumber", "mail", "eximMailhost", "title", "department", "company", "extensionAttribute10", "mDBUseDefaults", "mDBStorageQuota", "mDBOverQuotaLimit", "mDBOverHardQuotaLimit", "extensionAttribute14", "userAccountControl", "extensionAttribute8", "pwdLastSet", "LockedOut" });

            dataTable.Columns.Add("СУМД", typeof(bool));
            dataTable.Columns["СУМД"].ReadOnly = true;
            dataTable.Columns.Add("Логин");
            dataTable.Columns.Add("ФИО");
            dataTable.Columns.Add("Телефон");
            dataTable.Columns.Add("Почта");
            dataTable.Columns.Add("Почтовый сервер");
            dataTable.Columns.Add("Должность");
            dataTable.Columns.Add("Отдел");
            dataTable.Columns.Add("Компания");
            dataTable.Columns.Add("Статус миграции в Exchange");
            dataTable.Columns.Add("Квота - настройки базы");
            dataTable.Columns.Add("Квота - предупреждение");
            dataTable.Columns.Add("Квота - запрет отправки");
            dataTable.Columns.Add("Квота - запрет отправки/получения");
            dataTable.Columns.Add("Запрос на изменение квоты");
            dataTable.Columns.Add("Статус УЗ");

            var row = dataTable.NewRow();
            row["СУМД"] = directoryEntry.Properties["guidMD"].Count > 0;
            row["Логин"] = directoryEntry.Properties["sAMAccountName"].Count > 0 ? directoryEntry.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";

            foreach (var item in directoryEntry.Properties["objectClass"])
            {
                var objClass = item?.ToString()?.ToLowerInvariant() ?? string.Empty;
                if (objClass == "eximmaillist")
                {
                    row["Логин"] = directoryEntry.Properties["cn"].Count > 0 ? directoryEntry.Properties["cn"][0]?.ToString() ?? "" : "";
                }
            }

            var lastName = directoryEntry.Properties["sn"].Count > 0 ? directoryEntry.Properties["sn"][0]?.ToString() ?? "" : "";
            var firstName = directoryEntry.Properties["givenName"].Count > 0 ? directoryEntry.Properties["givenName"][0]?.ToString() ?? "" : "";
            var middleName = directoryEntry.Properties["middleName"].Count > 0 ? directoryEntry.Properties["middleName"][0]?.ToString() ?? "" : "";
            row["ФИО"] = $"{lastName} {firstName} {middleName}".Trim();

            row["Телефон"] = directoryEntry.Properties["telephoneNumber"].Count > 0 ? directoryEntry.Properties["telephoneNumber"][0]?.ToString() ?? "" : "";
            row["Почта"] = directoryEntry.Properties["mail"].Count > 0 ? directoryEntry.Properties["mail"][0]?.ToString() ?? "" : "";
            row["Почтовый сервер"] = directoryEntry.Properties["eximMailhost"].Count > 0 ? directoryEntry.Properties["eximMailhost"][0]?.ToString() ?? "" : "";
            row["Должность"] = directoryEntry.Properties["title"].Count > 0 ? directoryEntry.Properties["title"][0]?.ToString() ?? "" : "";
            row["Отдел"] = directoryEntry.Properties["department"].Count > 0 ? directoryEntry.Properties["department"][0]?.ToString() ?? "" : "";
            row["Компания"] = directoryEntry.Properties["company"].Count > 0 ? directoryEntry.Properties["company"][0]?.ToString() ?? "" : "";
            row["Статус миграции в Exchange"] = directoryEntry.Properties["extensionAttribute10"].Count > 0 ? directoryEntry.Properties["extensionAttribute10"][0]?.ToString() ?? "" : "";

            if (directoryEntry.Properties["mDBUseDefaults"].Count > 0)
            {
                row["Квота - настройки базы"] = Convert.ToBoolean(directoryEntry.Properties["mDBUseDefaults"][0]?.ToString() ?? "false") ? "Базовые настройки" : "Пользовательские настройки";

                if (!Convert.ToBoolean(directoryEntry.Properties["mDBUseDefaults"][0]?.ToString() ?? "false"))
                {
                    row["Квота - предупреждение"] = directoryEntry.Properties["mDBStorageQuota"].Count > 0
                        ? $"{Convert.ToDouble(directoryEntry.Properties["mDBStorageQuota"][0]) / 1024.0 / 1024.0:F2} МБ"
                        : "unlimited";
                    row["Квота - запрет отправки"] = directoryEntry.Properties["mDBOverQuotaLimit"].Count > 0
                        ? $"{Convert.ToDouble(directoryEntry.Properties["mDBOverQuotaLimit"][0]) / 1024.0 / 1024.0:F2} МБ"
                        : "unlimited";
                    row["Квота - запрет отправки/получения"] = directoryEntry.Properties["mDBOverHardQuotaLimit"].Count > 0
                        ? $"{Convert.ToDouble(directoryEntry.Properties["mDBOverHardQuotaLimit"][0]) / 1024.0 / 1024.0:F2} МБ"
                        : "unlimited";
                    row["Запрос на изменение квоты"] = directoryEntry.Properties["extensionAttribute14"].Count > 0 ? directoryEntry.Properties["extensionAttribute14"][0]?.ToString() ?? "" : "";
                }
                else
                {
                    row["Квота - предупреждение"] = "N/D";
                    row["Квота - запрет отправки"] = "N/D";
                    row["Квота - запрет отправки/получения"] = "N/D";
                    row["Запрос на изменение квоты"] = "N/D";
                }
            }
            else
            {
                row["Квота - настройки базы"] = "N/D";
                row["Квота - предупреждение"] = "N/D";
                row["Квота - запрет отправки"] = "N/D";
                row["Квота - запрет отправки/получения"] = "N/D";
                row["Запрос на изменение квоты"] = "N/D";
            }

            var userAccountControl = directoryEntry.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(directoryEntry.Properties["userAccountControl"][0]) : 0;
            var kadroviyStatus = directoryEntry.Properties["extensionAttribute8"].Count > 0 ? directoryEntry.Properties["extensionAttribute8"][0]?.ToString() ?? "" : "";

            string passwordDaysStr;
            long pwdExpiryTime = 0;

            try
            {
                using var expirySearcher = new DirectorySearcher(new DirectoryEntry("LDAP://" + Data.DC + Data.AdPath_Domain));
                expirySearcher.ReferralChasing = ReferralChasingOption.None;
                expirySearcher.Filter = $"(distinguishedName={distinguishedName.Replace("=", "\\=").Replace(",", "\\,")})";
                expirySearcher.PropertiesToLoad.Add("msDS-UserPasswordExpiryTimeComputed");
                var expiryResult = expirySearcher.FindOne();

                if (expiryResult != null && expiryResult.Properties["msDS-UserPasswordExpiryTimeComputed"].Count > 0)
                {
                    pwdExpiryTime = Convert.ToInt64(expiryResult.Properties["msDS-UserPasswordExpiryTimeComputed"][0]?.ToString() ?? "0");
                }
            }
            catch { }

            if (pwdExpiryTime == 0)
            {
                passwordDaysStr = "Пароль - требует смены";
            }
            else if (pwdExpiryTime == -1)
            {
                passwordDaysStr = "Пароль - не установлен";
            }
            else
            {
                var expiryDate = SafeFromFileTimeUtc(pwdExpiryTime)?.ToLocalTime();
                if (expiryDate.HasValue)
                {
                    var timeLeft = expiryDate.Value - DateTime.Now;
                    if (timeLeft.TotalMilliseconds < 0)
                    {
                        passwordDaysStr = "Пароль истёк!";
                    }
                    else if (timeLeft.TotalDays < 1)
                    {
                        int hours = (int)timeLeft.TotalHours;
                        int minutes = timeLeft.Minutes;
                        if (hours == 0 && minutes > 0)
                        {
                            passwordDaysStr = $"Пароль - осталось {minutes} {GetMinutesWord(minutes)}";
                        }
                        else if (minutes == 0 && hours > 0)
                        {
                            passwordDaysStr = $"Пароль - осталось {hours} {GetHoursWord(hours)}";
                        }
                        else if (hours > 0 && minutes > 0)
                        {
                            passwordDaysStr = $"Пароль - осталось {hours} {GetHoursWord(hours)} {minutes} {GetMinutesWord(minutes)}";
                        }
                        else
                        {
                            passwordDaysStr = "Пароль истекает сегодня";
                        }
                    }
                    else
                    {
                        int daysUntilExpiry = (int)timeLeft.TotalDays;
                        passwordDaysStr = $"Пароль - осталось {daysUntilExpiry} {GetDaysWord(daysUntilExpiry)}";
                    }
                }
                else
                {
                    passwordDaysStr = "N/D";
                }
            }

            string lockedOutStr;
            if (directoryEntry.Properties["LockedOut"].Count > 0)
            {
                var isLockedOut = Convert.ToBoolean(directoryEntry.Properties["LockedOut"][0]);
                lockedOutStr = isLockedOut ? "УЗ - заблокирована" : "УЗ - нет блокировки";
            }
            else
            {
                lockedOutStr = "УЗ - нет блокировки";
            }

            var kadroviyStatusStr = !string.IsNullOrWhiteSpace(kadroviyStatus) ? $"HR статус - {kadroviyStatus}" : "HR статус - Работает";

            if ((userAccountControl & 2) != 0)
            {
                row["Статус УЗ"] = $"DISABLE, {kadroviyStatusStr}";
            }
            else
            {
                var parts = new[] { "NORMAL", kadroviyStatusStr, passwordDaysStr, lockedOutStr };
                row["Статус УЗ"] = string.Join(", ", parts);
            }

            dataTable.Rows.Add(row);
        }
        catch
        {
        }
        return dataTable;
    }
    public DataTable Fast_GetComputerInfo(string Comp)
    {
        DataTable dataTable = new DataTable();
        Comp = CanonicalizeStringForLdapFilter(Comp);
        string path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            string[] props = new string[2] { "cn", "description" };

            using DirectoryEntry searchRoot = new DirectoryEntry(path);
            using DirectorySearcher directorySearcher = new DirectorySearcher(searchRoot);
            directorySearcher.SearchScope = SearchScope.Subtree;
            directorySearcher.ReferralChasing = ReferralChasingOption.None;
            directorySearcher.Filter = $"(&(objectClass=computer)(objectCategory=computer)(cn={Comp}*))";
            directorySearcher.PageSize = 51;
            directorySearcher.SizeLimit = 50;
            directorySearcher.PropertiesToLoad.AddRange(props);

            using SearchResultCollection results = directorySearcher.FindAll();

            dataTable.Columns.Add("Логин");
            dataTable.Columns.Add("Вывод. имя");
            dataTable.Columns.Add("Описание");

            foreach (SearchResult sr in results)
            {
                if (sr.Properties["cn"].Count > 0)
                {
                    DataRow row = dataTable.NewRow();
                    row["Логин"] = sr.Properties["cn"][0]?.ToString() ?? "";
                    row["Вывод. имя"] = sr.Properties["cn"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dataTable.Rows.Add(row);
                }
            }
        }
        catch
        {
        }

        return dataTable;
    }

    public DataTable GetDynamicDistributionGroupMembers(string recipientContainer, string ldapRecipientFilter)
    {
        var dt = new DataTable();
        dt.Columns.Add("СУМД", typeof(bool));
        dt.Columns["СУМД"].DefaultValue = false;
        dt.Columns["СУМД"].ReadOnly = true;
        dt.Columns.Add("Логин");
        dt.Columns.Add("ФИО");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Почта");
        dt.Columns.Add("Почтовый сервер");
        dt.Columns.Add("Должность");
        dt.Columns.Add("Отдел");
        dt.Columns.Add("Компания");
        dt.Columns.Add("Описание");
        dt.Columns.Add("Статус миграции в Exchange");
        dt.Columns.Add("Статус УЗ");
        dt.Columns.Add("distinguishedName");

        var props = new[] { "sAMAccountName", "userAccountControl", "guidMD", "sn", "givenName", "middleName", "mail", "title", "department", "company", "distinguishedName", "extensionAttribute10", "eximMailhost", "description", "displayName", "extensionAttribute8" };

        try
        {
            using var searchRoot = new DirectoryEntry("LDAP://" + Data.DC + "/" + recipientContainer);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = ldapRecipientFilter
            };
            ds.PageSize = 100;
            ds.PropertiesToLoad.AddRange(props);

            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Логин"] = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";

                var lastName = sr.Properties["sn"].Count > 0 ? sr.Properties["sn"][0]?.ToString() + " " : "";
                var firstName = sr.Properties["givenName"].Count > 0 ? sr.Properties["givenName"][0]?.ToString() + " " : "";
                var middleName = sr.Properties["middleName"].Count > 0 ? sr.Properties["middleName"][0]?.ToString() : "";
                row["ФИО"] = (lastName + firstName + middleName).Trim();

                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Почта"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                row["Почтовый сервер"] = sr.Properties["eximMailhost"].Count > 0 ? sr.Properties["eximMailhost"][0]?.ToString() ?? "" : "";
                row["Должность"] = sr.Properties["title"].Count > 0 ? sr.Properties["title"][0]?.ToString() ?? "" : "";
                row["Отдел"] = sr.Properties["department"].Count > 0 ? sr.Properties["department"][0]?.ToString() ?? "" : "";
                row["Компания"] = sr.Properties["company"].Count > 0 ? sr.Properties["company"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                row["distinguishedName"] = sr.Properties["distinguishedName"].Count > 0 ? sr.Properties["distinguishedName"][0]?.ToString() ?? "" : "";
                row["Статус миграции в Exchange"] = sr.Properties["extensionAttribute10"].Count > 0 ? sr.Properties["extensionAttribute10"][0]?.ToString() ?? "" : "";

                var uac = sr.Properties["userAccountControl"].Count > 0 ? Convert.ToInt32(sr.Properties["userAccountControl"][0]) : 0;
                var hrStatus = sr.Properties["extensionAttribute8"].Count > 0 ? sr.Properties["extensionAttribute8"][0]?.ToString() ?? "" : "";
                row["Статус УЗ"] = (uac & 2) != 0
                    ? $"DISABLE (HR статус - {hrStatus})"
                    : $"NORMAL (HR статус - {hrStatus})";

                row["СУМД"] = sr.Properties["guidMD"].Count > 0;
                dt.Rows.Add(row);
            }
        }
        catch { return null!; }
        return dt;
    }

    public bool GetDynamicDistributionGroupMembersCheck(string recipientContainer, string ldapRecipientFilter)
    {
        var props = new[] { "distinguishedName" };
        try
        {
            using var searchRoot = new DirectoryEntry("LDAP://" + Data.DC + "/" + recipientContainer);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = ldapRecipientFilter
            };
            ds.SizeLimit = 1;
            ds.PropertiesToLoad.AddRange(props);

            using var results = ds.FindAll();
            return results != null && results.Count > 0;
        }
        catch { }
        return false;
    }

    public async Task<string> GetRetentionPolicyAsync(string email)
    {
        if (string.IsNullOrWhiteSpace(email))
            return string.Empty;

        var emailAddress = email.Contains('@') ? email : $"{email}@magnit.ru";

        return await Task.Run(() =>
        {
            var tempFile = Path.Combine(Path.GetTempPath(), $"ggbm_rp_{Guid.NewGuid()}.ps1");
            try
            {
                var result = RunRetentionPolicyScript(emailAddress, tempFile);
                return result;
            }
            catch { }
            finally
            {
                try { if (File.Exists(tempFile)) File.Delete(tempFile); } catch { }
            }
            return string.Empty;
        });
    }

    private static string RunRetentionPolicyScript(string email, string tempFile)
    {
        var script = $@"
$ErrorActionPreference = 'SilentlyContinue'
try {{
    $session = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -AllowRedirection -SessionOption (New-PSSessionOption -UICulture 'ru-RU') -ErrorAction Stop
    $mbx = Invoke-Command -Session $session -ScriptBlock {{ Get-Mailbox -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
    if ($null -ne $mbx -and $null -ne $mbx.RetentionPolicy) {{
        $rpName = ""$($mbx.RetentionPolicy)""
        $rp = Invoke-Command -Session $session -ScriptBlock {{ Get-RetentionPolicy -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList $rpName
        if ($null -ne $rp) {{
            Write-Output ""$($rp.Name)""
        }}
    }}
    Remove-PSSession $session
}} catch {{
    try {{ Remove-PSSession $session }} catch {{ }}
    Write-Output ''
}}
";
        try
        {
            File.WriteAllText(tempFile, script, Encoding.UTF8);
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = $"-ExecutionPolicy Bypass -NoProfile -File \"{tempFile}\"",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc == null) return string.Empty;
            var output = proc.StandardOutput.ReadToEnd();
            proc.WaitForExit(30000);
            return output.Trim();
        }
        catch { return string.Empty; }
    }

    public async Task<string> GetMailboxSizeAsync(string userLogin)
    {
        if (string.IsNullOrWhiteSpace(userLogin))
            return string.Empty;

        var email = userLogin.Contains('@') ? userLogin : $"{userLogin}@magnit.ru";

        return await Task.Run(() =>
        {
            var tempFile = Path.Combine(Path.GetTempPath(), $"ggbm_quota_{Guid.NewGuid()}.ps1");
            try
            {
                var (result, _) = RunExchangeQuotaScript(email, tempFile);
                if (!string.IsNullOrEmpty(result))
                    return result;

                if (FixWSMANSpnPrefix())
                {
                    Thread.Sleep(1000);
                    var (result2, _) = RunExchangeQuotaScript(email, tempFile);
                    if (!string.IsNullOrEmpty(result2))
                        return result2;
                }
            }
            catch { }
            finally
            {
                try { if (File.Exists(tempFile)) File.Delete(tempFile); } catch { }
            }
            return string.Empty;
        });
    }

    private static (string result, bool isError) RunExchangeQuotaScript(string email, string tempFile)
    {
        var script = $@"
$ErrorActionPreference = 'Stop'
try {{
    $session = New-PSSession -ConfigurationName Microsoft.Exchange -ConnectionUri 'http://mail.magnit.ru/Powershell' -Authentication Kerberos -AllowRedirection -SessionOption (New-PSSessionOption -UICulture 'ru-RU') -ErrorAction Stop
    $mbx = Invoke-Command -Session $session -ScriptBlock {{ Get-Mailbox -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList '{email}'
    if ($null -eq $mbx) {{ Remove-PSSession $session; return 'Error: Mailbox not found|False' }}
    $dn = ""$($mbx.DistinguishedName)""
    $stat = Invoke-Command -Session $session -ScriptBlock {{ Get-MailboxStatistics -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList $dn
    $region = Invoke-Command -Session $session -ScriptBlock {{ Get-MailboxRegion -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList $dn
    $rpName = ""$($mbx.RetentionPolicy)""
    $rp = Invoke-Command -Session $session -ScriptBlock {{ Get-RetentionPolicy -Identity $args[0] -ErrorAction SilentlyContinue }} -ArgumentList $rpName
    Remove-PSSession $session
    
    $serverName = ""$($mbx.ServerName)""
    $regionName = if ($region) {{ ""$($region.Name)"" }} else {{ '' }}
    $retentionName = if ($rp) {{ ""$($rp.Name)"" }} else {{ '' }}
    $fullSize = ""$($stat.TotalItemSize)""
    $sizeGB = 0
    if ($fullSize -match '\(([\d,\s]+)\s*bytes\)') {{
        $bytesStr = $matches[1] -replace '[,\s]', ''
        $sizeGB = [math]::Round([long]$bytesStr / 1GB, 2)
    }}
    ""{email}|"" + $serverName + ""."" + $regionName + ""."" + $retentionName + ""|"" + $sizeGB
}} catch {{
    try {{ Remove-PSSession $session }} catch {{ }}
    return ""Error: $($_.Exception.Message)|False""
}}
";
        try
        {
            File.WriteAllText(tempFile, script, Encoding.UTF8);
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = $"-ExecutionPolicy Bypass -NoProfile -File \"{tempFile}\"",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc == null) return (string.Empty, false);
            var output = proc.StandardOutput.ReadToEnd();
            var error = proc.StandardError.ReadToEnd();
            proc.WaitForExit(30000);
            return (output.Trim(), !string.IsNullOrEmpty(error));
        }
        catch { return (string.Empty, true); }
    }

    private static bool FixWSMANSpnPrefix()
    {
        try
        {
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = "setspn",
                Arguments = "/Q host/mail.magnit.ru",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                CreateNoWindow = true
            };
            using var proc = System.Diagnostics.Process.Start(psi);
            if (proc == null) return false;
            var output = proc.StandardOutput.ReadToEnd();
            proc.WaitForExit(10000);
            return output.Contains("mail.magnit.ru") || output.Contains("MACHIT01");
        }
        catch { return false; }
    }

    private DataTable GetOwnerResources_Maillist(string distinguishedName)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(distinguishedName)) return dt;
        
        dt.Columns.Add("Объект");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        
        var props = new[] { "cn", "displayName", "description", "mail" };
        var path = $"LDAP://{Data.DC}/{Data.AdPath_Domain}";
        
        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.Subordinate,
                Filter = $"(&(objectClass=user)(manager={distinguishedName}))"
            };
            ds.PropertiesToLoad.AddRange(props);
            
            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Объект"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    private DataTable GetOwnerResources_DinamicDistributionGroup(string distinguishedName, string fio)
    {
        var dt = new DataTable();
        dt.Columns.Add("Объект");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        
        var props = new[] { "cn", "displayName", "description", "mail" };
        var path = $"LDAP://{Data.DC}/{Data.AdPath_Domain}";
        
        var filter = distinguishedName != null 
            ? $"(&(objectClass=msExchDynamicDistributionList)(managedBy={distinguishedName}))"
            : $"(&(objectClass=msExchDynamicDistributionList)(info=*{fio}*))";
        
        try
        {
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.Subordinate,
                Filter = filter
            };
            ds.PropertiesToLoad.AddRange(props);
            
            foreach (SearchResult sr in ds.FindAll())
            {
                var row = dt.NewRow();
                row["Объект"] = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                row["Вывод. имя"] = sr.Properties["displayName"].Count > 0 ? sr.Properties["displayName"][0]?.ToString() ?? "" : "";
                row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                dt.Rows.Add(row);
            }
        }
        catch { }
        return dt;
    }

    private DataTable GetOwnerResources_GroupBox(string fio)
    {
        var dt = new DataTable();
        dt.Columns.Add("Объект");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        
        if (string.IsNullOrWhiteSpace(fio))
        {
            return dt;
        }
        
        try
        {
            var filter = $"(&(objectClass=user)(objectCategory=person)(cn=m_*)(eximAdminDescription=*))";
            var props = new[] { "mail", "eximAdminDescription", "displayname", "description" };
            
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = filter;
            ds.PageSize = 50;
            ds.PropertiesToLoad.AddRange(props);
            
            var results = ds.FindAll();
            
            var fioLower = fio.ToLower();
            var matchCount = 0;
            foreach (SearchResult sr in results)
            {
                var eximDesc = sr.Properties["eximAdminDescription"].Count > 0 
                    ? sr.Properties["eximAdminDescription"][0]?.ToString() ?? "" : "";
                
                if (!string.IsNullOrEmpty(eximDesc) && eximDesc.ToLower().Contains(fioLower))
                {
                    matchCount++;
                    var row = dt.NewRow();
                    row["Объект"] = sr.Properties["mail"].Count > 0 ? sr.Properties["mail"][0]?.ToString() ?? "" : "";
                    row["Вывод. имя"] = sr.Properties["displayname"].Count > 0 ? sr.Properties["displayname"][0]?.ToString() ?? "" : "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch
        {
        }
        return dt;
    }

    private DataTable GetOwnerResources_ServiceUz(string fio)
    {
        var dt = new DataTable();
        dt.Columns.Add("Объект");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        
        if (string.IsNullOrWhiteSpace(fio))
        {
            return dt;
        }
        
        try
        {
            var filter = $"(&(objectClass=user)(objectCategory=person)(!guid1C=*)(!middleName=*)(|(displayName=*{CanonicalizeStringForLdapFilter(fio)}*)(description=*{CanonicalizeStringForLdapFilter(fio)}*)))";
            var props = new[] { "sAMAccountName", "description", "displayname" };
            
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = filter;
            ds.PageSize = 50;
            ds.PropertiesToLoad.AddRange(props);
            
            var results = ds.FindAll();
            
            foreach (SearchResult sr in results)
            {
                var sAMAccountName = sr.Properties["sAMAccountName"].Count > 0 ? sr.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
                var description = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                var displayName = sr.Properties["displayname"].Count > 0 ? sr.Properties["displayname"][0]?.ToString() ?? "" : "";
                
                if (!string.IsNullOrWhiteSpace(sAMAccountName) && !sAMAccountName.Equals(fio))
                {
                    var row = dt.NewRow();
                    row["Объект"] = sAMAccountName;
                    row["Вывод. имя"] = displayName;
                    row["Описание"] = description;
                    dt.Rows.Add(row);
                }
            }
        }
        catch
        {
        }
        return dt;
    }

    private DataTable GetOwnerResources_Group(string fio)
    {
        var dt = new DataTable();
        dt.Columns.Add("Объект");
        dt.Columns.Add("Вывод. имя");
        dt.Columns.Add("Описание");
        
        if (string.IsNullOrWhiteSpace(fio))
        {
            return dt;
        }
        
        try
        {
            var filter = $"(&(objectClass=group)(objectCategory=group)(info=*{CanonicalizeStringForLdapFilter(fio)}*))";
            var props = new[] { "cn", "description" };
            
            using var ds = CreateSearcher();
            ds.SearchScope = SearchScope.Subtree;
            ds.Filter = filter;
            ds.PageSize = 50;
            ds.PropertiesToLoad.AddRange(props);
            
            var results = ds.FindAll();
            
            foreach (SearchResult sr in results)
            {
                var cn = sr.Properties["cn"].Count > 0 ? sr.Properties["cn"][0]?.ToString() ?? "" : "";
                var description = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                
                if (!string.IsNullOrWhiteSpace(cn) && !cn.Equals(fio))
                {
                    var row = dt.NewRow();
                    row["Объект"] = cn;
                    row["Вывод. имя"] = "";
                    row["Описание"] = description;
                    dt.Rows.Add(row);
                }
            }
        }
        catch
        {
        }
        return dt;
    }

    public DataTable GetVladetelIsList(DataTable loginsDT)
    {
        loginsDT.Columns.Add("Тип");
        loginsDT.Columns.Add("Объект");
        loginsDT.Columns.Add("Вывод. имя");
        loginsDT.Columns.Add("Описание");
        
        var logins = new List<string>();
        foreach (DataRow row in loginsDT.Rows)
            logins.Add(row[0].ToString()!.Trim());
        logins = logins.Distinct().ToList();
        loginsDT.Rows.Clear();
        
        var results = new System.Collections.Concurrent.ConcurrentBag<DataRow>();
        
        foreach (var login in logins)
        {
            string fio = string.Empty;
            string dn = string.Empty;
            
            var userInfo = GetUserMoreInfo(login, out var error);
            if (error != null || userInfo.Rows.Count == 0)
            {
                var row = loginsDT.NewRow();
                row[0] = login;
                row["Тип"] = "not";
                row["Объект"] = "not";
                row["Вывод. имя"] = "not";
                row["Описание"] = "not";
                results.Add(row);
                continue;
            }
            
            fio = userInfo.Rows[0]["ФИО"].ToString()!;
            dn = userInfo.Rows[0]["LDAP путь"].ToString()!;
            
            var resourceRows = GetOwnerResources_GroupBox(fio);
            foreach (DataRow r in resourceRows.Rows)
            {
                var row = loginsDT.NewRow();
                row[0] = login;
                row["Тип"] = "ГПЯ";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }
            
            resourceRows = GetOwnerResources_ServiceUz(fio);
            foreach (DataRow r in resourceRows.Rows)
            {
                var row = loginsDT.NewRow();
                row[0] = login;
                row["Тип"] = "Сервисная УЗ";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }
            
            resourceRows = GetOwnerResources_Group(fio);
            foreach (DataRow r in resourceRows.Rows)
            {
                var row = loginsDT.NewRow();
                row[0] = login;
                row["Тип"] = "Группа";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }
            
            resourceRows = GetOwnerResources_Maillist(dn);
            foreach (DataRow r in resourceRows.Rows)
            {
                var row = loginsDT.NewRow();
                row[0] = login;
                row["Тип"] = "Рассылка";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }
            
            resourceRows = GetOwnerResources_DinamicDistributionGroup(dn, fio);
            foreach (DataRow r in resourceRows.Rows)
            {
                var row = loginsDT.NewRow();
                row[0] = login;
                row["Тип"] = "Динамическая рассылка";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }
        }
        
        foreach (var row in results)
            loginsDT.Rows.Add(row);
        
        loginsDT.DefaultView.Sort = $"{loginsDT.Columns[1].ColumnName}, {loginsDT.Columns[2].ColumnName}";
        return loginsDT.DefaultView.ToTable();
    }

    public DataTable GetVladetelIsListByFIO(DataTable fioDT)
    {
        fioDT.Columns.Add("Тип");
        fioDT.Columns.Add("Объект");
        fioDT.Columns.Add("Вывод. имя");
        fioDT.Columns.Add("Описание");
        
        var fios = new List<string>();
        foreach (DataRow row in fioDT.Rows)
            fios.Add(row[0].ToString()!.Trim());
        fios = fios.Distinct().ToList();
        fioDT.Rows.Clear();
        
        var results = new System.Collections.Concurrent.ConcurrentBag<DataRow>();
        
        foreach (var fio in fios)
        {
            foreach (DataRow r in GetOwnerResources_GroupBox(fio).Rows)
            {
                var row = fioDT.NewRow();
                row[0] = fio;
                row["Тип"] = "ГПЯ";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }

            foreach (DataRow r in GetOwnerResources_ServiceUz(fio).Rows)
            {
                var row = fioDT.NewRow();
                row[0] = fio;
                row["Тип"] = "Сервисная УЗ";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }

            foreach (DataRow r in GetOwnerResources_Group(fio).Rows)
            {
                var row = fioDT.NewRow();
                row[0] = fio;
                row["Тип"] = "Группа";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }

            foreach (DataRow r in GetOwnerResources_DinamicDistributionGroup(null, fio).Rows)
            {
                var row = fioDT.NewRow();
                row[0] = fio;
                row["Тип"] = "Динамическая рассылка";
                row["Объект"] = r["Объект"];
                row["Вывод. имя"] = r["Вывод. имя"];
                row["Описание"] = r["Описание"];
                results.Add(row);
            }
        }
        
        foreach (var row in results)
            fioDT.Rows.Add(row);
        
        fioDT.DefaultView.Sort = $"{fioDT.Columns[1].ColumnName}, {fioDT.Columns[2].ColumnName}";
        return fioDT.DefaultView.ToTable();
    }

    public DataTable Fast_GetMaillistInfoOnDisplayName(string displayName)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(displayName)) return dt;
        displayName = CanonicalizeStringForLdapFilter(displayName);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            var props = new[] { "displayName", "description" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=eximMaillist)(objectCategory=eximMaillist)(displayName={displayName}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["displayName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Вывод. имя"] = sr.Properties["displayName"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetGroupInfoOnMail(string mail)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(mail)) return dt;
        mail = CanonicalizeStringForLdapFilter(mail);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            var props = new[] { "mail", "description" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectCategory=group)(mail={mail}*))"
            };
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(props);
            ds.Asynchronous = true;

            dt.Columns.Add("Почта");
            dt.Columns.Add("Описание");

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["mail"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Почта"] = sr.Properties["mail"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetDynamicDistributionGroupInfoOnMail(string mail)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(mail)) return dt;
        mail = CanonicalizeStringForLdapFilter(mail);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            var props = new[] { "mail", "description" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=msExchDynamicDistributionList)(mail={mail}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Почта");
            dt.Columns.Add("Описание");

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["mail"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Почта"] = sr.Properties["mail"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetDynamicDistributionGroupInfoOnCn(string cn)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(cn)) return dt;
        cn = CanonicalizeStringForLdapFilter(cn);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            var props = new[] { "cn", "description" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=msExchDynamicDistributionList)(cn={cn}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Логин");
            dt.Columns.Add("Описание");

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["cn"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["cn"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetDynamicDistributionGroupInfoOnDisplayName(string displayName)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(displayName)) return dt;
        displayName = CanonicalizeStringForLdapFilter(displayName);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            var props = new[] { "displayName", "description" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=msExchDynamicDistributionList)(displayName={displayName}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Вывод. имя");
            dt.Columns.Add("Описание");

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["displayName"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Вывод. имя"] = sr.Properties["displayName"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable Fast_GetMaillistInfoOnCn(string cn)
    {
        var dt = new DataTable();
        if (string.IsNullOrWhiteSpace(cn)) return dt;
        cn = CanonicalizeStringForLdapFilter(cn);
        var path = "LDAP://" + Data.DC + Data.AdPath_Domain;

        try
        {
            var props = new[] { "cn", "description" };
            using var searchRoot = new DirectoryEntry(path);
            using var ds = new DirectorySearcher(searchRoot)
            {
                SearchScope = SearchScope.Subtree,
                ReferralChasing = ReferralChasingOption.None,
                Filter = $"(&(objectClass=eximMaillist)(objectCategory=eximMaillist)(cn={cn}*))"
            };
            ds.PageSize = 11;
            ds.SizeLimit = 10;
            ds.PropertiesToLoad.AddRange(props);

            dt.Columns.Add("Логин");
            dt.Columns.Add("Описание");

            foreach (SearchResult sr in ds.FindAll())
            {
                if (sr.Properties["cn"].Count > 0)
                {
                    var row = dt.NewRow();
                    row["Логин"] = sr.Properties["cn"][0]?.ToString() ?? "";
                    row["Описание"] = sr.Properties["description"].Count > 0 ? sr.Properties["description"][0]?.ToString() ?? "" : "";
                    dt.Rows.Add(row);
                }
            }
        }
        catch { }
        return dt;
    }

    public DataTable GetUserByDN(string distinguishedName)
    {
        var dataTable = new DataTable();
        var path = "LDAP://" + Data.DC + "/" + distinguishedName;

        try
        {
            using var directoryEntry = new DirectoryEntry(path);
            directoryEntry.RefreshCache(new[] { 
                "sAMAccountName", "displayName", "description", "mail", "telephoneNumber", 
                "mobilepers", "company", "department", "title", "manager", "thumbnailPhoto",
                "userAccountControl"
            });

            dataTable.Columns.Add("Логин");
            dataTable.Columns.Add("Вывод. имя");
            dataTable.Columns.Add("Описание");
            dataTable.Columns.Add("Почта");
            dataTable.Columns.Add("Телефон");
            dataTable.Columns.Add("Моб. телефон");
            dataTable.Columns.Add("Компания");
            dataTable.Columns.Add("Департамент");
            dataTable.Columns.Add("distinguishedName");
            dataTable.Columns.Add("manager");
            dataTable.Columns.Add("Photo", typeof(byte[]));
            dataTable.Columns.Add("Статус УЗ");

            var row = dataTable.NewRow();
            row["Логин"] = directoryEntry.Properties["sAMAccountName"].Count > 0 ? directoryEntry.Properties["sAMAccountName"][0]?.ToString() ?? "" : "";
            row["Вывод. имя"] = directoryEntry.Properties["displayName"].Count > 0 ? directoryEntry.Properties["displayName"][0]?.ToString() ?? "" : "";
            row["Описание"] = directoryEntry.Properties["description"].Count > 0 ? directoryEntry.Properties["description"][0]?.ToString() ?? "" : "";
            row["Почта"] = directoryEntry.Properties["mail"].Count > 0 ? directoryEntry.Properties["mail"][0]?.ToString() ?? "" : "";
            row["Телефон"] = directoryEntry.Properties["telephoneNumber"].Count > 0 ? directoryEntry.Properties["telephoneNumber"][0]?.ToString() ?? "" : "";
            row["Моб. телефон"] = directoryEntry.Properties["mobilepers"].Count > 0 ? directoryEntry.Properties["mobilepers"][0]?.ToString() ?? "" : "";
            row["Компания"] = directoryEntry.Properties["company"].Count > 0 ? directoryEntry.Properties["company"][0]?.ToString() ?? "" : "";
            row["Департамент"] = directoryEntry.Properties["department"].Count > 0 ? directoryEntry.Properties["department"][0]?.ToString() ?? "" : "";
            row["distinguishedName"] = distinguishedName;
            row["manager"] = directoryEntry.Properties["manager"].Count > 0 ? directoryEntry.Properties["manager"][0]?.ToString() ?? "" : "";
            row["Photo"] = directoryEntry.Properties["thumbnailPhoto"].Count > 0 ? directoryEntry.Properties["thumbnailPhoto"][0] as byte[] : null;
            
            int uac = directoryEntry.Properties["userAccountControl"].Count > 0 
                ? Convert.ToInt32(directoryEntry.Properties["userAccountControl"][0]) : 0;
            row["Статус УЗ"] = (uac & 2) != 0 ? "DISABLE" : "NORMAL";

            dataTable.Rows.Add(row);
        }
        catch { }
        return dataTable;
    }

    #region AD Write Operations

    private static string SanitizeAdError(Exception ex)
    {
        var msg = ex.Message;
        if (msg.Length > 200) msg = msg.Substring(0, 200);
        return msg;
    }

    private DirectoryEntry CreateUserEntry(string userDN)
    {
        var dc = Data.DC ?? "corp.tander.ru";
        var path = $"LDAP://{dc}/{userDN}";
        return CreateEntryWithAuth(path, AuthenticationTypes.Secure | AuthenticationTypes.Sealing | AuthenticationTypes.Signing);
    }

    public ADOperationResult ChangeUserPassword(string userDN, string newPassword)
    {
        if (string.IsNullOrWhiteSpace(userDN))
            return ADOperationResult.Fail("Не указан DN пользователя", "INVALID_DN");
        if (string.IsNullOrEmpty(newPassword) || newPassword.Length < 8 || newPassword.Length > 128)
            return ADOperationResult.Fail("Пароль не соответствует требованиям сложности", "WEAK_PASSWORD");

        try
        {
            using var entry = CreateUserEntry(userDN);
            entry.Invoke("SetPassword", newPassword);
            entry.CommitChanges();
            ADAuditLogger.Log("ChangePassword", userDN, Environment.UserName, true, "Пароль изменён");
            return ADOperationResult.Ok("Пароль изменён");
        }
        catch (Exception ex)
        {
            var sanitized = SanitizeAdError(ex);
            ADAuditLogger.Log("ChangePassword", userDN, Environment.UserName, false, sanitized, ex.GetType().Name);
            return ADOperationResult.Fail(sanitized, ex.GetType().Name);
        }
    }

    public ADOperationResult ForcePasswordChangeAtNextLogon(string userDN, bool force)
    {
        if (string.IsNullOrWhiteSpace(userDN))
            return ADOperationResult.Fail("Не указан DN пользователя", "INVALID_DN");

        try
        {
            using var entry = CreateUserEntry(userDN);
            entry.Properties["pwdLastSet"].Value = force ? 0 : -1;
            entry.CommitChanges();
            ADAuditLogger.Log("ForcePasswordChange", userDN, Environment.UserName, true,
                force ? "Флаг смены пароля установлен" : "Флаг смены пароля снят");
            return ADOperationResult.Ok(force ? "Требование смены пароля установлено" : "Требование смены пароля снято");
        }
        catch (Exception ex)
        {
            var sanitized = SanitizeAdError(ex);
            ADAuditLogger.Log("ForcePasswordChange", userDN, Environment.UserName, false, sanitized, ex.GetType().Name);
            return ADOperationResult.Fail(sanitized, ex.GetType().Name);
        }
    }

    public ADOperationResult UnlockAccount(string userDN, int maxRetries = 3, int retryDelayMs = 2000)
    {
        if (string.IsNullOrWhiteSpace(userDN))
            return ADOperationResult.Fail("Не указан DN пользователя", "INVALID_DN");

        for (int attempt = 1; attempt <= maxRetries; attempt++)
        {
            try
            {
                using var entry = CreateUserEntry(userDN);
                entry.Properties["lockoutTime"].Value = 0;
                entry.CommitChanges();
                entry.RefreshCache();
                var lt = entry.Properties["lockoutTime"];
                if (lt.Count > 0 && Convert.ToInt64(lt[0]) == 0)
                {
                    ADAuditLogger.Log("UnlockAccount", userDN, Environment.UserName, true,
                        $"УЗ разблокирована (попытка {attempt})");
                    return ADOperationResult.Ok("Учётная запись разблокирована");
                }
            }
            catch (Exception ex)
            {
                if (attempt == maxRetries)
                {
                    var sanitized = SanitizeAdError(ex);
                    ADAuditLogger.Log("UnlockAccount", userDN, Environment.UserName, false, sanitized, ex.GetType().Name);
                    return ADOperationResult.Fail(sanitized, ex.GetType().Name);
                }
            }
            if (attempt < maxRetries)
                Thread.Sleep(retryDelayMs);
        }

        ADAuditLogger.Log("UnlockAccount", userDN, Environment.UserName, false,
            $"Не удалось разблокировать после {maxRetries} попыток", "STILL_LOCKED");
        return ADOperationResult.Fail($"Не удалось разблокировать после {maxRetries} попыток", "STILL_LOCKED");
    }

    public PasswordStatusInfo GetPasswordStatus(string userDN)
    {
        if (string.IsNullOrWhiteSpace(userDN))
            return new PasswordStatusInfo(null, null, false, false);

        try
        {
            using var entry = CreateUserEntry(userDN);
            using var searcher = new DirectorySearcher(entry)
            {
                SearchScope = SearchScope.Base,
                CacheResults = false
            };
            searcher.PropertiesToLoad.Add("pwdLastSet");
            searcher.PropertiesToLoad.Add("userAccountControl");
            searcher.PropertiesToLoad.Add("msDS-UserPasswordExpiryTimeComputed");

            var sr = searcher.FindOne();
            if (sr == null)
                return new PasswordStatusInfo(null, null, false, false);

            DateTime? lastSet = null;
            var pwdProps = sr.Properties["pwdLastSet"];
            if (pwdProps.Count > 0)
            {
                var pwdStr = pwdProps[0]?.ToString() ?? "";
                if (long.TryParse(pwdStr, out var val))
                {
                    if (val == 0)
                        return new PasswordStatusInfo(null, null, false, true);
                    lastSet = SafeFromFileTime(val);
                }
            }

            bool neverExpires = false;
            var uacProps = sr.Properties["userAccountControl"];
            if (uacProps.Count > 0)
            {
                var uacStr = uacProps[0]?.ToString() ?? "";
                if (int.TryParse(uacStr, out var uacVal))
                    neverExpires = (uacVal & (int)AdsUserFlags.PasswordDoesNotExpire) != 0;
            }

            DateTime? expiry = null;
            var expProps = sr.Properties["msDS-UserPasswordExpiryTimeComputed"];
            if (expProps.Count > 0)
            {
                var expStr = expProps[0]?.ToString() ?? "";
                if (long.TryParse(expStr, out var val))
                {
                    if (val == long.MaxValue || val < 0)
                        neverExpires = true;
                    else
                        expiry = SafeFromFileTime(val);
                }
            }

            return new PasswordStatusInfo(lastSet, expiry, neverExpires, false);
        }
        catch (Exception)
        {
            return new PasswordStatusInfo(null, null, false, false);
        }
    }

    public AccountLockStatusInfo GetAccountLockStatus(string userDN)
    {
        if (string.IsNullOrWhiteSpace(userDN))
            return new AccountLockStatusInfo(false, false);

        try
        {
            using var entry = CreateUserEntry(userDN);
            entry.RefreshCache();

            bool lockedOut = false;
            var lt = entry.Properties["lockoutTime"];
            if (lt.Count > 0 && Convert.ToInt64(lt[0]) != 0)
                lockedOut = true;

            bool enabled = true;
            var uac = entry.Properties["userAccountControl"];
            if (uac.Count > 0)
            {
                var uacVal = Convert.ToInt32(uac[0]);
                enabled = (uacVal & (int)AdsUserFlags.AccountDisabled) == 0;
            }

            return new AccountLockStatusInfo(lockedOut, enabled);
        }
        catch
        {
            return new AccountLockStatusInfo(false, false);
        }
    }

    #endregion
}
