using System.Data;
using GetGroupBoxMember.Models;

namespace GetGroupBoxMember.Services;

public interface IADService
{
    Task<List<UserInfo>> FastSearchAsync(string query, string entityType, CancellationToken cancellationToken = default, Action<string>? onProgress = null);

    Task<List<UserInfo>> GetUserInfoAsync(string query, CancellationToken cancellationToken = default);

    Task<UserMoreInfo?> GetUserMoreInfoAsync(string login, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable?> GetUserMoreInfoTableAsync(string login, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetGroupInfoAsync(string query, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetGroupMembersAsync(string distinguishedName, CancellationToken cancellationToken = default);

    Task<DataTable> GetGroupMembersDataTableAsync(string distinguishedName, CancellationToken cancellationToken = default);

    Task<DataTable> GetDynamicGroupMembersDataTableAsync(string login, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetMailListInfoAsync(string query, CancellationToken cancellationToken = default);

    Task<DataTable?> GetMailListInfoDataTableAsync(string query, CancellationToken cancellationToken = default);

    Task<DataTable?> GetGroupInfoDataTableAsync(string query, string type, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetDynamicGroupInfoAsync(string query, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetComputerInfoAsync(string query, CancellationToken cancellationToken = default);

    Task<DataTable?> GetComputerInfoForInfoWindowAsync(string compName, CancellationToken cancellationToken = default, Action<string>? progress = null);

    Task<List<UserInfo>> GetGroupBoxAccessAsync(string login, string distinguishedName, CancellationToken cancellationToken = default);

    Task<DataTable> GetGroupBoxAccessDataTableAsync(string login, string distinguishedName, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetMailboxAccessAsync(string login, string distinguishedName, CancellationToken cancellationToken = default);

    Task<DataTable> GetMailboxAccessDataTableAsync(string login, string distinguishedName, CancellationToken cancellationToken = default);

    Task<DataTable> GetVladetelIsListAsync(string login, CancellationToken cancellationToken = default);

    Task<string?> GetQuotaDataAsync(string email, CancellationToken cancellationToken = default);

    Task<string?> GetRetentionPolicyAsync(string email, CancellationToken cancellationToken = default);

    Task<string?> GetManagerInfoAsync(string managerDN, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetEximMembersAsync(string mail, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetExchangeMembersAsync(string mail, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetMaillistExchangeMembersAsync(string mail, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> GetMembersByDnListAsync(string memberDns, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable> GetUserByDnAsync(string distinguishedName, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable?> GetHierarchyAsync(string login, CancellationToken cancellationToken = default);

    Task<List<UserInfo>> FindPCByOwnerAsync(string ownerLogin, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable> GetRepadminInfoAttributeMetaDataAsync(string login, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable> GetRepadminInfoValueMetaDataAsync(string login, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable> GetUsersGroupComparisonAsync(string login1, string login2, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable> GetGroupMoreInfoAsync(string login, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable> GetMaillistMoreInfoAsync(string login, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable> GetDynamicGroupMoreInfoAsync(string login, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable?> GetDynamicDistributionGroupInfoDataTableAsync(string query, string type, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable?> GetComputerInfoDataTableAsync(string query, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable> GetVladetelIsListByFIOAsync(System.Data.DataTable fioDT, CancellationToken cancellationToken = default);

    Task<System.Data.DataTable?> GetUserInfoForInfoWindowAsync(string login, CancellationToken cancellationToken = default, Action<string>? progress = null);

    Task<(string lastLogonTime, string domainController)> GetUserLastLogonAsync(string login, CancellationToken cancellationToken = default);

    Task<DataTable> SearchByAttributeAsync(string attributeName, string attributeValue, CancellationToken cancellationToken = default);

    Task<List<string>> GetSchemaAttributesAsync(CancellationToken cancellationToken = default);

    Task<ADOperationResult> ChangeUserPasswordAsync(string userDN, string newPassword, CancellationToken cancellationToken = default);

    Task<ADOperationResult> ForcePasswordChangeAtNextLogonAsync(string userDN, bool force, CancellationToken cancellationToken = default);

    Task<ADOperationResult> UnlockAccountAsync(string userDN, CancellationToken cancellationToken = default);

    Task<PasswordStatusInfo> GetPasswordStatusAsync(string userDN, CancellationToken cancellationToken = default);

    Task<AccountLockStatusInfo> GetAccountLockStatusAsync(string userDN, CancellationToken cancellationToken = default);
}
