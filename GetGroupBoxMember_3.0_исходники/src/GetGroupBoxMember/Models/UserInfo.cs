namespace GetGroupBoxMember.Models;

public class UserInfo
{
    public string Login { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
    public string FIO { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Department { get; set; } = string.Empty;
    public string Company { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Phone { get; set; } = string.Empty;
    public string MobilePhone { get; set; } = string.Empty;
    public string Office { get; set; } = string.Empty;
    public string Manager { get; set; } = string.Empty;
    public string DN { get; set; } = string.Empty;
    public string MailHost { get; set; } = string.Empty;
    public string MailBoxLocation { get; set; } = string.Empty;
    public string Owner { get; set; } = string.Empty;
    public string MigrateStatus { get; set; } = string.Empty;
    public string QuotaMailBox { get; set; } = string.Empty;
    public string Database { get; set; } = string.Empty;
    public string MailboxUsedSpace { get; set; } = string.Empty;
    public string StatusSMD { get; set; } = string.Empty;
    public string StatusUZ { get; set; } = string.Empty;
    public string HRStatus { get; set; } = string.Empty;
    public string PasswordDaysLeft { get; set; } = string.Empty;
    public string PasswordBlocked { get; set; } = string.Empty;
    public bool IsDisabled { get; set; }
    public bool IsSUMD { get; set; }
    public bool IsLockedOut { get; set; }
    public bool PasswordRequireChange { get; set; }
    public string AccountStatus => IsDisabled ? "Disabled" : "Active";
    public byte[]? Photo { get; set; }
    public object? ThumbnailPhoto { get; set; }
    public string EximMembers { get; set; } = string.Empty;
    public string ExchangeMembers { get; set; } = string.Empty;
    public bool IsSharedMailbox => !string.IsNullOrWhiteSpace(Owner);

    public string DisplayNameOrLogin => string.IsNullOrWhiteSpace(DisplayName) ? Login : DisplayName;

    public override bool Equals(object? obj)
    {
        if (obj is UserInfo other) return Login == other.Login;
        return false;
    }

    public override int GetHashCode() => Login.GetHashCode();
}

public class UserMoreInfo
{
    public string Login { get; set; } = string.Empty;
    public string LastName { get; set; } = string.Empty;
    public string FirstName { get; set; } = string.Empty;
    public string MiddleName { get; set; } = string.Empty;
    public string FullName { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Phone { get; set; } = string.Empty;
    public string MobilePhone { get; set; } = string.Empty;
    public string Owner { get; set; } = string.Empty;
    public string Manager { get; set; } = string.Empty;
    public string DN { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
    public string MailServer { get; set; } = string.Empty;
    public string MailStorage { get; set; } = string.Empty;
    public string MailBoxLocation { get; set; } = string.Empty;
    public string JobTitle { get; set; } = string.Empty;
    public string Department { get; set; } = string.Empty;
    public string Company { get; set; } = string.Empty;
    public string Guid1C { get; set; } = string.Empty;
    public string GuidMD { get; set; } = string.Empty;
    public string SID { get; set; } = string.Empty;
    public string Directorate { get; set; } = string.Empty;
    public string SubDepartment { get; set; } = string.Empty;
    public string ManagementFunction { get; set; } = string.Empty;
    public string DirectionService { get; set; } = string.Empty;
    public string Section { get; set; } = string.Empty;
    public string Sector { get; set; } = string.Empty;
    public string Position { get; set; } = string.Empty;
    public string EximCanReceiveExternal { get; set; } = string.Empty;
    public string EximCanSendExternal { get; set; } = string.Empty;
    public string EximMailboxStatus { get; set; } = string.Empty;
    public string ExchangeMigrationStatus { get; set; } = string.Empty;
    public string ExchangeMailboxStatus { get; set; } = string.Empty;
    public string Database { get; set; } = string.Empty;
    public string QuotaBaseSettings { get; set; } = string.Empty;
    public string QuotaWarning { get; set; } = string.Empty;
    public string QuotaSendProhibit { get; set; } = string.Empty;
    public string QuotaSendReceiveProhibit { get; set; } = string.Empty;
    public string QuotaChangeRequest { get; set; } = string.Empty;
    public string Notes { get; set; } = string.Empty;
    public string LDAPPath { get; set; } = string.Empty;
    public string MemberOf { get; set; } = string.Empty;
    public string AccountExpires { get; set; } = string.Empty;
    public string AccountStatus { get; set; } = string.Empty;
    public string Created { get; set; } = string.Empty;
    public string Modified { get; set; } = string.Empty;
    public string PasswordRequireChange { get; set; } = string.Empty;
    public string PasswordChanged { get; set; } = string.Empty;
    public string PasswordExpires { get; set; } = string.Empty;
    public string LastLogon { get; set; } = string.Empty;
    public byte[]? Photo { get; set; }
}

public class GroupMoreInfo
{
    public string Login { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Owner { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
    public string ExchangeReceiveExternal { get; set; } = string.Empty;
    public string ExchangeWhiteList { get; set; } = string.Empty;
    public string Moderation { get; set; } = string.Empty;
    public string Moderator { get; set; } = string.Empty;
    public string VipSenderNoModeration { get; set; } = string.Empty;
    public string LDAPPath { get; set; } = string.Empty;
    public string GroupStatus { get; set; } = string.Empty;
    public string Created { get; set; } = string.Empty;
    public string Modified { get; set; } = string.Empty;
}

public class MaillistMoreInfo
{
    public string Login { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Owner { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
    public string ExchangeReceiveExternal { get; set; } = string.Empty;
    public string ExchangeWhiteList { get; set; } = string.Empty;
    public string Moderation { get; set; } = string.Empty;
    public string Moderator { get; set; } = string.Empty;
    public string VipSenderNoModeration { get; set; } = string.Empty;
    public string LDAPPath { get; set; } = string.Empty;
    public string GroupStatus { get; set; } = string.Empty;
    public string Created { get; set; } = string.Empty;
    public string Modified { get; set; } = string.Empty;
}

public class SearchResultItem
{
    public string Login { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Department { get; set; } = string.Empty;
    public string Guid1C { get; set; } = string.Empty;
    public string GuidMD { get; set; } = string.Empty;
    public string MobilePhone { get; set; } = string.Empty;
    public string Owner { get; set; } = string.Empty;
    public string DistinguishedName { get; set; } = string.Empty;
    public bool IsPlaceholder { get; set; }
}

public class AttributesItem
{
    public string Attribute { get; set; } = string.Empty;
    public string Value { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
}
