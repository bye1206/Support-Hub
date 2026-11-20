using System;
using System.Collections.ObjectModel;
using System.Collections.Generic;
using System.Data;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Input;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using GetGroupBoxMember.Models;
using GetGroupBoxMember.Services;
using GetGroupBoxMember.Views;

namespace GetGroupBoxMember.ViewModels;

public partial class MainWindowViewModel : ViewModelBase
{
    private readonly IADService _adService;
    private readonly QueryLogger _queryLogger;
    private readonly WindowManager _windowManager;
    private CancellationTokenSource? _searchCts;
    private CancellationTokenSource? _debounceCts;
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, CancellationTokenSource> _commandCts = new();

    private CancellationToken GetCommandToken(string commandName)
    {
        if (_commandCts.TryRemove(commandName, out var existing))
        {
            existing.Cancel();
            existing.Dispose();
        }
        var cts = new CancellationTokenSource();
        _commandCts[commandName] = cts;
        return cts.Token;
    }

    private void CancelAllCommandTokens()
    {
        foreach (var kvp in _commandCts)
        {
            kvp.Value.Cancel();
            kvp.Value.Dispose();
        }
        _commandCts.Clear();
    }

    [ObservableProperty]
    private string _searchText = string.Empty;

    [ObservableProperty]
    private string _searchType = "User";

    [ObservableProperty]
    private ObservableCollection<SearchResultItem> _searchResults = new();

    [ObservableProperty]
    private double _listScrollOffset;

    [ObservableProperty]
    private bool _isSearching;

    [ObservableProperty]
    private bool _isListVisible;

    [ObservableProperty]
    private SearchResultItem? _selectedSearchResult;

    partial void OnSelectedSearchResultChanged(SearchResultItem? value)
    {
        if (_suppressClearOnResultClear) return;
        if (value != null && !value.IsPlaceholder)
        {
            OnSearchResultSelected(value);
        }
        else if (value == null)
        {
            ClearForm();
        }
    }

    [ObservableProperty]
    private UserInfo? _selectedUser;

    [ObservableProperty]
    private UserMoreInfo? _userMoreInfo;

    [ObservableProperty]
    private string _statusText = "Готов";

    [ObservableProperty]
    private string _searchProgress = string.Empty;

    [ObservableProperty]
    private string _findStatusText = string.Empty;

    [ObservableProperty]
    private bool _isFindStatusVisible;

    [ObservableProperty]
    private string _login = string.Empty;

    [ObservableProperty]
    private string _mail = string.Empty;

    [ObservableProperty]
    private string _displayName = string.Empty;

    [ObservableProperty]
    private string _description = string.Empty;

    [ObservableProperty]
    private string _department = string.Empty;

    [ObservableProperty]
    private string _company = string.Empty;

    [ObservableProperty]
    private string _title = string.Empty;

    [ObservableProperty]
    private string _phone = string.Empty;

    [ObservableProperty]
    private string _mobilePhone = string.Empty;

    [ObservableProperty]
    private string _mobilePhoneDisplay = string.Empty;

    [ObservableProperty]
    private bool _hasMobilePhoneWarning;

    [ObservableProperty]
    private string _mailDisplay = string.Empty;

    [ObservableProperty]
    private bool _hasMailWarning;

    [ObservableProperty]
    private string _manager = string.Empty;

    [ObservableProperty]
    private string _distinguishedName = string.Empty;

    [ObservableProperty]
    private string _vladetel = string.Empty;

    [ObservableProperty]
    private string _mailHost = string.Empty;

    [ObservableProperty]
    private string _mailBoxLocation = string.Empty;

    [ObservableProperty]
    private string _migrateStatus = string.Empty;

    [ObservableProperty]
    private string _retentionPolicy = string.Empty;

    [ObservableProperty]
    private bool _isSharedMailbox;

    [ObservableProperty]
    private bool _isBadgesTwoRows;

    public bool IsBadgesOneRow => !IsBadgesTwoRows;

    [ObservableProperty]
    private bool _isExchangeMailbox;

    [ObservableProperty]
    private string _quotaMailBox = string.Empty;

    [ObservableProperty]
    private string _statusSMD = string.Empty;

    [ObservableProperty]
    private string _statusUZ = string.Empty;

    [ObservableProperty]
    private string _AccountStatus = string.Empty;

    [ObservableProperty]
    private string _HrStatus = string.Empty;

    [ObservableProperty]
    private string _PasswordDays = string.Empty;

    [ObservableProperty]
    private string _PasswordBlocked = string.Empty;

    [ObservableProperty]
    private bool _isLockedOut;

    [ObservableProperty]
    private bool _passwordRequireChange;

    [ObservableProperty]
    private bool _isAdOperationInProgress;

    [ObservableProperty]
    private string _passwordLastSetText = string.Empty;

    [ObservableProperty]
    private string _passwordExpiryText = string.Empty;

    [ObservableProperty]
    private string _passwordNeverExpiresText = string.Empty;

    [ObservableProperty]
    private string _adOperationStatus = string.Empty;

    public bool IsAdActionEnabled => HasSelectedUser && !IsSharedMailbox && !IsAdOperationInProgress;
    public bool IsUnlockEnabled => IsAdActionEnabled && IsLockedOut;

    partial void OnIsAdOperationInProgressChanged(bool value) => UpdateAdActionState();
    partial void OnHasSelectedUserChanged(bool value) => UpdateAdActionState();
    partial void OnIsSharedMailboxChanged(bool value) => UpdateAdActionState();
    partial void OnIsLockedOutChanged(bool value) => UpdateAdActionState();

    private void UpdateAdActionState()
    {
        OnPropertyChanged(nameof(IsAdActionEnabled));
        OnPropertyChanged(nameof(IsUnlockEnabled));
    }

    [ObservableProperty]
    private string _MailboxUsedSize = string.Empty;

    [ObservableProperty]
    private string _lastLogonTime = string.Empty;

    [ObservableProperty]
    private string _domainController = string.Empty;

    [ObservableProperty]
    private string _photoUrl = string.Empty;

    [ObservableProperty]
    private Bitmap? _avatarBitmap;

    [ObservableProperty]
    private bool _hasSelectedUser;

    [ObservableProperty]
    private bool _isUsersSelected = true;

    [ObservableProperty]
    private bool _isGroupsSelected;

    [ObservableProperty]
    private bool _isComputersSelected;

    [ObservableProperty]
    private bool _isMailListsSelected;

    [ObservableProperty]
    private bool _isDynamicGroupSelected;

    [ObservableProperty]
    private ObservableCollection<UserInfo> _memberGroupUsers = new();

    [ObservableProperty]
    private ObservableCollection<UserInfo> _ownerUsers = new();

    [ObservableProperty]
    private ObservableCollection<UserInfo> _eximUsers = new();

    [ObservableProperty]
    private ObservableCollection<UserInfo> _exchangeUsers = new();

    [ObservableProperty]
    private ObservableCollection<UserInfo> _pcUsers = new();

    [ObservableProperty]
    private ObservableCollection<UserInfo> _groupAccessUsers = new();

    [ObservableProperty]
    private ObservableCollection<UserInfo> _mailboxUsers = new();

    [ObservableProperty]
    private ObservableCollection<AttributesItem> _attributesList = new();

    [ObservableProperty]
    private ObservableCollection<GroupMoreInfo> _groupMoreInfoList = new();

    [ObservableProperty]
    private ObservableCollection<MaillistMoreInfo> _maillistMoreInfoList = new();

    [ObservableProperty]
    private bool _isRefreshEnabled = true;
[ObservableProperty]
    private bool _isGetInfoEnabled;

    [ObservableProperty]
    private bool _isGetHierarchyEnabled;

    [ObservableProperty]
    private bool _isRepadminEnabled;

    [ObservableProperty]
    private bool _isGetMemberGroupEnabled;

    [ObservableProperty]
    private bool _isGetOwnerEnabled;

    [ObservableProperty]
    private bool _isGetEximUserEnabled;

    [ObservableProperty]
    private bool _isGetExchangeUserEnabled;

    [ObservableProperty]
    private bool _isEximExchangeEnabled;

    [ObservableProperty]
    private bool _isGetGroupAccessEnabled;

    [ObservableProperty]
    private bool _isGetMailboxAccessEnabled;

    [ObservableProperty]
    private bool _isGetVladetelIsListEnabled;

    [ObservableProperty]
    private bool _isFindPcEnabled;

    [ObservableProperty]
    private bool _isEximEnabled;

    [ObservableProperty]
    private bool _isExchangeEnabled;

    [ObservableProperty]
    private bool _isGroupAccessEnabled;

    [ObservableProperty]
    private bool _isMailboxAccessEnabled;

    [ObservableProperty]
    private bool _isVladetelIsListEnabled;

    [ObservableProperty]
    private bool _isUserLogEnabled;

    [ObservableProperty]
    private bool _isGroupMemberEnabled;

    [ObservableProperty]
    private bool _isGroupBoxAccessLoading;

    [ObservableProperty]
    private bool _isMailboxAccessLoading;

    [ObservableProperty]
    private bool _isGetVladetelIsListLoading;

    [ObservableProperty]
    private string _vladetelIsListLoadingText = "Загрузка...";

    [ObservableProperty]
    private bool _isUserLogLoading;

    [ObservableProperty]
    private bool _isEximExchangeLoading;

    [ObservableProperty]
    private bool _isGetEximUserLoading;

    [ObservableProperty]
    private bool _isGetExchangeUserLoading;

    [ObservableProperty]
    private bool _isEximLoading;

    [ObservableProperty]
    private bool _isExchangeLoading;

    [ObservableProperty]
    private bool _isGroupMemberLoading;

    [ObservableProperty]
    private bool _isFindPcLoading;

    [ObservableProperty]
    private bool _isUserBadgeVisible;

    [ObservableProperty]
    private bool _isCommandPaletteOpen;

    private int _threadSleepPreFind = 0;
    private int _threadSleepPostFind = 0;
    private DateTime _preFindLastDate = DateTime.MinValue;
    private DateTime _postFindLastDate = DateTime.MinValue;
    private bool _fastFindComplete = false;
    private bool _pictureBoxNonVisibleFlag = false;
    private bool _suppressDebounce;
    private bool _suppressClearOnResultClear;
    private string _inputBuf = string.Empty;

    private List<UserInfo> _boxDt = new();
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, UserInfo> _userInfoCache = new();
    private string? _pendingSelectedLogin;

    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, List<UserInfo>> _eximCache = new();
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, List<UserInfo>> _exchangeCache = new();
    private string _eximMembersDns = string.Empty;
    private string _exchangeMembersDns = string.Empty;
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, List<UserInfo>> _groupBoxAccessCache = new();
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, List<UserInfo>> _mailboxAccessCache = new();
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, DataTable> _ownerCache = new();
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, List<UserInfo>> _groupMembersCache = new();
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, List<UserInfo>> _maillistMembersCache = new();
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, DataTable> _userLogCache = new();

    public MainWindowViewModel() : this(new ADService())
    {
    }

    public MainWindowViewModel(IADService adService)
    {
        _adService = adService ?? new ADService();
        _queryLogger = new QueryLogger();
        _windowManager = WindowManager.Instance;
        RefreshCommand = new RelayCommand(ExecuteRefresh);
        IsUserBadgeVisible = true;
    }

    public List<UserInfo>? GetCachedEximUsers() => _eximCache.TryGetValue(Login, out var list) ? list : null;

    public List<UserInfo>? GetCachedExchangeUsers() => _exchangeCache.TryGetValue(Login, out var list) ? list : null;

    public List<UserInfo>? GetCachedGroupBoxAccessUsers() => _groupBoxAccessCache.TryGetValue(Login, out var list) ? list : null;

    public List<UserInfo>? GetCachedMailboxAccessUsers() => _mailboxAccessCache.TryGetValue(Login, out var list) ? list : null;

    public DataTable? GetCachedOwnerUsers() => _ownerCache.TryGetValue(Login, out var dt) ? dt : null;

    public DataTable? GetCachedUserLog() => _userLogCache.TryGetValue(Login, out var dt) ? dt : null;

    private bool TryPopulateFromCache<T>(ObservableCollection<T> collection, System.Collections.Concurrent.ConcurrentDictionary<string, List<T>> cache, string key) where T : class
    {
        if (cache.TryGetValue(key, out var list) && list.Count > 0)
        {
            collection.Clear();
            foreach (var item in list) collection.Add(item);
            return true;
        }
        return false;
    }

    private bool TryPopulateUserInfoFromCache(ObservableCollection<UserInfo> collection, System.Collections.Concurrent.ConcurrentDictionary<string, List<UserInfo>> cache, string key)
    {
        if (cache.TryGetValue(key, out var list) && list.Count > 0)
        {
            collection.Clear();
            foreach (var item in list) collection.Add(item);
            return true;
        }
        return false;
    }

    partial void OnSearchTextChanged(string value)
    {

        if (_suppressDebounce)
        {
            _suppressDebounce = false;
            return;
        }

        if (string.IsNullOrWhiteSpace(value) || value.Length < 2)
        {
            IsListVisible = false;
            SearchResults.Clear();
            ClearForm();
            return;
        }
        _ = DebounceSearchAsync(value);
    }

    partial void OnSelectedUserChanged(UserInfo? value)
    {
        HasSelectedUser = value != null;
        IsUserBadgeVisible = HasSelectedUser;
    }

    partial void OnIsUsersSelectedChanged(bool value)
    {
        if (value) 
        {
            ClearForm();
            SearchType = "User";
            IsUserBadgeVisible = HasSelectedUser;
            if (!string.IsNullOrWhiteSpace(SearchText) && SearchText.Length >= 2)
            {
                _ = DebounceSearchAsync(SearchText);
            }
        }
    }

    partial void OnIsGroupsSelectedChanged(bool value)
    {
        if (value) 
        {
            ClearForm();
            SearchType = "Group";
            IsUserBadgeVisible = false;
            if (!string.IsNullOrWhiteSpace(SearchText) && SearchText.Length >= 2)
            {
                _ = DebounceSearchAsync(SearchText);
            }
        }
    }

    partial void OnIsComputersSelectedChanged(bool value)
    {
        if (value)
        {
            ClearForm();
            SearchType = "Computer";
            IsUserBadgeVisible = false;
            if (!string.IsNullOrWhiteSpace(SearchText) && SearchText.Length >= 2)
            {
                _ = DebounceSearchAsync(SearchText);
            }
            else
            {
            }
        }
    }

    partial void OnIsMailListsSelectedChanged(bool value)
    {
        if (value) 
        {
            ClearForm();
            SearchType = "MailList";
            IsUserBadgeVisible = false;
            if (!string.IsNullOrWhiteSpace(SearchText) && SearchText.Length >= 2)
            {
                _ = DebounceSearchAsync(SearchText);
            }
        }
    }

    partial void OnIsDynamicGroupSelectedChanged(bool value)
    {
        if (value) 
        {
            ClearForm();
            SearchType = "DynamicGroup";
            IsUserBadgeVisible = false;
            if (!string.IsNullOrWhiteSpace(SearchText) && SearchText.Length >= 2)
            {
                _ = DebounceSearchAsync(SearchText);
            }
        }
    }

    private async Task DebounceSearchAsync(string query)
    {
        var trimmedQuery = query.Trim();
        _debounceCts?.Cancel();
        _debounceCts = new CancellationTokenSource();
        var token = _debounceCts.Token;

        var normalizedQuery = trimmedQuery;
        if (SearchType == "User")
        {
            var parsed = Helpers.NormalizeSearchQuery(trimmedQuery);
            if (parsed != trimmedQuery)
            {
                normalizedQuery = parsed;
            }
        }

        try
        {
            await Task.Delay(250, token);
            if (!token.IsCancellationRequested)
            {
                await PerformSearchAsync(normalizedQuery, token);
            }
            else
            {
            }
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task PerformSearchAsync(string query, CancellationToken token)
    {
        var psSw = System.Diagnostics.Stopwatch.StartNew();
        
        if (string.IsNullOrWhiteSpace(query) || query.Length < 2)
        {
            SearchResults.Clear();
            IsListVisible = false;
            ClearForm();
            return;
        }

        IsSearching = true;
        IsListVisible = true;
        SearchProgress = "Начинаем поиск...";
        
        try
        {
            var results = await _adService.FastSearchAsync(query, SearchType, token, progress =>
            {
                Dispatcher.UIThread.Post(() => SearchProgress = progress);
            });
            
            if (token.IsCancellationRequested)
            {
                return;
            }
            

            var savedOffset = ListScrollOffset;
            SearchResults.Clear();
            _userInfoCache.Clear();
            if (results != null)
            {
                foreach (var r in results)
                {
                    if (!string.IsNullOrEmpty(r.Login))
                        _userInfoCache[r.Login] = r;
                    SearchResults.Add(new SearchResultItem
                    {
                        Login = r.Login,
                        DisplayName = r.DisplayName,
                        Description = r.Description,
                        Email = r.Email,
                        Department = r.Department,
                        MobilePhone = r.MobilePhone,
                        Owner = SearchType == "User" ? r.Owner : string.Empty,
                        DistinguishedName = r.DN ?? string.Empty
                    });
                }
            }
            Dispatcher.UIThread.Post(() => ListScrollOffset = savedOffset);
            SearchProgress = (results?.Count ?? 0) > 0 ? $"Найдено: {results?.Count}" : "Ничего не найдено";
            StatusText = (results?.Count ?? 0) > 0 ? $"Найдено: {results?.Count}" : "Ничего не найдено";
            if (SearchResults.Count == 0)
            {
                SearchResults.Add(new SearchResultItem
                {
                    DisplayName = "Ничего не найдено, попробуйте изменить параметры поиска",
                    IsPlaceholder = true
                });
            }
        }
        catch (OperationCanceledException)
        {
            SearchProgress = "Поиск отменён";
            StatusText = "Поиск отменён";
        }
        finally
        {
            psSw.Stop();
            IsSearching = false;
        }
    }

    public async Task<List<SearchResultItem>> PerformQuickSearchAsync(string query, CancellationToken token)
    {
        var results = new List<SearchResultItem>();

        if (string.IsNullOrWhiteSpace(query) || query.Length < 2)
        {
            return results;
        }

        try
        {
            var searchResults = await _adService.FastSearchAsync(query, "User", token, progress =>
            {
                Dispatcher.UIThread.Post(() => { });
            });

            if (token.IsCancellationRequested)
            {
                return results;
            }

            if (searchResults != null)
            {
                foreach (var r in searchResults)
                {
                    results.Add(new SearchResultItem
                    {
                        Login = r.Login,
                        DisplayName = r.DisplayName,
                        Description = r.Description,
                        Email = r.Email,
                        Department = r.Department,
                        MobilePhone = r.MobilePhone,
                        Owner = r.Owner,
                        DistinguishedName = r.DN ?? string.Empty
                    });
                }
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception) { }

        return results;
    }

    private void OnSearchResultSelected(SearchResultItem item)
    {
        if (item == null) return;

        if (item.IsPlaceholder)
        {
            return;
        }


        if (string.IsNullOrWhiteSpace(item.Login) && string.IsNullOrWhiteSpace(item.DistinguishedName))
        {
            return;
        }

        _debounceCts?.Cancel();
        Dispatcher.UIThread.Post(() =>
        {
            _suppressClearOnResultClear = true;
            SearchResults.Clear();
            SelectedSearchResult = null;
            _suppressClearOnResultClear = false;
            IsListVisible = false;
        });
        _suppressDebounce = true;
        SearchText = item.Login ?? string.Empty;
        _suppressDebounce = false;
        _pendingSelectedLogin = item.Login;

        switch (SearchType)
        {
            case "User":
                _ = SearchUserByLoginAsync(item.Login, CancellationToken.None);
                break;
            case "Group":
                _suppressDebounce = false;
                _ = SearchGroupAsync(item.Login, CancellationToken.None, item.DistinguishedName);
                break;
            case "MailList":
                _suppressDebounce = false;
                _ = SearchMailListAsync(item.Login, CancellationToken.None);
                break;
            case "DynamicGroup":
                _suppressDebounce = false;
                _ = SearchDynamicGroupAsync(item.Login, CancellationToken.None);
                break;
            case "Computer":
                _suppressDebounce = false;
                _ = SearchComputerAsync(item.Login, CancellationToken.None);
                break;
            default:
                _suppressDebounce = false;
                _ = SearchUserByLoginAsync(item.Login, CancellationToken.None);
                break;
        }
    }

    private async Task SearchUserByLoginAsync(string query, CancellationToken token)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();

        IsGetInfoEnabled = true;
        IsGetHierarchyEnabled = true;
        IsRepadminEnabled = true;

        StatusText = $"Поиск пользователя: {query}...";

        try
        {
            var userInfo = await _adService.GetUserInfoAsync(query, token);
            sw.Stop();

            if (userInfo == null || userInfo.Count == 0)
            {
                FindStatusText = "Не найден";
                IsFindStatusVisible = true;
                return;
            }

            _boxDt = userInfo;

            if (userInfo.Count == 1)
            {
                await LoadUserDataAsync(userInfo[0], token);
                _pendingSelectedLogin = null;
            }
            else
            {
                FindStatusText = $"{userInfo.Count} УЗ";
                IsFindStatusVisible = true;
                IsGetInfoEnabled = true;

                if (!string.IsNullOrEmpty(_pendingSelectedLogin))
                {
                    var selectedUser = userInfo.FirstOrDefault(u => u.Login == _pendingSelectedLogin);
                    if (selectedUser != null)
                    {
                        await LoadUserDataAsync(selectedUser, token);
                        _pendingSelectedLogin = null;
                    }
                    else
                    {
                    }
                }
            }
        }
        catch (OperationCanceledException)
        {
            StatusText = "Поиск отменён";
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    private async Task LoadUserDataAsync(UserInfo user, CancellationToken token)
    {
        _inputBuf = SearchText;
        _postFindLastDate = DateTime.Now;
        _pictureBoxNonVisibleFlag = true;

        ClearAllCaches();

        AvatarBitmap = null;
        PhotoUrl = string.Empty;

        ResetAllButtonStates();

        var loadToken = GetCommandToken(nameof(LoadUserDataAsync));


        SelectedUser = user;
        FindStatusText = "OK";
        IsFindStatusVisible = true;

        Login = user.Login ?? string.Empty;
        Mail = user.Email ?? string.Empty;
        DisplayName = user.DisplayName ?? string.Empty;
        Description = user.Description ?? string.Empty;
        Department = user.Department ?? string.Empty;
        Company = user.Company ?? string.Empty;
        Title = user.Title ?? string.Empty;
        Phone = user.Phone ?? string.Empty;
        MobilePhone = user.MobilePhone ?? string.Empty;
        ValidateUserFields();

        var hasEximSource = !string.IsNullOrWhiteSpace(Mail);
        var hasEximMembers = !string.IsNullOrWhiteSpace(user.EximMembers);
        var hasExchangeMembers = !string.IsNullOrWhiteSpace(user.ExchangeMembers);
        var isSharedMailbox = user.IsSharedMailbox;

        _eximMembersDns = user.EximMembers ?? string.Empty;
        _exchangeMembersDns = user.ExchangeMembers ?? string.Empty;


        if (isSharedMailbox)
        {
            IsEximEnabled = hasEximSource;
            IsExchangeEnabled = hasEximSource;
            IsGetEximUserEnabled = hasEximSource;
            IsGetExchangeUserEnabled = hasEximSource;
            IsEximExchangeEnabled = hasEximSource;
            IsGetMemberGroupEnabled = false;
            IsGroupAccessEnabled = false;
            IsMailboxAccessEnabled = false;
            IsGetOwnerEnabled = false;
            IsVladetelIsListEnabled = false;
            IsUserLogEnabled = false;
            IsFindPcEnabled = false;
            IsGroupMemberEnabled = false;
            IsGetHierarchyEnabled = false;
            IsGetInfoEnabled = true;
            IsRepadminEnabled = true;
        }
        else
        {
            IsEximEnabled = false;
            IsExchangeEnabled = false;
            IsGetEximUserEnabled = false;
            IsGetExchangeUserEnabled = false;
            IsEximExchangeEnabled = false;
            IsGetMemberGroupEnabled = !string.IsNullOrWhiteSpace(DistinguishedName);
            IsGroupAccessEnabled = false;
            IsMailboxAccessEnabled = false;
            IsGetOwnerEnabled = !string.IsNullOrWhiteSpace(Login);
            IsVladetelIsListEnabled = false;
            IsUserLogEnabled = false;
            IsFindPcEnabled = false;
            IsGroupMemberEnabled = !string.IsNullOrWhiteSpace(DistinguishedName);
            IsGetHierarchyEnabled = true;
            IsGetInfoEnabled = true;
            IsRepadminEnabled = true;
        }

        if (!string.IsNullOrWhiteSpace(user.Manager))
        {
            _ = ResolveManagerAsync(user.Manager, loadToken);
        }
        else
        {
            Manager = string.Empty;
        }

        DistinguishedName = user.DN ?? string.Empty;
        Vladetel = user.Owner ?? string.Empty;
        MailHost = user.MailHost ?? string.Empty;
        MailBoxLocation = user.MailBoxLocation ?? string.Empty;
        MigrateStatus = user.MigrateStatus ?? string.Empty;
        QuotaMailBox = string.IsNullOrEmpty(user.QuotaMailBox) ? "Загрузка..." : user.QuotaMailBox;
        StatusSMD = user.StatusSMD ?? string.Empty;
        StatusUZ = user.StatusUZ ?? string.Empty;
        IsSharedMailbox = user.IsSharedMailbox;
        IsBadgesTwoRows = !user.IsSharedMailbox;
        IsExchangeMailbox = user.MailBoxLocation == "Exchange";
        RetentionPolicy = string.Empty;
        MailboxUsedSize = "Загрузка...";

        ParseStatusUZ(user.StatusUZ);

        await Task.Yield();

        _queryLogger.Log(user.Login ?? "", SearchType, 1);

        if (user.Photo != null && user.Photo.Length > 0)
        {
            _ = LoadAvatarFromBytesAsync(user.Photo, loadToken);
        }
        else
        {
            PhotoUrl = $"https://mail.magnit.ru/owa/service.svc/s/GetPersonaPhoto?email={Uri.EscapeDataString(Mail)}&size=HR648x648";
            _ = LoadAvatarBitmapAsync(PhotoUrl, loadToken);
        }

        var preloadTasks = new List<Task>();

        int workerThreads, completionPortThreads;
        System.Threading.ThreadPool.GetAvailableThreads(out workerThreads, out completionPortThreads);

        preloadTasks.Add(Task.Run(() => GetEximMembersPreloadAsync(Login, Mail, user.EximMembers, loadToken)));
        preloadTasks.Add(Task.Run(() => GetExchangeMembersPreloadAsync(Login, Mail, user.ExchangeMembers, loadToken)));
        preloadTasks.Add(Task.Run(() => GetGroupBoxAccessPreloadAsync(Login, DistinguishedName, loadToken)));
        preloadTasks.Add(Task.Run(() => GetMailboxAccessPreloadAsync(Login, DistinguishedName, loadToken)));
        preloadTasks.Add(Task.Run(() => GetOwnerPreloadAsync(Login, loadToken)));
        preloadTasks.Add(Task.Run(() => CheckUserLogFileExistsAsync(Login)));

        if (!string.IsNullOrWhiteSpace(DistinguishedName))
        {
            preloadTasks.Add(Task.Run(() => GetGroupMembersPreloadAsync(Login, DistinguishedName, loadToken)));
        }

        if (!string.IsNullOrWhiteSpace(Mail) && MailBoxLocation == "Exchange")
        {
            _ = UpdateMailboxQuotaAsync(Mail, loadToken);
        }

        if (IsSharedMailbox && !string.IsNullOrWhiteSpace(Mail))
        {
            _ = UpdateRetentionPolicyAsync(Mail, loadToken);
        }

        await Task.WhenAll(preloadTasks);

        LastLogonTime = "Последний вход - Загрузка...";
        DomainController = "КД - Загрузка...";
        _ = GetUserLastLogonAsync(Login, loadToken);

        if (!IsSharedMailbox && !string.IsNullOrWhiteSpace(DistinguishedName))
        {
            _ = RefreshPasswordStatusInternalAsync(loadToken);
        }
    }

    private void ValidateUserFields()
    {
        string loginPrefix = (Login.Contains("@") ? Login.Split('@')[0] : Login).Trim();
        string mailPrefix = (Mail.Contains("@") ? Mail.Split('@')[0] : Mail).Trim();
        bool mailMismatch = !string.IsNullOrEmpty(loginPrefix) && !string.IsNullOrEmpty(mailPrefix) &&
            !loginPrefix.Equals(mailPrefix, StringComparison.OrdinalIgnoreCase);

        MailDisplay = mailMismatch ? Mail + " (Не совпадает с логином)" : Mail;
        HasMailWarning = mailMismatch;

        bool phoneHasLetters = !string.IsNullOrEmpty(MobilePhone) && MobilePhone.Any(char.IsLetter);
        int digitCount = !string.IsNullOrEmpty(MobilePhone) ? MobilePhone.Count(char.IsDigit) : 0;
        bool phoneInvalidDigits = digitCount > 0 && digitCount != 10 && digitCount != 11;
        bool isNonRussian = !string.IsNullOrEmpty(MobilePhone) && MobilePhone.StartsWith("+") &&
            !MobilePhone.StartsWith("+7") && !MobilePhone.StartsWith("+8");

        if (phoneHasLetters)
        {
            MobilePhoneDisplay = MobilePhone + " (\"Буквы в номере\")";
            HasMobilePhoneWarning = true;
        }
        else if (isNonRussian)
        {
            MobilePhoneDisplay = MobilePhone + " (\"Номер не российской нумерации\")";
            HasMobilePhoneWarning = true;
        }
        else if (phoneInvalidDigits)
        {
            MobilePhoneDisplay = MobilePhone + " (\"Неверное количество цифр в номере\")";
            HasMobilePhoneWarning = true;
        }
        else
        {
            MobilePhoneDisplay = MobilePhone;
            HasMobilePhoneWarning = false;
        }
    }

    private void ClearAllCaches()
    {
        _eximCache.Clear();
        _exchangeCache.Clear();
        _groupBoxAccessCache.Clear();
        _mailboxAccessCache.Clear();
        _ownerCache.Clear();
        _groupMembersCache.Clear();
        _maillistMembersCache.Clear();
        _userLogCache.Clear();
    }

    private void ResetAllButtonStates()
    {
        IsGetMemberGroupEnabled = false;
        IsGetEximUserEnabled = false;
        IsGetExchangeUserEnabled = false;
        IsEximExchangeEnabled = false;
        IsGetGroupAccessEnabled = false;
        IsGetMailboxAccessEnabled = false;
        IsGetOwnerEnabled = false;
        IsEximEnabled = false;
        IsExchangeEnabled = false;
        IsGroupAccessEnabled = false;
        IsMailboxAccessEnabled = false;
        IsVladetelIsListEnabled = false;
        IsUserLogEnabled = false;
        IsFindPcEnabled = false;
        IsGroupMemberEnabled = false;
        IsGetHierarchyEnabled = false;
        IsRepadminEnabled = false;
        IsGetInfoEnabled = false;

        IsEximLoading = false;
        IsExchangeLoading = false;
        IsGroupBoxAccessLoading = false;
        IsGroupMemberLoading = false;
        IsMailboxAccessLoading = false;
        IsUserLogLoading = false;
        IsGetVladetelIsListLoading = false;
        IsGetEximUserLoading = false;
        IsGetExchangeUserLoading = false;
        IsEximExchangeLoading = false;
        IsFindPcLoading = false;
    }

    private async Task GetEximMembersPreloadAsync(string login, string mail, string memberDns, CancellationToken token)
    {
        var begin = _postFindLastDate;
        Dispatcher.UIThread.Post(() => IsEximLoading = true);
        
        try
        {
            await Task.Delay(_threadSleepPostFind, token);
            if (_postFindLastDate > begin) return;

            List<UserInfo> members;
            
            if (!string.IsNullOrWhiteSpace(memberDns))
            {
                members = await _adService.GetMembersByDnListAsync(memberDns, token);
            }
            else if (!string.IsNullOrWhiteSpace(mail))
            {
                members = await _adService.GetEximMembersAsync(mail, token);
            }
            else
            {
                members = new List<UserInfo>();
            }
            
            if (_postFindLastDate > begin) return;
            _eximCache[mail] = members;
            Dispatcher.UIThread.Post(() => IsGetEximUserEnabled = members.Count > 0);
        }
        catch
        {
        }
        finally
        {
            Dispatcher.UIThread.Post(() => IsEximLoading = false);
        }
    }

    private async Task GetExchangeMembersPreloadAsync(string login, string mail, string memberDns, CancellationToken token)
    {
        var begin = _postFindLastDate;
        Dispatcher.UIThread.Post(() => IsExchangeLoading = true);
        
        try
        {
            await Task.Delay(_threadSleepPostFind, token);
            if (_postFindLastDate > begin) return;

            List<UserInfo> members;
            
            if (!string.IsNullOrWhiteSpace(memberDns))
            {
                members = await _adService.GetMembersByDnListAsync(memberDns, token);
            }
            else if (!string.IsNullOrWhiteSpace(mail))
            {
                members = await _adService.GetExchangeMembersAsync(mail, token);
            }
            else
            {
                members = new List<UserInfo>();
            }
            
            if (_postFindLastDate > begin) return;
            _exchangeCache[mail] = members;
            Dispatcher.UIThread.Post(() => IsGetExchangeUserEnabled = members.Count > 0);
        }
        catch
        {
        }
        finally
        {
            Dispatcher.UIThread.Post(() => IsExchangeLoading = false);
        }
    }

    private async Task GetGroupBoxAccessPreloadAsync(string login, string dn, CancellationToken token)
    {
        var begin = _postFindLastDate;
        Dispatcher.UIThread.Post(() => IsGroupBoxAccessLoading = true);
        
        try
        {
            if (string.IsNullOrWhiteSpace(dn))
            {
                return;
            }
            
            await Task.Delay(_threadSleepPostFind, token);
            if (_postFindLastDate > begin) return;
            
            var accessList = await _adService.GetGroupBoxAccessAsync(login, dn, token);
            if (_postFindLastDate > begin) return;

            _groupBoxAccessCache[login] = accessList;
            Dispatcher.UIThread.Post(() =>
            {
                if (SearchType != "User") return;
                IsGroupAccessEnabled = accessList != null && accessList.Count > 0;
            });
            
        }
        catch
        {
        }
        finally
        {
            Dispatcher.UIThread.Post(() => IsGroupBoxAccessLoading = false);
        }
    }

    private async Task GetMailboxAccessPreloadAsync(string login, string dn, CancellationToken token)
    {
        var begin = _postFindLastDate;
        Dispatcher.UIThread.Post(() => IsMailboxAccessLoading = true);
        
        try
        {
            if (string.IsNullOrWhiteSpace(dn))
            {
                return;
            }
            
            await Task.Delay(_threadSleepPostFind, token);
            if (_postFindLastDate > begin) return;
            
            var maillist = await _adService.GetMailboxAccessAsync(login, dn, token);
            if (_postFindLastDate > begin) return;

            _mailboxAccessCache[login] = maillist;
            Dispatcher.UIThread.Post(() =>
            {
                if (SearchType != "User") return;
                IsMailboxAccessEnabled = maillist != null && maillist.Count > 0;
            });
            
        }
        catch
        {
        }
        finally
        {
            Dispatcher.UIThread.Post(() => IsMailboxAccessLoading = false);
        }
    }

    private async Task GetOwnerPreloadAsync(string login, CancellationToken token)
    {
        var begin = _postFindLastDate;
        Dispatcher.UIThread.Post(() => IsGetVladetelIsListLoading = true);
        
        try
        {
            await Task.Delay(_threadSleepPostFind, token);
            
            if (_postFindLastDate > begin) 
            {
                return;
            }
            if (token.IsCancellationRequested)
            {
                return;
            }
            
            var ownerDt = await _adService.GetVladetelIsListAsync(login, token);
            
            if (_postFindLastDate > begin) 
            {
                return;
            }
            if (token.IsCancellationRequested)
            {
                return;
            }

            if (ownerDt != null)
            {
                _ownerCache[login] = ownerDt;
                Dispatcher.UIThread.Post(() => IsVladetelIsListEnabled = ownerDt.Rows.Count > 0);
            }
            else
            {
                Dispatcher.UIThread.Post(() => IsVladetelIsListEnabled = false);
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            Dispatcher.UIThread.Post(() => IsVladetelIsListEnabled = false);
        }
        finally
        {
            Dispatcher.UIThread.Post(() => IsGetVladetelIsListLoading = false);
        }
    }

    private async Task GetGroupMembersPreloadAsync(string login, string dn, CancellationToken token)
    {
        var begin = _postFindLastDate;
        Dispatcher.UIThread.Post(() => IsGroupMemberLoading = true);
        
        try
        {
            if (string.IsNullOrWhiteSpace(dn))
            {
                
                return;
            }

            await Task.Delay(_threadSleepPostFind, token);
            if (_postFindLastDate > begin) return;

            var members = await _adService.GetGroupMembersAsync(dn, token);
            if (_postFindLastDate > begin) return;

            _groupMembersCache[dn] = members;
            
        }
        catch
        {
        }
        finally
        {
            Dispatcher.UIThread.Post(() => IsGroupMemberLoading = false);
        }
    }

    private async Task CheckUserLogFileExistsAsync(string login)
    {
        Dispatcher.UIThread.Post(() => IsUserLogLoading = true);
        
        try
        {
            await Task.Run(() =>
            {
                try
                {
                    var settings = AppSettings.Load();
                    string userLogPath = settings.UserLogPath;
                    string filePath = Path.Combine(userLogPath, login + ".txt");
                    string archivePath = Path.Combine(userLogPath, "archive_hnas-xdisk_wScripts", "UserLog", login + ".txt");
                    bool fileExists = File.Exists(filePath) || File.Exists(archivePath);
                    Dispatcher.UIThread.Post(() => IsUserLogEnabled = fileExists);
                    Dispatcher.UIThread.Post(() => IsFindPcEnabled = fileExists);
                    
                }
                catch (Exception ex)
                {
                    
                    Dispatcher.UIThread.Post(() => IsUserLogEnabled = false);
                }
            });
        }
        finally
        {
            Dispatcher.UIThread.Post(() => IsUserLogLoading = false);
        }
    }

    private async Task SearchGroupAsync(string query, CancellationToken token, string? distinguishedName = null)
    {
        IsGetInfoEnabled = true;
        IsRepadminEnabled = true;
        StatusText = $"Поиск группы: {query}...";

        try
        {
            List<UserInfo>? groupInfo = null;

            if (!string.IsNullOrEmpty(distinguishedName))
            {
                groupInfo = await _adService.GetGroupInfoAsync(distinguishedName, token);
            }

            if ((groupInfo == null || groupInfo.Count == 0) && !string.IsNullOrEmpty(query))
            {
                groupInfo = await _adService.GetGroupInfoAsync(query, token);
            }

            if (groupInfo == null || groupInfo.Count == 0)
            {
                FindStatusText = "Не найдена";
                IsFindStatusVisible = false;
                return;
            }

            _boxDt = groupInfo;

            if (groupInfo.Count == 1)
            {
                var g = groupInfo[0];
                _inputBuf = SearchText;
                _postFindLastDate = DateTime.Now;
                _pictureBoxNonVisibleFlag = true;
                FindStatusText = "OK";
                IsFindStatusVisible = true;

                Login = g.Login ?? string.Empty;
                Mail = g.Email ?? string.Empty;
                DisplayName = g.DisplayName ?? string.Empty;
                Description = g.Description ?? string.Empty;
                Vladetel = g.Owner ?? string.Empty;
                DistinguishedName = g.DN ?? string.Empty;
                Department = g.Department ?? string.Empty;
                Company = g.Company ?? string.Empty;
                Title = g.Title ?? string.Empty;
                Phone = g.Phone ?? string.Empty;
                MobilePhone = g.MobilePhone ?? string.Empty;
                ValidateUserFields();
                Manager = g.Manager ?? string.Empty;
                MailHost = g.MailHost ?? string.Empty;
                MailBoxLocation = g.MailBoxLocation ?? string.Empty;
                QuotaMailBox = g.QuotaMailBox ?? string.Empty;
                StatusSMD = g.StatusSMD ?? string.Empty;
                StatusUZ = g.StatusUZ ?? string.Empty;
                ParseStatusUZ(StatusUZ);


                IsGetMemberGroupEnabled = true;
                IsGroupMemberEnabled = true;
                IsGetGroupAccessEnabled = false;
                IsGetMailboxAccessEnabled = false;
                IsGetOwnerEnabled = false;
                IsEximExchangeEnabled = false;
                IsVladetelIsListEnabled = false;
                IsEximEnabled = false;
                IsGetEximUserEnabled = false;
                IsExchangeEnabled = false;
                IsGetExchangeUserEnabled = false;
            }
            else
            {
                FindStatusText = $"{groupInfo.Count} УЗ";
                IsFindStatusVisible = true;
                IsGetInfoEnabled = true;
                IsRepadminEnabled = true;
            }

            _queryLogger.Log(query, SearchType, groupInfo.Count);
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    private async Task SearchMailListAsync(string query, CancellationToken token)
    {
        IsGetInfoEnabled = true;
        IsRepadminEnabled = true;
        StatusText = $"Поиск рассылки: {query}...";

        try
        {
            var mailListInfo = await _adService.GetMailListInfoAsync(query, token);

            if (mailListInfo == null || mailListInfo.Count == 0)
            {
                FindStatusText = "Не найдена";
                IsFindStatusVisible = false;
                return;
            }

            _boxDt = mailListInfo;

            if (mailListInfo.Count == 1)
            {
                var m = mailListInfo[0];
                _inputBuf = SearchText;
                _postFindLastDate = DateTime.Now;
                _pictureBoxNonVisibleFlag = true;
                FindStatusText = "OK";
                IsFindStatusVisible = true;

                Login = m.Login ?? string.Empty;
                Mail = m.Email ?? string.Empty;
                DisplayName = m.DisplayName ?? string.Empty;
                Description = m.Description ?? string.Empty;
                Vladetel = m.Owner ?? string.Empty;
                DistinguishedName = m.DN ?? string.Empty;
                
                if (!string.IsNullOrWhiteSpace(m.Owner))
                {
                    var ownerDisplayNames = new List<string>();
                    var ownerDns = m.Owner.Split(';', StringSplitOptions.RemoveEmptyEntries);
                    foreach (var ownerDn in ownerDns)
                    {
                        try
                        {
                            var ownerInfo = await _adService.GetManagerInfoAsync(ownerDn, token);
                            if (!string.IsNullOrWhiteSpace(ownerInfo))
                            {
                                ownerDisplayNames.Add(ownerInfo);
                            }
                        }
                        catch { }
                    }
                    if (ownerDisplayNames.Count > 0)
                    {
                        Vladetel = string.Join("; ", ownerDisplayNames);
                    }
                }
                Department = m.Department ?? string.Empty;
                Company = m.Company ?? string.Empty;
                Phone = m.Phone ?? string.Empty;
                MobilePhone = m.MobilePhone ?? string.Empty;
                ValidateUserFields();
                Manager = m.Manager ?? string.Empty;
                MailHost = m.MailHost ?? string.Empty;
                MailBoxLocation = m.MailBoxLocation ?? string.Empty;
                QuotaMailBox = m.QuotaMailBox ?? string.Empty;
                StatusSMD = m.StatusSMD ?? string.Empty;
                StatusUZ = m.StatusUZ ?? string.Empty;
                ParseStatusUZ(StatusUZ);

                IsGetEximUserEnabled = false;
                IsGetMailboxAccessEnabled = true;
                IsGetMemberGroupEnabled = false;
                IsGroupMemberEnabled = false;
                IsGetGroupAccessEnabled = false;
                IsGetOwnerEnabled = false;
                IsEximExchangeEnabled = false;
                IsVladetelIsListEnabled = false;
                IsEximEnabled = !string.IsNullOrWhiteSpace(m.EximMembers);
                IsExchangeEnabled = !string.IsNullOrWhiteSpace(m.Email);
                _eximMembersDns = m.EximMembers ?? string.Empty;
                _exchangeMembersDns = string.Empty;

                _ = GetAccessMaillistAsync(Login, DistinguishedName, token);
            }
            else
            {
                FindStatusText = $"{mailListInfo.Count} УЗ";
                IsFindStatusVisible = true;
            }

            _queryLogger.Log(query, SearchType, mailListInfo.Count);
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    private async Task SearchDynamicGroupAsync(string query, CancellationToken token)
    {
        IsGetInfoEnabled = true;
        IsRepadminEnabled = true;
        StatusText = $"Поиск динамической рассылки: {query}...";

        try
        {
            var dynGroupInfo = await _adService.GetDynamicGroupInfoAsync(query, token);

            if (dynGroupInfo == null || dynGroupInfo.Count == 0)
            {
                FindStatusText = "Не найдена";
                IsFindStatusVisible = false;
                return;
            }

            if (dynGroupInfo.Count > 1)
            {
                var exact = dynGroupInfo.FirstOrDefault(d => string.Equals(d.Login, query, StringComparison.OrdinalIgnoreCase));
                if (exact != null)
                    dynGroupInfo = new List<UserInfo> { exact };
            }

            _boxDt = dynGroupInfo;

            if (dynGroupInfo.Count == 1)
            {
                var d = dynGroupInfo[0];
                _inputBuf = SearchText;
                _postFindLastDate = DateTime.Now;
                _pictureBoxNonVisibleFlag = true;
                FindStatusText = "OK";
                IsFindStatusVisible = true;
                IsGetInfoEnabled = true;
                IsRepadminEnabled = true;

                Login = d.Login ?? string.Empty;
                Mail = d.Email ?? string.Empty;
                DisplayName = d.DisplayName ?? string.Empty;
                Description = d.Description ?? string.Empty;
                Vladetel = d.Owner ?? string.Empty;
                DistinguishedName = d.DN ?? string.Empty;
                Department = d.Department ?? string.Empty;
                Company = d.Company ?? string.Empty;
                Phone = d.Phone ?? string.Empty;
                MobilePhone = d.MobilePhone ?? string.Empty;
                ValidateUserFields();
                Manager = d.Manager ?? string.Empty;
                MailHost = d.MailHost ?? string.Empty;
                MailBoxLocation = d.MailBoxLocation ?? string.Empty;
                QuotaMailBox = d.QuotaMailBox ?? string.Empty;
                StatusSMD = d.StatusSMD ?? string.Empty;
                StatusUZ = d.StatusUZ ?? string.Empty;
                ParseStatusUZ(StatusUZ);

                IsGetMailboxAccessEnabled = false;
                IsGetMemberGroupEnabled = false;
                IsGroupMemberEnabled = false;
                IsGetGroupAccessEnabled = false;
                IsGetOwnerEnabled = false;
                IsEximExchangeEnabled = false;
                IsVladetelIsListEnabled = false;
                IsEximEnabled = false;
                IsExchangeEnabled = !string.IsNullOrWhiteSpace(d.Email);
                _eximMembersDns = string.Empty;
                _exchangeMembersDns = string.Empty;
                _ = GetAccessMaillistAsync(Login, DistinguishedName, token);
            }
            else
            {
                FindStatusText = $"{dynGroupInfo.Count} УЗ";
                IsFindStatusVisible = true;
                IsGetInfoEnabled = true;
                IsRepadminEnabled = true;
            }

            _queryLogger.Log(query, SearchType, dynGroupInfo.Count);
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    private async Task SearchComputerAsync(string query, CancellationToken token)
    {
        IsGetInfoEnabled = true;
        IsRepadminEnabled = true;
        StatusText = $"Поиск ПК: {query}...";

        try
        {
            var computerInfo = await _adService.GetComputerInfoAsync(query, token);

            if (computerInfo == null || computerInfo.Count == 0)
            {
                FindStatusText = "Не найден";
                IsFindStatusVisible = false;
                return;
            }

            _boxDt = computerInfo;

            if (computerInfo.Count == 1)
            {
                var c = computerInfo[0];
                _inputBuf = SearchText;
                _postFindLastDate = DateTime.Now;
                _pictureBoxNonVisibleFlag = true;
                FindStatusText = "OK";
                IsFindStatusVisible = true;

                Login = c.Login ?? string.Empty;
                DisplayName = c.DisplayName ?? string.Empty;
                Description = c.Description ?? string.Empty;
                DistinguishedName = c.DN ?? string.Empty;
                StatusUZ = c.StatusUZ ?? string.Empty;
                ParseStatusUZ(StatusUZ);
                Vladetel = c.Owner ?? string.Empty;
                Department = c.Department ?? string.Empty;
                Company = c.Company ?? string.Empty;
                Phone = c.Phone ?? string.Empty;
                MobilePhone = c.MobilePhone ?? string.Empty;
                ValidateUserFields();
                Manager = c.Manager ?? string.Empty;


                IsGetInfoEnabled = true;
                IsRepadminEnabled = true;
                IsGetMemberGroupEnabled = false;
                IsGetGroupAccessEnabled = false;
                IsGetMailboxAccessEnabled = false;
                IsGetOwnerEnabled = false;
                IsEximExchangeEnabled = false;
                IsVladetelIsListEnabled = false;
                IsEximEnabled = false;
                IsExchangeEnabled = false;
                IsGetEximUserEnabled = false;
                IsGetExchangeUserEnabled = false;
            }
            else
            {
                FindStatusText = $"{computerInfo.Count} УЗ";
                IsFindStatusVisible = true;
                IsGetInfoEnabled = true;
                IsRepadminEnabled = true;
            }

            _queryLogger.Log(query, SearchType, computerInfo.Count);
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    private async Task PerformFastSearchAsync(string query, CancellationToken token)
    {
        var begin = DateTime.Now;
        _preFindLastDate = begin;

        await Task.Delay(_threadSleepPreFind, token);

        if (_preFindLastDate > begin)
        {
            _fastFindComplete = false;
            return;
        }

        try
        {
            var results = await _adService.FastSearchAsync(query, SearchType, token);
            var savedOffset = ListScrollOffset;
            SearchResults.Clear();

            foreach (var r in results)
            {
                SearchResults.Add(new SearchResultItem
                {
                    Login = r.Login,
                    DisplayName = r.DisplayName,
                    Description = r.Description,
                    Email = r.Email,
                    Department = r.Department,
                    MobilePhone = r.MobilePhone,
                    DistinguishedName = r.DN ?? string.Empty
                });
            }
            Dispatcher.UIThread.Post(() => ListScrollOffset = savedOffset);

            _fastFindComplete = true;
        }
        catch (Exception)
        {
            _fastFindComplete = false;
        }
    }

    private async Task GetAccessGroupBoxAsync(string login, string dn, CancellationToken token)
    {
        var begin = _postFindLastDate;
        if (!_pictureBoxNonVisibleFlag)
            return;

        var inpBuf = SearchText;
        IsGroupBoxAccessLoading = true;

        try
        {
            await Task.Delay(_threadSleepPostFind, token);

            if (_postFindLastDate > begin)
                return;

            var accessList = await _adService.GetGroupBoxAccessAsync(login, dn, token);

            if (accessList != null && accessList.Count > 0)
            {
                GroupAccessUsers.Clear();
                foreach (var u in accessList)
                {
                    GroupAccessUsers.Add(u);
                }
                IsGetGroupAccessEnabled = true;
            }
            else
            {
                IsGetGroupAccessEnabled = false;
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка получения доступа к ящикам: {ex.Message}";
            IsGetGroupAccessEnabled = false;
        }
        finally
        {
            IsGroupBoxAccessLoading = false;
        }
    }

    private async Task GetAccessMaillistAsync(string login, string dn, CancellationToken token)
    {
        var begin = _postFindLastDate;
        if (!_pictureBoxNonVisibleFlag)
            return;

        var inpBuf = SearchText;
        IsMailboxAccessLoading = true;

        try
        {
            await Task.Delay(_threadSleepPostFind, token);

            if (_postFindLastDate > begin)
                return;

            var maillist = await _adService.GetMailboxAccessAsync(login, dn, token);

            if (maillist != null && maillist.Count > 0)
            {
                MailboxUsers.Clear();
                foreach (var u in maillist)
                {
                    MailboxUsers.Add(u);
                }
                IsGetMailboxAccessEnabled = true;
            }
            else
            {
                IsGetMailboxAccessEnabled = false;
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка получения рассылок: {ex.Message}";
            IsGetMailboxAccessEnabled = false;
        }
        finally
        {
            IsMailboxAccessLoading = false;
        }
    }

    private async Task GetVladetelIsListAsync(string login, CancellationToken token)
    {
        var begin = _postFindLastDate;
        if (!_pictureBoxNonVisibleFlag)
            return;

        IsGetVladetelIsListLoading = true;

        try
        {
            await Task.Delay(_threadSleepPostFind, token);

            if (_postFindLastDate > begin)
                return;

            var ownerDt = await _adService.GetVladetelIsListAsync(login, token);

            if (_postFindLastDate > begin)
                return;

            if (ownerDt != null && ownerDt.Rows.Count > 0)
            {
                _ownerCache[login] = ownerDt;
            }
            IsVladetelIsListEnabled = ownerDt != null && ownerDt.Rows.Count > 0;
        }
        catch
        {
            IsVladetelIsListEnabled = false;
        }
        finally
        {
            IsGetVladetelIsListLoading = false;
        }
    }

    private async Task UpdateMailboxQuotaAsync(string email, CancellationToken token)
    {
        try
        {
            var quotaData = await _adService.GetQuotaDataAsync(email, token);
            
            if (quotaData != null && !token.IsCancellationRequested)
            {
                MailboxUsedSize = quotaData;
            }
            else if (!token.IsCancellationRequested)
            {
                MailboxUsedSize = "Нет данных";
            }
        }
        catch
        {
            if (!token.IsCancellationRequested)
            {
                MailboxUsedSize = "Ошибка загрузки";
            }
        }
    }

    private async Task UpdateRetentionPolicyAsync(string email, CancellationToken token)
    {
        try
        {
            var rp = await _adService.GetRetentionPolicyAsync(email, token);

            if (rp != null && !token.IsCancellationRequested)
            {
                RetentionPolicy = rp;
            }
            else if (!token.IsCancellationRequested)
            {
                RetentionPolicy = "Нет данных";
            }
        }
        catch
        {
            if (!token.IsCancellationRequested)
            {
                RetentionPolicy = "Ошибка загрузки";
            }
        }
    }

    private async Task GetUserLastLogonAsync(string login, CancellationToken token)
    {
        var begin = _postFindLastDate;
        try
        {
            if (string.IsNullOrWhiteSpace(login))
            {
                LastLogonTime = "Последний вход - Нет данных";
                DomainController = "КД - Нет данных";
                return;
            }

            var result = await _adService.GetUserLastLogonAsync(login, token);
            
            if (_postFindLastDate > begin)
            {
                return;
            }
            LastLogonTime = "Последний вход - " + result.lastLogonTime;
            DomainController = "КД - " + result.domainController;
        }
        catch
        {
            if (_postFindLastDate <= begin)
            {
                LastLogonTime = "Последний вход - Ошибка";
                DomainController = "КД - Ошибка";
            }
        }
    }

    private async Task ResolveManagerAsync(string managerDN, CancellationToken token)
    {
        try
        {
            var managerInfo = await _adService.GetManagerInfoAsync(managerDN, token);
            
            if (managerInfo != null)
            {
                Manager = managerInfo;
            }
            else
            {
                Manager = string.Empty;
            }
        }
        catch
        {
            Manager = string.Empty;
        }
    }

    private void ParseStatusUZ(string statusUZ)
    {
        if (string.IsNullOrWhiteSpace(statusUZ))
        {
            AccountStatus = string.Empty;
            HrStatus = string.Empty;
            PasswordDays = string.Empty;
            PasswordBlocked = string.Empty;
            return;
        }

        var lower = statusUZ.ToLowerInvariant();

        if (lower.Contains("disable"))
            AccountStatus = "DISABLE";
        else if (lower.Contains("normal"))
            AccountStatus = "NORMAL";
        else
            AccountStatus = statusUZ.Split(',')[0].Trim();

        if (lower.Contains("hr статус") || lower.Contains("hr status"))
        {
            string searchStr = lower.Contains("hr статус") ? "hr статус" : "hr status";
            var hrIdx = lower.IndexOf(searchStr);
            var hrPart = statusUZ.Substring(hrIdx);
            var commaIdx = hrPart.IndexOf(',');
            HrStatus = commaIdx > 0 ? hrPart.Substring(0, commaIdx).Trim() : hrPart.Trim();
        }
        else
        {
            HrStatus = string.Empty;
        }

        if (lower.Contains("пароль") || lower.Contains("password"))
        {
            string searchStr = lower.Contains("пароль") ? "пароль" : "password";
            var passIdx = lower.IndexOf(searchStr);
            var passPart = statusUZ.Substring(passIdx);
            var commaIdx = passPart.IndexOf(',');
            PasswordDays = commaIdx > 0 ? passPart.Substring(0, commaIdx).Trim() : passPart.Trim();
        }
        else
        {
            PasswordDays = string.Empty;
        }

        if (lower.Contains("блок по паролю: да") || lower.Contains("блокирован") || lower.Contains("lockout"))
        {
            PasswordBlocked = "Блок: Да";
            IsLockedOut = true;
        }
        else
        {
            PasswordBlocked = string.Empty;
            IsLockedOut = false;
        }

        if (lower.Contains("требовать смену пароля") || lower.Contains("требует смены"))
            PasswordRequireChange = true;
        else
            PasswordRequireChange = false;
    }

    private async Task LoadAvatarFromBytesAsync(byte[] photoData, CancellationToken token)
    {
        try
        {
            using var stream = new MemoryStream(photoData);
            var bitmap = new Bitmap(stream);
            if (!token.IsCancellationRequested)
            {
                AvatarBitmap = bitmap;
            }
        }
        catch
        {
            AvatarBitmap = null;
        }
    }

    private async Task LoadAvatarBitmapAsync(string url, CancellationToken token)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(url))
            {
                AvatarBitmap = null;
                return;
            }

            using var httpClient = new System.Net.Http.HttpClient();
            httpClient.Timeout = TimeSpan.FromSeconds(10);
            var response = await httpClient.GetAsync(url, token);
            if (response.IsSuccessStatusCode)
            {
                using var stream = await response.Content.ReadAsStreamAsync(token);
                var bitmap = new Bitmap(stream);
                if (!token.IsCancellationRequested)
                {
                    AvatarBitmap = bitmap;
                }
            }
        }
        catch
        {
            AvatarBitmap = null;
        }
    }

    public void ClearForm()
    {
        CancelAllCommandTokens();
        
        ResetAllButtonStates();
        
        Login = string.Empty;
        Mail = string.Empty;
        DisplayName = string.Empty;
        Description = string.Empty;
        Department = string.Empty;
        Company = string.Empty;
        Phone = string.Empty;
        MobilePhone = string.Empty;
        MobilePhoneDisplay = string.Empty;
        HasMobilePhoneWarning = false;
        MailDisplay = string.Empty;
        HasMailWarning = false;
        Manager = string.Empty;
        DistinguishedName = string.Empty;
        Vladetel = string.Empty;
        MailHost = string.Empty;
        MailBoxLocation = string.Empty;
        MigrateStatus = string.Empty;
        QuotaMailBox = string.Empty;
        StatusSMD = string.Empty;
        StatusUZ = string.Empty;
        AccountStatus = string.Empty;
        HrStatus = string.Empty;
        PasswordDays = string.Empty;
        PasswordBlocked = string.Empty;
        PasswordLastSetText = string.Empty;
        PasswordExpiryText = string.Empty;
        PasswordNeverExpiresText = string.Empty;
        PasswordRequireChange = false;
        IsLockedOut = false;
        MailboxUsedSize = string.Empty;
        LastLogonTime = string.Empty;
        DomainController = string.Empty;
        PhotoUrl = string.Empty;
        AvatarBitmap = null;

        FindStatusText = string.Empty;
        IsFindStatusVisible = false;
        IsUserBadgeVisible = false;
        SelectedUser = null;

        IsGetInfoEnabled = false;
        IsGetHierarchyEnabled = false;
        IsRepadminEnabled = false;
        IsGetMemberGroupEnabled = false;
        IsGetOwnerEnabled = false;
        IsGetEximUserEnabled = false;
        IsGetExchangeUserEnabled = false;
        IsEximExchangeEnabled = false;
        IsGroupAccessEnabled = false;
        IsMailboxAccessEnabled = false;
        IsGetVladetelIsListEnabled = false;
        IsFindPcEnabled = false;
        IsUserLogEnabled = false;
        IsGroupMemberEnabled = false;
        IsEximEnabled = false;
        IsExchangeEnabled = false;

        MemberGroupUsers.Clear();
        OwnerUsers.Clear();
        EximUsers.Clear();
        ExchangeUsers.Clear();
        PcUsers.Clear();
        GroupAccessUsers.Clear();
        MailboxUsers.Clear();

        _boxDt = new List<UserInfo>();

        _eximCache.Clear();
        _exchangeCache.Clear();
        _groupBoxAccessCache.Clear();
        _mailboxAccessCache.Clear();
        _ownerCache.Clear();
        _groupMembersCache.Clear();
        _maillistMembersCache.Clear();
        _userLogCache.Clear();
    }

    public void LoadSearchResultToCards(SearchResultItem item)
    {
        if (item == null) return;


        Login = item.Login ?? string.Empty;
        Mail = item.Email ?? string.Empty;
        DisplayName = item.DisplayName ?? string.Empty;
        Description = item.Description ?? string.Empty;
        Department = item.Department ?? string.Empty;
        Company = string.Empty;
        Phone = string.Empty;
        MobilePhone = item.MobilePhone ?? string.Empty;
        ValidateUserFields();
        Manager = string.Empty;
        DistinguishedName = item.DistinguishedName ?? string.Empty;
        
        StatusText = "Выберите действие";
        FindStatusText = "1 УЗ";
        IsFindStatusVisible = true;
        
        IsGetInfoEnabled = true;
        IsGetHierarchyEnabled = true;
        IsRepadminEnabled = true;
        IsGroupAccessEnabled = false;
        IsMailboxAccessEnabled = false;
        IsFindPcEnabled = true;
        IsUserLogEnabled = true;
        IsEximEnabled = true;
        IsExchangeEnabled = true;
        IsEximExchangeEnabled = true;
        IsGetVladetelIsListEnabled = true;
        
        HasSelectedUser = true;
        IsUserBadgeVisible = true;
    }

    [RelayCommand]
    private async Task SearchAsync()
    {
        var query = Helpers.NormalizeSearchQuery(SearchText?.Trim() ?? string.Empty);
        if (string.IsNullOrWhiteSpace(query))
        {
            ClearForm();
            return;
        }

        var token = GetCommandToken(nameof(SearchAsync));

        ClearForm();

        if (IsUsersSelected)
        {
            await SearchUserByLoginAsync(query, token);
        }
        else if (IsGroupsSelected)
        {
            await SearchGroupAsync(query, token);
        }
        else if (IsMailListsSelected)
        {
            await SearchMailListAsync(query, token);
        }
        else if (IsDynamicGroupSelected)
        {
            await SearchDynamicGroupAsync(query, token);
        }
        else if (IsComputersSelected)
        {
            await SearchComputerAsync(query, token);
        }
    }

    [RelayCommand]
    private void Clear()
    {
        SearchText = string.Empty;
        ClearForm();
    }

    [RelayCommand]
    private async Task GetInfoAsync()
    {

        if (string.IsNullOrWhiteSpace(Login))
        {
            StatusText = "Сначала выполните поиск";
            return;
        }

        StatusText = "Загрузка расширенной информации...";

        var token = GetCommandToken(nameof(GetInfoAsync));

        var window = new ShowInfoWindow();
        _windowManager.OpenWindow(window);

        try
        {
            await window.LoadDataAsync(async (progress) =>
            {
                progress("Загрузка данных...");
                DataTable dataToShow;

                switch (SearchType)
                {
                    case "User":
                        dataToShow = await _adService.GetUserInfoForInfoWindowAsync(Login, token) ?? new DataTable();
                        if (dataToShow.Rows.Count > 0)
                            dataToShow.TableName = $"Инфо: {Login}";
                        break;

                    case "Group":
                        dataToShow = await _adService.GetGroupMoreInfoAsync(Login, token);
                        break;

                    case "DynamicGroup":
                        dataToShow = await _adService.GetDynamicGroupMoreInfoAsync(Login, token);
                        if (dataToShow.Rows.Count > 0)
                            dataToShow.TableName = $"Инфо: {Login}";
                        break;

                    case "MailList":
                        dataToShow = await _adService.GetMaillistMoreInfoAsync(Login, token);
                        if (dataToShow.Rows.Count > 0)
                            dataToShow.TableName = $"Инфо: {Login}";
                        break;

                    case "Computer":
                        dataToShow = await _adService.GetComputerInfoForInfoWindowAsync(Login, token) ?? new DataTable();
                        if (dataToShow.Rows.Count > 0)
                            dataToShow.TableName = $"Инфо: {Login}";
                        break;
                    default:
                        dataToShow = new DataTable();
                        StatusText = "Расширенная информация недоступна";
                        break;
                }

                return dataToShow;
            });

            StatusText = "Готово";
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    public async Task OpenSelectedUserInfoAsync()
    {
        if (SelectedSearchResult == null || string.IsNullOrWhiteSpace(SelectedSearchResult.Login))
        {
            StatusText = "Сначала выберите пользователя из списка";
            return;
        }

        var targetLogin = SelectedSearchResult.Login;

        StatusText = "Загрузка информации...";

        var token = GetCommandToken(nameof(OpenSelectedUserInfoAsync));

        var window = new ShowInfoWindow();
        _windowManager.OpenWindow(window);

        try
        {
            await window.LoadDataAsync(async (progress) =>
            {
                progress("Загрузка данных...");
                var dataToShow = await _adService.GetUserInfoForInfoWindowAsync(targetLogin, token) ?? new DataTable();
                if (dataToShow.Rows.Count > 0)
                    dataToShow.TableName = $"Инфо: {targetLogin}";
                return dataToShow;
            });

            StatusText = "Готово";
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    [RelayCommand]
    private async Task GetGroupMembersAsync()
    {
        if (string.IsNullOrWhiteSpace(DistinguishedName) && SearchType != "DynamicGroup")
            return;

        var token = GetCommandToken(nameof(GetGroupMembersAsync));

        StatusText = "Загрузка участников группы...";
        IsGetMemberGroupEnabled = false;

        var window = new ShowMemberListWindow();
        _windowManager.OpenWindow(window);

        try
        {
            await window.LoadFromServiceAsync(async () =>
            {
                if (SearchType == "DynamicGroup")
                    return await _adService.GetDynamicGroupMembersDataTableAsync(Login, token);
                return await _adService.GetGroupMembersDataTableAsync(DistinguishedName, token);
            });
            StatusText = "Участники группы загружены";
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            IsGetMemberGroupEnabled = true;
        }
    }

    [RelayCommand]
    private async Task GetEximMembersAsync()
    {
        if (string.IsNullOrWhiteSpace(Mail) && string.IsNullOrWhiteSpace(DistinguishedName))
        {
            return;
        }

        var token = GetCommandToken(nameof(GetEximMembersAsync));

        var window = new ShowMemberListWindow();
        _windowManager.OpenWindow(window);

        try
        {
            DataTable dt = await window.LoadFromServiceAsync(async () =>
            {
                string cacheKey = !string.IsNullOrWhiteSpace(Mail) ? Mail : DistinguishedName;
                List<UserInfo> members;

                if (!string.IsNullOrWhiteSpace(_eximMembersDns))
                {
                    members = await _adService.GetMembersByDnListAsync(_eximMembersDns, token);
                }
                else if (SearchType != "MailList" && !string.IsNullOrWhiteSpace(DistinguishedName))
                {
                    members = await _adService.GetGroupBoxAccessAsync(Login, DistinguishedName, token);
                }
                else if (!string.IsNullOrWhiteSpace(Mail))
                {
                    members = await _adService.GetEximMembersAsync(Mail, token);
                }
                else
                {
                    members = new List<UserInfo>();
                }

                EximUsers.Clear();
                foreach (var m in members)
                {
                    EximUsers.Add(m);
                }

                if (members.Count > 0)
                {
                    Dispatcher.UIThread.Post(() => { StatusText = $"Загружено {members.Count} участников Exim"; });
                    return ConvertMembersToDataTable(members, $"Exim: {cacheKey}", "Exim");
                }
                else
                {
                    Dispatcher.UIThread.Post(() => { StatusText = "Участники Exim не найдены для данного пользователя"; });
                    var emptyDt = new DataTable("Empty");
                    emptyDt.Columns.Add("Результат");
                    var row = emptyDt.NewRow();
                    row[0] = "Участники Exim не найдены";
                    emptyDt.Rows.Add(row);
                    return emptyDt;
                }
            });
        }
        catch (Exception ex)
        {
            Dispatcher.UIThread.Post(() => { StatusText = "Ошибка загрузки Exim: " + ex.Message; });
        }
    }

    [RelayCommand]
    private async Task GetExchangeMembersAsync()
    {
        if (string.IsNullOrWhiteSpace(Mail) && string.IsNullOrWhiteSpace(DistinguishedName))
        {
            return;
        }

        var token = GetCommandToken(nameof(GetExchangeMembersAsync));

        var window = new ShowMemberListWindow();
        _windowManager.OpenWindow(window);

        try
        {
            DataTable dt = await window.LoadFromServiceAsync(async () =>
            {
                string cacheKey = !string.IsNullOrWhiteSpace(Mail) ? Mail : DistinguishedName;

                if (SearchType == "DynamicGroup")
                {
                    var dynDt = await _adService.GetDynamicGroupMembersDataTableAsync(Login, token);
                    if (dynDt.Rows.Count > 0)
                    {
                        Dispatcher.UIThread.Post(() => { StatusText = $"Загружено {dynDt.Rows.Count} участников Exchange"; });
                        dynDt.TableName = $"Exchange: {Login}";
                        return dynDt;
                    }
                    else
                    {
                        Dispatcher.UIThread.Post(() => { StatusText = "Участники Exchange не найдены для данной динамической рассылки"; });
                        var emptyDt = new DataTable("Empty");
                        emptyDt.Columns.Add("Результат");
                        var emptyRow = emptyDt.NewRow();
                        emptyRow[0] = "Участники Exchange не найдены";
                        emptyDt.Rows.Add(emptyRow);
                        return emptyDt;
                    }
                }

                List<UserInfo> members;

                if (SearchType == "MailList")
                {
                    members = await _adService.GetMaillistExchangeMembersAsync(Mail, token);
                }
                else if (!string.IsNullOrWhiteSpace(_exchangeMembersDns))
                {
                    members = await _adService.GetMembersByDnListAsync(_exchangeMembersDns, token);
                }
                else if (SearchType != "MailList" && !string.IsNullOrWhiteSpace(DistinguishedName))
                {
                    members = await _adService.GetGroupBoxAccessAsync(Login, DistinguishedName, token);
                }
                else if (!string.IsNullOrWhiteSpace(Mail))
                {
                    members = await _adService.GetExchangeMembersAsync(Mail, token);
                }
                else
                {
                    members = new List<UserInfo>();
                }

                ExchangeUsers.Clear();
                foreach (var m in members)
                {
                    ExchangeUsers.Add(m);
                }

                if (members.Count > 0)
                {
                    Dispatcher.UIThread.Post(() => { StatusText = $"Загружено {members.Count} участников Exchange"; });
                    return ConvertMembersToDataTable(members, $"Exchange: {cacheKey}", "Exchange");
                }
                else
                {
                    Dispatcher.UIThread.Post(() => { StatusText = "Участники Exchange не найдены для данного пользователя"; });
                    var emptyDt = new DataTable("Empty");
                    emptyDt.Columns.Add("Результат");
                    var row = emptyDt.NewRow();
                    row[0] = "Участники Exchange не найдены";
                    emptyDt.Rows.Add(row);
                    return emptyDt;
                }
            });
        }
        catch (Exception ex)
        {
            Dispatcher.UIThread.Post(() => { StatusText = $"Ошибка загрузки Exchange: {ex.Message}"; });
        }
    }

    [RelayCommand]
    private async Task GetOwnerAsync()
    {
        
        
        if (string.IsNullOrWhiteSpace(Login))
        {
            
            StatusText = "Сначала выполните поиск пользователя";
            return;
        }

        var token = GetCommandToken(nameof(GetOwnerAsync));

        StatusText = "Загрузка владельцев ИС...";

        var window = new ShowOwnerWindow();
        _windowManager.OpenWindow(window);

        try
        {
            DataTable dt = await window.LoadFromServiceAsync(async () =>
            {
                var result = await _adService.GetVladetelIsListAsync(Login, token);
                StatusText = $"Загружено {result?.Rows.Count ?? 0} владельцев";
                if (result != null && result.Rows.Count > 0)
                {
                    result.TableName = $"Владельцы ИС: {Login}";
                }
                return result ?? new DataTable();
            });
            
            if (dt != null && dt.Rows.Count > 0)
            {
            }
            
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            
        }
    }

    [RelayCommand]
    private async Task GetHierarchyAsync()
    {
        

        if (string.IsNullOrWhiteSpace(Login))
        {
            
            StatusText = "Сначала выполните поиск пользователя";
            return;
        }

        StatusText = "Загрузка иерархии...";

        var token = GetCommandToken(nameof(GetHierarchyAsync));

        try
        {
            var window = new ShowHierarchyWindow();
            _windowManager.OpenWindow(window);
            
            var hierarchyDt = await window.LoadFromServiceAsync(() =>
                _adService.GetHierarchyAsync(Login, token));
            
            if (hierarchyDt != null && hierarchyDt.Rows.Count > 0)
            {
                StatusText = $"Иерархия загружена ({hierarchyDt.Rows.Count} записей)";
            }
            else
            {
                StatusText = "Иерархия не найдена";
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            
        }
    }

    [RelayCommand]
    private async Task OpenUserGridAsync()
    {
        StatusText = "Открытие списка пользователей...";
        await Task.Delay(100);
        StatusText = "Готово";
    }

    [RelayCommand]
    private async Task OpenGroupsListGetInfo()
    {
        IsGroupsSelected = true;
        await GetInfoAsync();
    }

    [RelayCommand]
    private async Task OpenGroupsListGetMembers()
    {
        IsGroupsSelected = true;
        await GetGroupMemberList();
    }

    [RelayCommand]
    private async Task OpenMaillistListGetInfo()
    {
        IsMailListsSelected = true;
        await GetInfoAsync();
    }

    [RelayCommand]
    private async Task OpenMaillistListGetLargeInfo()
    {
        IsMailListsSelected = true;
        await GetInfoAsync();
    }

    [RelayCommand]
    private async Task OpenMaillistListGetMembers()
    {
        IsMailListsSelected = true;
        await GetMaillistMemberList();
    }

    [RelayCommand]
    private async Task OpenDynamicDistributionGroupListGetInfo()
    {
        IsDynamicGroupSelected = true;
        await GetInfoAsync();
    }

    [RelayCommand]
    private void OpenDynamicDistributionGroupListGetMembers()
    {
        StatusText = "Динамические группы не имеют участников...";
    }

    [RelayCommand]
    private async Task OpenPcList()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл списка ПК");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Загрузка списка ПК...";

        var window = new ShowMemberListWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var dataTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            var items = new List<string>();
            foreach (System.Data.DataRow row in dataTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < dataTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                    items.Add(row[0].ToString()!.Trim());
            }

            dataTable.Clear();
            dataTable.Dispose();

            var resultDt = new System.Data.DataTable("ПК: Список");
            resultDt.Columns.Add(dataTable.Columns[0].ColumnName + " (source)");
            resultDt.Columns.Add("Имя");
            resultDt.Columns.Add("ОС");
            resultDt.Columns.Add("Сервис пак");
            resultDt.Columns.Add("Состоит в группах");
            resultDt.Columns.Add("distinguishedName");
            resultDt.Columns.Add("Создана");
            resultDt.Columns.Add("Статус УЗ");

            var dtLock = new object();
            using var semaphore = new SemaphoreSlim(8);
            var tasks = items.Select(async item =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var pcDt = await _adService.GetComputerInfoDataTableAsync(item, CancellationToken.None);
                    if (pcDt != null && pcDt.Rows.Count > 0)
                    {
                        foreach (System.Data.DataRow pcRow in pcDt.Select())
                        {
                            var groupMembers = pcRow["Состоит в группах"]?.ToString()?.Split('|', StringSplitOptions.RemoveEmptyEntries) ?? Array.Empty<string>();
                            var cleanGroups = groupMembers
                                .Select(g => g.Replace("CN=", ""))
                                .Select(g => g.Contains(",") ? g.Substring(0, g.IndexOf(",")) : g)
                                .Where(g => !string.IsNullOrWhiteSpace(g));
                            pcRow["Состоит в группах"] = string.Join("; ", cleanGroups) + ";";

                            var sourceCol = resultDt.Columns[0].ColumnName;
                            var newRow = resultDt.NewRow();
                            newRow[sourceCol] = item;
                            newRow["Имя"] = pcRow["Имя"];
                            newRow["ОС"] = pcRow["ОС"];
                            newRow["Сервис пак"] = pcRow["Сервис пак"];
                            newRow["Состоит в группах"] = pcRow["Состоит в группах"];
                            newRow["distinguishedName"] = pcRow["distinguishedName"];
                            newRow["Создана"] = pcRow["Создана"];
                            newRow["Статус УЗ"] = pcRow["Статус УЗ"];
                            lock (dtLock) { resultDt.Rows.Add(newRow); }
                        }
                    }
                }
                catch { }
                finally
                {
                    semaphore.Release();
                }
            }).ToArray();
            await Task.WhenAll(tasks);

            StatusText = $"Загружено {resultDt.Rows.Count} ПК из файла";
            return resultDt;
        });
    }

    [RelayCommand]
    private async Task OwnerSearchLogin()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл списка владельцев");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Поиск владельцев по логину...";

        var window = new ShowOwnerWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var sourceTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            var items = new List<string>();
            foreach (System.Data.DataRow row in sourceTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < sourceTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                    items.Add(row[0].ToString()!.Trim());
            }
            sourceTable.Clear();
            sourceTable.Dispose();

            var sourceColName = "source";
            var resultDt = new System.Data.DataTable("Владельцы ИС");
            resultDt.Columns.Add(sourceColName);
            resultDt.Columns.Add("Логин");
            resultDt.Columns.Add("ФИО");
            resultDt.Columns.Add("Должность");
            resultDt.Columns.Add("Отдел");
            resultDt.Columns.Add("Компания");
            resultDt.Columns.Add("Тип ресурса");
            resultDt.Columns.Add("Объект");
            resultDt.Columns.Add("Вывод. имя ресурса");
            resultDt.Columns.Add("Описание ресурса");

            var usersFound = new Dictionary<string, string>();
            var dtLock = new object();

            using var semaphore = new SemaphoreSlim(8);
            var tasks = items.Select(async item =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var userList = await _adService.GetUserInfoAsync(item, CancellationToken.None);
                    if (userList.Count > 0)
                    {
                        var login = userList[0].Login;
                        var moreInfo = await _adService.GetUserMoreInfoAsync(login, CancellationToken.None);
                        var vladetelDt = await _adService.GetVladetelIsListAsync(login, CancellationToken.None);

                        lock (dtLock)
                        {
                            foreach (System.Data.DataRow vr in vladetelDt.Select())
                            {
                                var newRow = resultDt.NewRow();
                                newRow[sourceColName] = item;
                                newRow["Логин"] = login;
                                newRow["ФИО"] = moreInfo?.FullName ?? "";
                                newRow["Должность"] = moreInfo?.JobTitle ?? "";
                                newRow["Отдел"] = moreInfo?.Department ?? "";
                                newRow["Компания"] = moreInfo?.Company ?? "";
                                newRow["Тип ресурса"] = vr["Тип"];
                                newRow["Объект"] = vr["Объект"];
                                newRow["Вывод. имя ресурса"] = vr["Вывод. имя"];
                                newRow["Описание ресурса"] = vr["Описание"];
                                resultDt.Rows.Add(newRow);
                            }
                        }
                    }
                }
                catch { }
                finally
                {
                    semaphore.Release();
                }
            }).ToArray();
            await Task.WhenAll(tasks);

            StatusText = $"Загружено {resultDt.Rows.Count} записей о владельцах из файла";
            return resultDt;
        });
    }

    [RelayCommand]
    private async Task OwnerSearchFio()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл списка владельцев");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Поиск владельцев по ФИО...";

        var window = new ShowOwnerWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var sourceTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            var fioDt = new System.Data.DataTable();
            fioDt.Columns.Add("ФИО");
            foreach (System.Data.DataRow row in sourceTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < sourceTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                {
                    var newRow = fioDt.NewRow();
                    newRow["ФИО"] = row[0].ToString()!.Trim();
                    fioDt.Rows.Add(newRow);
                }
            }
            sourceTable.Clear();
            sourceTable.Dispose();

            var resultDt = await _adService.GetVladetelIsListByFIOAsync(fioDt, CancellationToken.None);

            StatusText = $"Загружено {resultDt.Rows.Count} записей о владельцах из файла";
            return resultDt;
        });
    }

    [RelayCommand]
    private async Task OpenUsersList()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл списка пользователей");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Загрузка списка пользователей...";

        var window = new ShowMemberListWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var dataTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            if (dataTable == null || dataTable.Columns.Count == 0)
            {
                StatusText = "Файл списка пользователей пуст или не содержит колонок";
                return new System.Data.DataTable("Пользователи: Список");
            }

            var items = new List<string>();
            foreach (System.Data.DataRow row in dataTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < dataTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                    items.Add(row[0].ToString()!.Trim());
            }

            dataTable.Clear();
            dataTable.Dispose();

            var resultDt = new System.Data.DataTable("Пользователи: Список");
            resultDt.Columns.Add(dataTable.Columns[0].ColumnName + " (source)");
            resultDt.Columns.Add("Логин");
            resultDt.Columns.Add("Вывод. имя");
            resultDt.Columns.Add("Телефон");
            resultDt.Columns.Add("Почта");
            resultDt.Columns.Add("Статус УЗ");

            var dtLock = new object();
            using var semaphore = new SemaphoreSlim(8);
            var tasks = items.Select(async item =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var userList = await _adService.GetUserInfoAsync(item, CancellationToken.None);

                    var sourceCol = resultDt.Columns[0].ColumnName;
                    foreach (var user in userList)
                    {
                        var moreInfoDt = await _adService.GetUserMoreInfoTableAsync(user.Login, CancellationToken.None);
                        var newRow = resultDt.NewRow();
                        newRow[sourceCol] = item;
                        newRow["Логин"] = user.Login;
                        newRow["Вывод. имя"] = user.DisplayName;
                        newRow["Телефон"] = "";
                        newRow["Почта"] = user.Email;
                        newRow["Статус УЗ"] = user.AccountStatus;
                        if (moreInfoDt != null)
                        {
                            foreach (System.Data.DataRow mir in moreInfoDt.Select())
                            {
                                var attr = mir["Атрибут"]?.ToString();
                                if (attr == "Моб. телефон" || attr == "Телефон")
                                    newRow["Телефон"] = mir["Значение"]?.ToString() ?? "";
                            }
                        }
                        lock (dtLock) { resultDt.Rows.Add(newRow); }
                    }
                }
                catch { }
                finally
                {
                    semaphore.Release();
                }
            }).ToArray();
            await Task.WhenAll(tasks);

            StatusText = $"Загружено {resultDt.Rows.Count} пользователей из файла";
            return resultDt;
        });
    }

    [RelayCommand]
    private async Task GroupGetInfo()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл списка групп");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Загрузка списка групп...";

        var window = new ShowMemberListWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var dataTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            var items = new List<string>();
            foreach (System.Data.DataRow row in dataTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < dataTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                    items.Add(row[0].ToString()!.Trim());
            }

            dataTable.Clear();
            dataTable.Dispose();

            var resultDt = new System.Data.DataTable("Группы: Список");
            resultDt.Columns.Add(dataTable.Columns[0].ColumnName + " (source)");
            resultDt.Columns.Add("Логин");
            resultDt.Columns.Add("distinguishedName");
            resultDt.Columns.Add("Почта");
            resultDt.Columns.Add("Вывод. имя");
            resultDt.Columns.Add("Описание");
            resultDt.Columns.Add("Владелец");
            resultDt.Columns.Add("Создана");

            var dtLock = new object();
            using var semaphore = new SemaphoreSlim(8);
            var tasks = items.Select(async item =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var dt = await _adService.GetGroupMoreInfoAsync(item, CancellationToken.None);
                    if (dt != null && dt.Rows.Count > 0)
                    {
                        var sourceCol = resultDt.Columns[0].ColumnName;
                        foreach (System.Data.DataRow r in dt.Select())
                        {
                            var newRow = resultDt.NewRow();
                            newRow[sourceCol] = item;
                            newRow["Логин"] = r["Логин"];
                            newRow["distinguishedName"] = r["distinguishedName"];
                            newRow["Почта"] = r["Почта"];
                            newRow["Вывод. имя"] = r["Вывод. имя"];
                            newRow["Описание"] = r["Описание"];
                            newRow["Владелец"] = r["Владелец"];
                            newRow["Создана"] = r["Создана"];
                            lock (dtLock) { resultDt.Rows.Add(newRow); }
                        }
                    }
                }
                catch { }
                finally
                {
                    semaphore.Release();
                }
            }).ToArray();
            await Task.WhenAll(tasks);

            StatusText = $"Загружено {resultDt.Rows.Count} групп из файла";
            return resultDt;
        });
    }

    [RelayCommand]
    private async Task MaillistGetInfo()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл списка рассылок");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Загрузка списка рассылок...";

        var window = new ShowMemberListWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var dataTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            var items = new List<string>();
            foreach (System.Data.DataRow row in dataTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < dataTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                    items.Add(row[0].ToString()!.Trim());
            }

            dataTable.Clear();
            dataTable.Dispose();

            var resultDt = new System.Data.DataTable("Рассылки: Список");
            resultDt.Columns.Add(dataTable.Columns[0].ColumnName + " (source)");
            resultDt.Columns.Add("Логин");
            resultDt.Columns.Add("distinguishedName");
            resultDt.Columns.Add("Вывод. имя");
            resultDt.Columns.Add("Описание");
            resultDt.Columns.Add("Владелец");
            resultDt.Columns.Add("Почта");

            var dtLock = new object();
            using var semaphore = new SemaphoreSlim(8);
            var tasks = items.Select(async item =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var dt = await _adService.GetMailListInfoDataTableAsync(item, CancellationToken.None);
                    if (dt != null)
                    {
                        var sourceCol = resultDt.Columns[0].ColumnName;
                        foreach (System.Data.DataRow r in dt.Select())
                        {
                            var newRow = resultDt.NewRow();
                            newRow[sourceCol] = item;
                            newRow["Логин"] = r["Логин"];
                            newRow["distinguishedName"] = r["distinguishedName"];
                            newRow["Вывод. имя"] = r["Вывод. имя"];
                            newRow["Описание"] = r["Описание"];
                            newRow["Владелец"] = r["Владелец"];
                            newRow["Почта"] = r["Почта"];
                            lock (dtLock) { resultDt.Rows.Add(newRow); }
                        }
                    }
                }
                catch { }
                finally
                {
                    semaphore.Release();
                }
            }).ToArray();
            await Task.WhenAll(tasks);

            StatusText = $"Загружено {resultDt.Rows.Count} рассылок из файла";
            return resultDt;
        });
    }

    [RelayCommand]
    private async Task MaillistGetLargeInfo()
    {
        IsMailListsSelected = true;
        await GetInfoAsync();
    }

    [RelayCommand]
    private async Task DynamicGroupGetInfo()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл динамических групп рассылки");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Загрузка списка динамических рассылок...";

        var window = new ShowMemberListWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var dataTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            var items = new List<string>();
            foreach (System.Data.DataRow row in dataTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < dataTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                    items.Add(row[0].ToString()!.Trim());
            }

            dataTable.Clear();
            dataTable.Dispose();

            var resultDt = new System.Data.DataTable("Динамические рассылки: Список");

            var dtLock = new object();
            using var semaphore = new SemaphoreSlim(8);
            var tasks = items.Select(async item =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var type = item.Contains("@") ? "mail" : "cn";
                    var groupDt = await _adService.GetDynamicDistributionGroupInfoDataTableAsync(item, type, CancellationToken.None);

                    if (groupDt != null && groupDt.Rows.Count > 0)
                    {
                        foreach (System.Data.DataRow groupRow in groupDt.Select())
                        {
                            var moreInfoDt = await _adService.GetDynamicGroupMoreInfoAsync(groupRow["Логин"]?.ToString() ?? "", CancellationToken.None);
                            if (moreInfoDt != null)
                            {
                                foreach (System.Data.DataRow miRow in moreInfoDt.Select())
                                {
                                    foreach (System.Data.DataColumn col in miRow.Table.Columns)
                                    {
                                        if (!resultDt.Columns.Contains(col.ColumnName))
                                            resultDt.Columns.Add(col.ColumnName);
                                    }
                                    var newRow = resultDt.NewRow();
                                    foreach (System.Data.DataColumn col in miRow.Table.Columns)
                                    {
                                        newRow[col.ColumnName] = miRow[col];
                                    }
                                    lock (dtLock) { resultDt.Rows.Add(newRow); }
                                }
                            }
                        }
                    }
                }
                catch { }
                finally
                {
                    semaphore.Release();
                }
            }).ToArray();
            await Task.WhenAll(tasks);

            StatusText = $"Загружено {resultDt.Rows.Count} динамических рассылок из файла";
            return resultDt;
        });
    }

    [RelayCommand]
    private async Task GetEximUser()
    {
        await GetEximMembersAsync();
    }

    [RelayCommand]
    private async Task GetExchangeUser()
    {
        await GetExchangeMembersAsync();
    }

    [RelayCommand]
    private async Task OpenRepadminAsync()
    {
        
        if (string.IsNullOrWhiteSpace(Login))
        {
            StatusText = "Сначала выполните поиск";
            return;
        }

        StatusText = "Открытие Repadmin...";
        var repadminWindow = new RepadminWindow(Login);
        _windowManager.OpenWindow(repadminWindow);
        StatusText = "Готово";
    }

    [RelayCommand]
    private async Task EximExchangeAsync()
    {
        
        if (string.IsNullOrWhiteSpace(Mail))
        {
            
            StatusText = "У пользователя нет почты";
            return;
        }

        StatusText = "Загрузка Exim <-> Exchange...";

        var token = GetCommandToken(nameof(EximExchangeAsync));

        var window = new ShowEximExchangeWindow();
        _windowManager.OpenWindow(window);

        try
        {
            var resultDt = await window.LoadFromServiceAsync(async () =>
            {
                var eximMembers = await _adService.GetEximMembersAsync(Mail, token);
                var exchangeMembers = await _adService.GetExchangeMembersAsync(Mail, token);

                var eximLogins = eximMembers.Select(m => m.Login).ToHashSet();
                var exchangeLogins = exchangeMembers.Select(m => m.Login).ToHashSet();

                var onlyInExchange = exchangeMembers.Where(m => !eximLogins.Contains(m.Login)).ToList();
                var onlyInExim = eximMembers.Where(m => !exchangeLogins.Contains(m.Login)).ToList();

                var dt = new DataTable();
                dt.Columns.Add("Присутствует в системе");
                dt.Columns.Add("Логин");
                dt.Columns.Add("ФИО");
                dt.Columns.Add("Почта");
                dt.Columns.Add("Статус УЗ");

                foreach (var member in onlyInExchange)
                {
                    var userDt = await _adService.GetUserByDnAsync(member.DN, token);
                    if (userDt.Rows.Count >= 1)
                    {
                        var row = dt.NewRow();
                        row["Присутствует в системе"] = "Exchange";
                        row["Логин"] = userDt.Rows[0]["Логин"];
                        row["ФИО"] = userDt.Rows[0]["Вывод. имя"];
                        row["Почта"] = userDt.Rows[0]["Почта"];
                        row["Статус УЗ"] = userDt.Rows[0]["Статус УЗ"];
                        dt.Rows.Add(row);
                    }
                }

                foreach (var member in onlyInExim)
                {
                    var userDt = await _adService.GetUserByDnAsync(member.DN, token);
                    if (userDt.Rows.Count >= 1)
                    {
                        var row = dt.NewRow();
                        row["Присутствует в системе"] = "Exim";
                        row["Логин"] = userDt.Rows[0]["Логин"];
                        row["ФИО"] = userDt.Rows[0]["Вывод. имя"];
                        row["Почта"] = userDt.Rows[0]["Почта"];
                        row["Статус УЗ"] = userDt.Rows[0]["Статус УЗ"];
                        dt.Rows.Add(row);
                    }
                }

                return dt;
            });

            if (resultDt.Rows.Count > 0)
            {
                resultDt.TableName = $"{Login}: разница в членах Exim <-> Exchange";
                IsEximExchangeEnabled = true;
                StatusText = "Готово";
            }
            else
            {
                StatusText = "Нет различий в членах Exim и Exchange";
                IsEximExchangeEnabled = false;
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    [RelayCommand]
    private async Task GetGroupAccessAsync()
    {
        
        if (string.IsNullOrWhiteSpace(DistinguishedName))
        {
            
            StatusText = "Сначала выполните поиск пользователя";
            return;
        }

        StatusText = "Загрузка доступа к ящикам...";

        var token = GetCommandToken(nameof(GetGroupAccessAsync));
        
        var window = new ShowMailboxListWindow();
        _windowManager.OpenWindow(window);
        
        try
        {
            var dt = await window.LoadFromServiceAsync(() => 
                _adService.GetGroupBoxAccessDataTableAsync(Login, DistinguishedName, token));
            
            if (dt != null && dt.Rows.Count > 0)
            {
                dt.TableName = $"Доступ к ящикам: {Login}";
                StatusText = $"Загружено {dt.Rows.Count} записей";
                IsGroupAccessEnabled = true;
            }
            else
            {
                StatusText = "Нет данных для отображения";
                IsGroupAccessEnabled = false;
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            
        }
    }

    [RelayCommand]
    private async Task GetMailboxAccessAsync()
    {
        
        if (string.IsNullOrWhiteSpace(DistinguishedName))
        {
            
            StatusText = "Сначала выполните поиск пользователя";
            return;
        }

        StatusText = "Загрузка рассылок...";

        var token = GetCommandToken(nameof(GetMailboxAccessAsync));
        
        var window = new ShowMaillistWindow();
        _windowManager.OpenWindow(window);
        
        try
        {
            var dt = await window.LoadFromServiceAsync(() => 
                _adService.GetMailboxAccessDataTableAsync(Login, DistinguishedName, token));
            
            if (dt != null && dt.Rows.Count > 0)
            {
                dt.TableName = $"Рассылки: {Login}";
                StatusText = $"Загружено {dt.Rows.Count} записей";
                IsMailboxAccessEnabled = true;
            }
            else
            {
                StatusText = "Нет данных для отображения";
                IsMailboxAccessEnabled = false;
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            
        }
    }

    [RelayCommand]
    private async Task FindPcAsync()
    {
        
        if (string.IsNullOrWhiteSpace(Login))
        {
            
            StatusText = "Сначала выполните поиск пользователя";
            return;
        }

        StatusText = "Загрузка UserLog...";
        IsFindPcLoading = true;
        
        var window = new FindPCWindow();
        _windowManager.OpenWindow(window);
        
        try
        {
            DataTable dt = await window.LoadFromServiceAsync(async () =>
            {
                if (_userLogCache.TryGetValue(Login, out var cachedDt) && cachedDt.Rows.Count > 0)
                {
                    StatusText = $"Загружено из кэша {cachedDt.Rows.Count} записей";
                    return cachedDt;
                }
                else
                {
                    var result = await Task.Run(() => ReadUserLogFile(Login));
                    if (result.Rows.Count > 0)
                    {
                        _userLogCache[Login] = result;
                    }
                    StatusText = $"Загружено {result.Rows.Count} записей";
                    return result;
                }
            });

            if (dt.Rows.Count > 0)
            {
                IsFindPcEnabled = true;
            }
            else
            {
                StatusText = "Таких данных не найдено. Возможно, отсутствует файл лога для данного пользователя.";
                IsFindPcEnabled = false;
            }
        }
        catch (Exception ex)
        {
            
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            IsFindPcLoading = false;
            
        }
    }

    private DataTable ReadUserLogFile(string login)
    {
        

        var dt = new DataTable();
        dt.TableName = $"{login}: UserLog.";
        dt.Columns.Add("Дата", typeof(DateTime));
        dt.Columns.Add("ПК");
        dt.Columns.Add("ip адрес ПК");
        dt.Columns.Add("Контроллер домена");
        dt.Columns.Add("IP адрес Контроллера домена");

        var settings = AppSettings.Load();
        string userLogPath = settings.UserLogPath;
        string archivePath = Path.Combine(userLogPath, "archive_hnas-xdisk_wScripts", "UserLog");
        string filePath = Path.Combine(userLogPath, login + ".txt");
        string archiveFilePath = Path.Combine(archivePath, login + ".txt");

        
        
        

        var linesSet = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        if (File.Exists(filePath))
        {
            try
            {
                foreach (var line in File.ReadAllLines(filePath))
                    linesSet.Add(line);
            }
            catch { }
        }

        if (File.Exists(archiveFilePath))
        {
            try
            {
                foreach (var line in File.ReadAllLines(archiveFilePath))
                    linesSet.Add(line);
            }
            catch { }
        }

        System.Text.RegularExpressions.Regex dateRegex = new System.Text.RegularExpressions.Regex(@"^\d{2}\.\d{2}\.\d{4}$");
        System.Text.RegularExpressions.Regex timeRegex = new System.Text.RegularExpressions.Regex(@"^(\d{2}|\d):\d{2}:\d{2}$");

        var allLines = linesSet.ToList();
        foreach (var line in allLines)
        {
            var array = line.Split(new char[] { ' ', ';' }, StringSplitOptions.RemoveEmptyEntries);
            if (array.Length >= 3 && dateRegex.IsMatch(array[0]) && timeRegex.IsMatch(array[1]))
            {
                DataRow row = dt.NewRow();
                try
                {
                    string dateStr = array[0] + " " + array[1];
                    if (DateTime.TryParseExact(dateStr, "dd.MM.yyyy HH:mm:ss",
                        System.Globalization.CultureInfo.InvariantCulture,
                        System.Globalization.DateTimeStyles.None, out DateTime parsedDate))
                    {
                        row["Дата"] = parsedDate;
                    }
                }
                catch { }
                row["ПК"] = array[2];
                if (array.Length >= 6)
                {
                    row["ip адрес ПК"] = array[3].Trim('[', ']');
                    row["Контроллер домена"] = array[4];
                    row["IP адрес Контроллера домена"] = array[5].Trim('[', ']');
                }
                dt.Rows.Add(row);
            }
        }

        

        var dv = dt.DefaultView;
        dv.Sort = "Дата DESC";
        dt = dv.ToTable();

        return dt;
    }

    [RelayCommand]
    private async Task HistoryAsync()
    {
        var historyDT = _queryLogger.GetHistory();
        historyDT.TableName = string.IsNullOrWhiteSpace(Login) ? "История запросов" : $"История запросов: {Login}";
        var window = new ShowHistoryWindow();
        _windowManager.OpenWindow(window);
        await window.LoadDataAsync(async (progress) =>
        {
            return historyDT;
        });
    }

    [RelayCommand]
    private void CompareGroups()
    {
        _windowManager.OpenWindow<CompareGroupsWindow>();
    }

    [RelayCommand]
    private void SearchByAttributes()
    {
        _windowManager.OpenWindow<SearchByAttributesWindow>();
    }

    [RelayCommand]
    private void PasswordOperations()
    {
        if (string.IsNullOrEmpty(Login))
        {
            return;
        }
        var window = new PasswordOperationsWindow(this);
        _windowManager.OpenWindow(window);
    }

    [RelayCommand]
    private void ExchangeMenu()
    {
        if (string.IsNullOrEmpty(Login))
        {
            return;
        }
        var window = new ExchangeInfoWindow(Mail ?? "");
        _windowManager.OpenWindow(window);
    }

    [RelayCommand]
    private void About()
    {
        _windowManager.OpenWindow<AboutWindow>();
    }

    [RelayCommand]
    private void OpenSettings()
    {
        _windowManager.OpenWindow<SettingsWindow>();
    }

    public ICommand RefreshCommand { get; }

    private void ExecuteRefresh()
    {
        var user = SelectedUser;
        if (user == null || string.IsNullOrWhiteSpace(user.Login))
        {
            StatusText = "Нет выбранного пользователя для обновления";
            return;
        }

        StatusText = "Обновление...";
        _ = SearchUserByLoginAsync(user.Login, CancellationToken.None);
    }

    [RelayCommand]
    private async Task GetGroupMemberList()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл списка групп");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Загрузка списка участников групп...";

        var window = new ShowMailboxListWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var dataTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            var items = new List<string>();
            foreach (System.Data.DataRow row in dataTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < dataTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                    items.Add(row[0].ToString()!.Trim());
            }

            dataTable.Clear();
            dataTable.Dispose();

            var sourceColName = dataTable.Columns.Count > 0 ? dataTable.Columns[0].ColumnName + " (source)" : "source";
            var resultDt = new System.Data.DataTable("Участники групп");

            var dtLock = new object();
            using var semaphore = new SemaphoreSlim(8);
            var tasks = items.Select(async item =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var type = item.Contains("@") ? "mail" : "cn";
                    var groupDt = await _adService.GetGroupInfoDataTableAsync(item, type, CancellationToken.None);
                    if (groupDt != null && groupDt.Rows.Count > 0)
                    {
                        foreach (System.Data.DataRow groupRow in groupDt.Select())
                        {
                            var membersDt = await _adService.GetGroupMembersDataTableAsync(groupRow["distinguishedName"]?.ToString() ?? "", CancellationToken.None);
                            if (membersDt != null)
                            {
                                lock (dtLock)
                                {
                                    foreach (System.Data.DataRow memberRow in membersDt.Select())
                                    {
                                        var newRow = resultDt.NewRow();
                                        newRow[sourceColName] = item;
                                        foreach (System.Data.DataColumn col in groupRow.Table.Columns)
                                        {
                                            var colName = "Группа " + col.ColumnName;
                                            if (!resultDt.Columns.Contains(colName))
                                                resultDt.Columns.Add(colName);
                                            newRow[colName] = groupRow[col];
                                        }
                                        foreach (System.Data.DataColumn col in memberRow.Table.Columns)
                                        {
                                            var colName = "Участник " + col.ColumnName;
                                            if (!resultDt.Columns.Contains(colName))
                                                resultDt.Columns.Add(colName);
                                            newRow[colName] = memberRow[col];
                                        }
                                        resultDt.Rows.Add(newRow);
                                    }
                                }
                            }
                        }
                    }
                }
                catch { }
                finally
                {
                    semaphore.Release();
                }
            }).ToArray();
            await Task.WhenAll(tasks);

            StatusText = $"Загружено {resultDt.Rows.Count} участников групп из файла";
            return resultDt;
        });
    }

    [RelayCommand]
    private async Task GetMaillistMemberList()
    {
        var mainWindow = Services.WindowManager.GetMainWindow();
        if (mainWindow == null) return;

        var filePath = await FileDialogHelper.SelectExcelFileAsync(mainWindow, "Выберите файл списка рассылок");
        if (string.IsNullOrEmpty(filePath)) return;

        StatusText = "Загрузка списка участников рассылок...";

        var window = new ShowMaillistWindow();
        _windowManager.OpenWindow(window);

        await window.LoadFromServiceAsync(async () =>
        {
            var excelLog = new ExcelLog(filePath);
            var dataTable = await Task.Run(() => excelLog.ReadExcelFirstSheets());

            var items = new List<string>();
            foreach (System.Data.DataRow row in dataTable.Rows)
            {
                bool hasData = false;
                for (int i = 0; i < dataTable.Columns.Count; i++)
                {
                    if (!row.IsNull(i)) { hasData = true; break; }
                }
                if (hasData)
                    items.Add(row[0].ToString()!.Trim());
            }

            dataTable.Clear();
            dataTable.Dispose();

            var sourceColName = "source";
            var resultDt = new System.Data.DataTable("Участники рассылок (Exim)");

            var dtLock = new object();
            using var semaphore = new SemaphoreSlim(8);
            var tasks = items.Select(async item =>
            {
                await semaphore.WaitAsync();
                try
                {
                    var maillistDt = await _adService.GetMailListInfoDataTableAsync(item, CancellationToken.None);
                    if (maillistDt != null && maillistDt.Rows.Count > 0)
                    {
                        foreach (System.Data.DataRow listRow in maillistDt.Select())
                        {
                            var members = await _adService.GetExchangeMembersAsync(listRow["Почта"]?.ToString() ?? "", CancellationToken.None);
                            lock (dtLock)
                            {
                                foreach (var member in members)
                                {
                                    var newRow = resultDt.NewRow();
                                    newRow[sourceColName] = item;
                                    var groupColName = "Рассылка Почта";
                                    if (!resultDt.Columns.Contains(groupColName))
                                        resultDt.Columns.Add(groupColName);
                                    newRow[groupColName] = listRow["Почта"];
                                    if (!resultDt.Columns.Contains("Участник Логин"))
                                        resultDt.Columns.Add("Участник Логин");
                                    newRow["Участник Логин"] = member.Login;
                                    if (!resultDt.Columns.Contains("Участник Почта"))
                                        resultDt.Columns.Add("Участник Почта");
                                    newRow["Участник Почта"] = member.Email;
                                    if (!resultDt.Columns.Contains("Участник Вывод. имя"))
                                        resultDt.Columns.Add("Участник Вывод. имя");
                                    newRow["Участник Вывод. имя"] = member.DisplayName;
                                    if (!resultDt.Columns.Contains("Участник Отдел"))
                                        resultDt.Columns.Add("Участник Отдел");
                                    newRow["Участник Отдел"] = member.Department;
                                    resultDt.Rows.Add(newRow);
                                }
                            }
                        }
                    }
                }
                catch { }
                finally
                {
                    semaphore.Release();
                }
            }).ToArray();
            await Task.WhenAll(tasks);

            StatusText = $"Загружено {resultDt.Rows.Count} участников рассылок из файла";
            return resultDt;
        });
    }

    private System.Data.DataTable ConvertToDataTable(List<UserInfo> list, string tableName)
    {
        var dt = new System.Data.DataTable(tableName);
        dt.TableName = tableName;

        if (list == null || list.Count == 0) return dt;

        var first = list[0];
        var props = first.GetType().GetProperties();

        foreach (var prop in props)
        {
            if (prop.Name == "ExtensionData") continue;
            var colName = GetColumnName(prop.Name);
            var colType = Nullable.GetUnderlyingType(prop.PropertyType) ?? prop.PropertyType;
            if (colType.IsClass && colType != typeof(string))
                continue;
            dt.Columns.Add(colName, colType);
        }

        foreach (var item in list)
        {
            var row = dt.NewRow();
            foreach (var prop in props)
            {
                if (prop.Name == "ExtensionData") continue;
                var colName = GetColumnName(prop.Name);
                if (dt.Columns.Contains(colName))
                {
                    var value = prop.GetValue(item);
                    if (value != null)
                        row[colName] = value;
                }
            }
            dt.Rows.Add(row);
        }

        return dt;
    }

    private System.Data.DataTable ConvertMembersToDataTable(List<UserInfo> list, string tableName, string systemName = "Exchange")
    {
        var dt = new System.Data.DataTable(tableName);
        dt.TableName = tableName;
        
        dt.Columns.Add("Присутствует в системе", typeof(string));
        dt.Columns.Add("Логин", typeof(string));
        dt.Columns.Add("ФИО", typeof(string));
        dt.Columns.Add("Почта", typeof(string));
        dt.Columns.Add("Статус УЗ", typeof(string));

        if (list == null || list.Count == 0) return dt;

        foreach (var item in list)
        {
            var row = dt.NewRow();
            row["Присутствует в системе"] = systemName;
            row["Логин"] = item.Login ?? "";
            row["ФИО"] = item.DisplayName ?? "";
            row["Почта"] = item.Email ?? "";
            row["Статус УЗ"] = item.StatusUZ ?? "";
            dt.Rows.Add(row);
        }

        return dt;
    }

    private string GetColumnName(string propertyName)
    {
        return propertyName switch
        {
            "Login" => "Логин",
            "DisplayName" => "ФИО",
            "Email" => "Почта",
            "Department" => "Департамент",
            "Company" => "Компания",
            "Title" => "Должность",
            "Phone" => "Телефон",
            "MobilePhone" => "Моб. телефон",
            "Manager" => "Руководитель",
            "DN" => "DN",
            "Description" => "Описание",
            "Owner" => "Владелец",
            "StatusUZ" => "Статус УЗ",
            "StatusSMD" => "Статус СУМД",
            "HrStatus" => "HR статус",
            "PasswordDaysLeft" => "Дней до смены пароля",
            "MailHost" => "Почтовый сервер",
            "MailBoxLocation" => "Расположение ящика",
            "Database" => "База данных",
            "MailboxUsedSpace" => "Занято",
            _ => propertyName
        };
    }

    [RelayCommand]
    private void ShowVdiInfo()
    {
        if (string.IsNullOrWhiteSpace(Login))
        {
            StatusText = "Сначала выполните поиск пользователя";
            return;
        }

        if (SearchType != "User")
        {
            StatusText = "VDI информация доступна только для пользователей";
            return;
        }

        var vdiWindow = new VdiFoldersWindow(Login);
        _windowManager.OpenWindow(vdiWindow);
    }

    [RelayCommand]
    private async Task ChangePasswordAsync()
    {
        if (!IsAdActionEnabled || string.IsNullOrWhiteSpace(DistinguishedName))
        {
            StatusText = "Выберите пользователя";
            return;
        }

        var vm = new PasswordChangeDialogViewModel
        {
            TargetDisplayName = DisplayName,
            TargetLogin = Login
        };
        var dialog = new PasswordChangeDialog { DataContext = vm };
        var owner = WindowManager.GetMainWindow();
        if (owner == null) return;

        var password = await dialog.ShowDialog<string?>(owner);
        if (string.IsNullOrEmpty(password)) return;

        IsAdOperationInProgress = true;
        AdOperationStatus = "Смена пароля...";
        StatusText = "Смена пароля...";

        try
        {
            var ct = GetCommandToken(nameof(ChangePasswordAsync));
            var result = await _adService.ChangeUserPasswordAsync(DistinguishedName, password, ct);
            if (result.Success)
            {
                StatusText = result.Message;
                await RefreshPasswordStatusInternalAsync(GetCommandToken(nameof(RefreshPasswordStatusAsync)));
            }
            else
            {
                StatusText = $"Ошибка: {result.Message}";
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            IsAdOperationInProgress = false;
            AdOperationStatus = string.Empty;
        }
    }

    [RelayCommand]
    private async Task ForcePasswordChangeAsync(string? forceStr)
    {
        if (!IsAdActionEnabled || string.IsNullOrWhiteSpace(DistinguishedName))
        {
            StatusText = "Выберите пользователя";
            return;
        }

        if (!bool.TryParse(forceStr, out var force)) return;

        IsAdOperationInProgress = true;
        AdOperationStatus = force ? "Установка флага..." : "Снятие флага...";
        StatusText = force ? "Установка требования смены пароля..." : "Снятие требования смены пароля...";

        try
        {
            var ct = GetCommandToken(nameof(ForcePasswordChangeAsync));
            var result = await _adService.ForcePasswordChangeAtNextLogonAsync(DistinguishedName, force, ct);
            if (result.Success)
            {
                StatusText = result.Message;
                PasswordRequireChange = force;
            }
            else
            {
                StatusText = $"Ошибка: {result.Message}";
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            IsAdOperationInProgress = false;
            AdOperationStatus = string.Empty;
        }
    }

    [RelayCommand]
    private async Task UnlockAccountAsync()
    {
        if (!IsUnlockEnabled || string.IsNullOrWhiteSpace(DistinguishedName))
        {
            StatusText = "УЗ не заблокирована или пользователь не выбран";
            return;
        }

        IsAdOperationInProgress = true;
        AdOperationStatus = "Разблокировка...";
        StatusText = "Разблокировка учётной записи...";

        try
        {
            var ct = GetCommandToken(nameof(UnlockAccountAsync));
            var result = await _adService.UnlockAccountAsync(DistinguishedName, ct);
            if (result.Success)
            {
                StatusText = result.Message;
                IsLockedOut = false;
            }
            else
            {
                StatusText = $"Ошибка: {result.Message}";
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            IsAdOperationInProgress = false;
            AdOperationStatus = string.Empty;
        }
    }

    [RelayCommand]
    private async Task RefreshPasswordStatusAsync()
    {
        await RefreshPasswordStatusInternalAsync(GetCommandToken(nameof(RefreshPasswordStatusAsync)));
    }

    private async Task RefreshPasswordStatusInternalAsync(CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(DistinguishedName)) return;

        try
        {
            var pwdStatus = await _adService.GetPasswordStatusAsync(DistinguishedName, ct);
            var lockStatus = await _adService.GetAccountLockStatusAsync(DistinguishedName, ct);

            PasswordLastSetText = pwdStatus.PasswordLastSet?.ToString("dd.MM.yyyy") ?? "—";
            PasswordExpiryText = pwdStatus.PasswordExpiry?.ToString("dd.MM.yyyy") ?? "—";
            PasswordNeverExpiresText = pwdStatus.PasswordNeverExpires ? "Да" : "Нет";
            PasswordRequireChange = pwdStatus.PasswordRequireChange;
            IsLockedOut = lockStatus.LockedOut;
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            StatusText = $"Ошибка обновления статуса: {ex.Message}";
        }
    }
}
