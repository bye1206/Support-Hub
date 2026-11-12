"""AD employee card for the ticket view (P-29, port of GetGroupBoxMember).

Read-only subset of the owner's GetGroupBoxMember tool (AD.cs GetUserMoreInfo,
2026-11 sources): identity, org structure, phones, AD groups, password dates
and the account photo. Attribute list mirrors the proven utility:

- identity: sAMAccountName, displayName, sn/givenName, mail, thumbnailPhoto;
- org: title, department, company, manager (resolved to a display name);
- phones: telephoneNumber, mobilepers (corp extension attribute);
- groups: memberOf is STRIPPED by the AD proxy on self-reads (D-047 quirk),
  so the group list is read FROM THE GROUP side: (&(objectClass=group)
  (member=<userDN>)) - the same approach as the auth module;
- password: pwdLastSet + msDS-UserPasswordExpiryTimeComputed (Windows
  FILETIME, 100 ns since 1601-01-01 UTC);
- status: userAccountControl (bit 0x2 = disabled).

Every lookup needs a service bind (LDAP_SERVICE_USER_DN/PASSWORD): the auth
path binds under the operator's own credentials and cannot read other users.
ldap3 is synchronous - all calls run in a worker thread.
"""

import logging
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)

try:
    import ldap3

    HAS_LDAP3 = True
except ImportError:  # pragma: no cover - ldap3 is a hard dependency
    HAS_LDAP3 = False

_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)

# 0x2 = ACCOUNTDISABLE; lockout is not in userAccountControl anymore
# (msDS-User-Account-Control-Computed bit 0x400000, requested separately).
_UAC_DISABLED = 0x2
_UAC_LOCKED = 0x400000

_USER_ATTRIBUTES = [
    "sAMAccountName",
    "displayName",
    "sn",
    "givenName",
    "mail",
    "title",
    "department",
    "company",
    "telephoneNumber",
    "mobilepers",
    "manager",
    "distinguishedName",
    "userAccountControl",
    "msDS-User-Account-Control-Computed",
    "pwdLastSet",
    "msDS-UserPasswordExpiryTimeComputed",
    "thumbnailPhoto",
]


class AdUnavailableError(Exception):
    """AD directory reads are not configured or AD is unreachable."""


def filetime_to_datetime(raw: Any) -> datetime | None:
    """Windows FILETIME (100 ns since 1601-01-01) -> UTC datetime."""
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return None
    if value <= 0:  # 0 / 9223372036854775807 = "never set" / "never expires"
        return None
    return _FILETIME_EPOCH + timedelta(microseconds=value / 10)


def _cn_of(dn: str) -> str:
    """Common name of a DN: 'CN=Support,OU=...' -> 'Support'."""
    for part in dn.split(","):
        part = part.strip()
        if part.upper().startswith("CN="):
            return part[3:]
    return dn


def demo_card(login: str) -> dict[str, Any]:
    """Synthetic employee card for the UI preview (AD_DEMO=true, dev only).

    Mirrors the real card shape 1:1 so the operator workspace can be demoed
    without a service account; the photo is a tiny generated JPEG-free blob
    (1x1 PNG) - just enough to exercise the <img> path."""
    return {
        "login": login,
        "full_name": "Иван Петров",
        "email": f"{login}@corp.tander.ru",
        "title": "Ведущий специалист",
        "department": "Департамент ИТ",
        "company": "Магнит",
        "phone": "8-800-555-35-35",
        "mobile": "+7-900-123-45-67",
        "manager": "Мария Иванова",
        "disabled": False,
        "locked": False,
        "password_changed_at": datetime.now(UTC) - timedelta(days=27),
        "password_expires_at": datetime.now(UTC) + timedelta(days=63),
        "groups": [
            "1C-Users",
            "VPN-Access",
            "Support-Team",
            "Confluence-Users",
            "Jira-Users",
            "Mail-All",
            "SAP-Basic",
        ],
        "has_photo": True,
        "_photo": bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d4944415478da63fccf00f60300030301003b7bd0560000000049454e44ae426082"
        ),
    }


class AdDirectory:
    """Read-only AD directory for the employee card (P-29)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return (
            HAS_LDAP3
            and bool(self._settings.ldap_host)
            and bool(self._settings.ldap_service_user_dn)
            and bool(self._settings.ldap_service_password)
        )

    async def get_user(self, login: str) -> dict[str, Any] | None:
        """Employee card by login (sAMAccountName or e-mail). Worker thread."""
        import anyio.to_thread

        return await anyio.to_thread.run_sync(self.get_user_sync, login)

    def get_user_sync(self, login: str) -> dict[str, Any] | None:
        """Blocking lookup; returns None when the user is not in AD."""
        if not self.configured:
            raise AdUnavailableError("AD directory is not configured")
        conn = self._connect()
        try:
            escaped = ldap3.utils.conv.escape_filter_chars(login)
            if "@" in login:
                filter_expr = f"(mail={escaped})"
            else:
                filter_expr = f"(sAMAccountName={escaped})"
            conn.search(
                self._settings.ldap_base_dn,
                f"(&(objectClass=user)(objectCategory=user){filter_expr})",
                attributes=_USER_ATTRIBUTES,
                search_scope="SUBTREE",
                size_limit=1,
            )
            if not conn.entries:
                return None
            entry = conn.entries[0]
            user_dn = str(entry.entry_dn)

            groups = self._read_groups(conn, user_dn)
            manager = self._read_manager(conn, entry)
            photo = bytes(entry.thumbnailPhoto[0]) if "thumbnailPhoto" in entry else b""

            uac = int(str(entry.userAccountControl)) if "userAccountControl" in entry else 0
            computed = int(
                str(entry["msDS-User-Account-Control-Computed"])
            ) if "msDS-User-Account-Control-Computed" in entry else 0
            return {
                "login": str(entry.sAMAccountName),
                "full_name": str(entry.displayName) if "displayName" in entry else "",
                "email": str(entry.mail) if "mail" in entry else "",
                "title": str(entry.title) if "title" in entry else "",
                "department": str(entry.department) if "department" in entry else "",
                "company": str(entry.company) if "company" in entry else "",
                "phone": str(entry.telephoneNumber) if "telephoneNumber" in entry else "",
                "mobile": str(entry.mobilepers) if "mobilepers" in entry else "",
                "manager": manager,
                "disabled": bool(uac & _UAC_DISABLED),
                "locked": bool(computed & _UAC_LOCKED),
                "password_changed_at": filetime_to_datetime(
                    entry.pwdLastSet[0] if "pwdLastSet" in entry else None
                ),
                "password_expires_at": filetime_to_datetime(
                    entry["msDS-UserPasswordExpiryTimeComputed"][0]
                ) if "msDS-UserPasswordExpiryTimeComputed" in entry else None,
                "groups": groups,
                "has_photo": bool(photo),
                # The photo itself is cached separately (bytes are not JSON).
                "_photo": photo,
            }
        except AdUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - ldap3/network layer
            logger.warning("AD directory read failed: %s", exc)
            raise AdUnavailableError(f"AD read failed: {exc}") from exc
        finally:
            try:
                conn.unbind()
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass

    def _connect(self) -> Any:
        settings = self._settings
        if settings.ldap_tls_verify and settings.ldap_ca_cert_file:
            tls = ldap3.Tls(
                validate=ssl.CERT_REQUIRED, ca_certs_file=settings.ldap_ca_cert_file
            )
        else:
            # Same residual risk as the auth path: corp proxy chain lacks the
            # intermediate until the corp root CA is provisioned.
            tls = ldap3.Tls(validate=ssl.CERT_NONE)
        server = ldap3.Server(
            settings.ldap_host,
            port=settings.ldap_port,
            use_ssl=True,
            tls=tls,
            connect_timeout=settings.ldap_timeout_seconds,
        )
        conn = ldap3.Connection(
            server,
            user=settings.ldap_service_user_dn,
            password=settings.ldap_service_password,
            auto_bind=False,
            receive_timeout=settings.ldap_timeout_seconds,
        )
        if not conn.bind():
            raise AdUnavailableError("AD service bind failed")
        return conn

    def _read_groups(self, conn: Any, user_dn: str) -> list[str]:
        """Group names FROM THE GROUP side (memberOf is stripped by the proxy)."""
        escaped_dn = user_dn.replace("\\", "\\\\")
        conn.search(
            self._settings.ldap_base_dn,
            f"(&(objectClass=group)(member={escaped_dn}))",
            attributes=["cn"],
            search_scope="SUBTREE",
        )
        names = [str(entry.cn) for entry in conn.entries if "cn" in entry]
        return sorted(names)

    def _read_manager(self, conn: Any, entry: Any) -> str:
        manager_dn = str(entry.manager) if "manager" in entry else ""
        if not manager_dn:
            return ""
        # One extra BASE read of the manager's display name (GGBM does the same).
        try:
            conn.search(
                manager_dn,
                "(objectClass=*)",
                attributes=["displayName"],
                search_scope="BASE",
            )
            if conn.entries and "displayName" in conn.entries[0]:
                return str(conn.entries[0].displayName)
        except Exception:  # noqa: BLE001 - manager display name is cosmetic
            pass
        return _cn_of(manager_dn)
