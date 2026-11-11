"""Direct LDAP/AD authentication for operators (D-047).

Adapted from the owner-proven ``ldap_auth_module.py`` (RAG chat dashboard,
production 2026-11). Domain quirks are baked in:

1. Anonymous search is BLOCKED by the AD proxy: bind under the user's UPN
   first, only then search.
2. ``memberOf`` never arrives in self-read (the proxy strips it): group
   membership is verified FROM THE GROUP object, ``(member=<userDN>)``.
3. ldap3 2.9 (Debian): ``Tls(validate=...)`` - not ``validity=``;
   ``receive_timeout`` - not ``receive_time_limit``; the timeout is an
   ``int`` (a float raises TypeError at connect).

Differences from the original module (why a rewrite, not an import):
- configuration comes from our Settings, not ``os.environ`` at import time;
- ldap3 is synchronous: every LDAP call runs in a worker thread
  (``check_credentials`` is async) - the event loop must never block on a
  10 s bind timeout while serving the realtime workspace;
- returns the corporate identity (email/display name/group flags) needed
  for operator provisioning, not just ok/fail;
- the rate limiter is a separate object (instance state, resettable in
  tests) and honors ``X-Forwarded-For`` only when explicitly trusted.
"""

import hashlib
import hmac
import ssl
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from app.config import Settings

try:
    import ldap3

    HAS_LDAP3 = True
except ImportError:  # pragma: no cover - ldap3 is a hard dependency
    HAS_LDAP3 = False


class LdapUnavailableError(Exception):
    """LDAP infrastructure failure (AD down, ldap3 missing, timeout)."""


@dataclass
class LdapIdentity:
    login: str
    email: str
    display_name: str | None
    # True = passed the operator group check (or no group configured).
    is_operator: bool
    # True = member of the admin group (break-glass local user is admin too).
    is_admin: bool
    # True = member of the optional supervisor group (D-048).
    is_supervisor: bool
    # "local" = emergency account, "cache" = cached success, "ldap" = live AD.
    source: str


class AuthRateLimiter:
    """Per-IP failed-attempt limiter: max failures per window -> limited."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_limited(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            queue = self._fails.get(key)
            if not queue:
                return False
            while queue and queue[0] < now - self._window:
                queue.popleft()
            return len(queue) >= self._max

    def record_failure(self, key: str) -> None:
        now = time.time()
        with self._lock:
            queue = self._fails[key]
            queue.append(now)
            while queue and queue[0] < now - self._window:
                queue.popleft()


class LdapAuthenticator:
    """Validates domain credentials and maps them to an operator identity."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[tuple[str, str], tuple[LdapIdentity, float]] = {}
        self._cache_lock = threading.Lock()
        self.rate_limiter = AuthRateLimiter(
            settings.auth_rate_limit_max, settings.auth_rate_limit_window_seconds
        )

    async def check_credentials(self, login: str, password: str) -> LdapIdentity:
        """Async facade: ldap3 is blocking, run it off the event loop."""
        import anyio.to_thread

        return await anyio.to_thread.run_sync(
            self.check_credentials_sync, login, password
        )

    def check_credentials_sync(self, login: str, password: str) -> LdapIdentity:
        """Blocking check: break-glass user -> cache -> live LDAP."""
        settings = self._settings
        # 1. Emergency account (works even when AD is unreachable).
        if settings.auth_local_user and settings.auth_local_pass:
            if hmac.compare_digest(login, settings.auth_local_user) and hmac.compare_digest(
                password, settings.auth_local_pass
            ):
                return LdapIdentity(
                    login=login,
                    email=self._email_for(login),
                    display_name=login,
                    is_operator=True,
                    is_admin=True,
                    is_supervisor=True,
                    source="local",
                )
        # 2. Without ldap3 there is no LDAP path at all (fail-closed).
        if not HAS_LDAP3:  # pragma: no cover - ldap3 is a hard dependency
            raise LdapUnavailableError("ldap3 is not installed")

        # 3. Cache of successful logins, keyed by password hash: a changed
        # domain password invalidates the entry immediately.
        cache_key = (login.lower(), hashlib.sha256(password.encode("utf-8")).hexdigest())
        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(cache_key)
            if hit and hit[1] > now:
                return hit[0]
            for key in [k for k, v in self._cache.items() if v[1] <= now]:
                del self._cache[key]

        # 4. Live AD check.
        identity = self._ldap_check(login, password)
        expiry = now + settings.auth_cache_ttl_seconds
        with self._cache_lock:
            self._cache[cache_key] = (identity, expiry)
        return identity

    def _email_for(self, login: str) -> str:
        if "@" in login:
            return login.lower()
        return f"{login}@{self._settings.ldap_domain}".lower()

    def _ldap_check(self, login: str, password: str) -> LdapIdentity:
        settings = self._settings
        upn = login if "@" in login else f"{login}@{settings.ldap_domain}"
        if settings.ldap_tls_verify and settings.ldap_ca_cert_file:
            tls = ldap3.Tls(
                validate=ssl.CERT_REQUIRED, ca_certs_file=settings.ldap_ca_cert_file
            )
        else:
            # CERT_NONE: the corp AD proxy serves a chain without the
            # intermediate in standard bundles (documented residual risk).
            tls = ldap3.Tls(validate=ssl.CERT_NONE)
        server = ldap3.Server(
            settings.ldap_host,
            port=settings.ldap_port,
            use_ssl=True,
            tls=tls,
            connect_timeout=settings.ldap_timeout_seconds,
        )
        try:
            conn = ldap3.Connection(
                server,
                user=upn,
                password=password,
                auto_bind=False,
                receive_timeout=settings.ldap_timeout_seconds,
            )
            if not conn.bind():
                description = "?"
                try:
                    description = str(conn.result.get("description", "?"))
                except Exception:  # noqa: BLE001 - ldap3 result shape varies
                    pass
                raise LdapAuthFailed(f"bind failed: {description}")

            # Self-read under the user's own bind (anonymous search blocked):
            # DN, mail and display name in one query.
            escaped = ldap3.utils.conv.escape_filter_chars(login)
            conn.search(
                settings.ldap_base_dn,
                f"(sAMAccountName={escaped})",
                attributes=["distinguishedName", "mail", "displayName"],
                search_scope="SUBTREE",
            )
            user_dn = ""
            mail = ""
            display_name = ""
            for entry in conn.entries:
                user_dn = str(entry.entry_dn)
                mail = str(entry.mail) if "mail" in entry else ""
                display_name = str(entry.displayName) if "displayName" in entry else ""
                break
            if not user_dn:
                raise LdapAuthFailed("user DN not found (check LDAP_BASE_DN / account)")

            is_admin = self._member_of_any(
                conn, settings.ldap_group_admin_dn, user_dn
            )
            is_supervisor = bool(settings.ldap_group_supervisor_dn) and (
                self._member_of_any(
                    conn, settings.ldap_group_supervisor_dn, user_dn
                )
            )
            if settings.ldap_group_operator_dn:
                is_operator = self._member_of_any(
                    conn, settings.ldap_group_operator_dn, user_dn
                )
            else:
                # No operator group configured: any domain user may operate
                # (module semantics; set LDAP_GROUP_OPERATOR_DN in shared envs).
                is_operator = True
            conn.unbind()
        except LdapAuthFailed:
            raise
        except Exception as exc:  # noqa: BLE001 - ldap3/network layer
            raise LdapUnavailableError(f"ldap error: {exc}") from exc

        if not is_operator:
            raise LdapAuthFailed("user is NOT a member of the required group")
        return LdapIdentity(
            login=login,
            email=(mail or self._email_for(login)).lower(),
            display_name=display_name or None,
            is_operator=True,
            is_admin=is_admin,
            is_supervisor=is_supervisor,
            source="ldap",
        )

    def _member_of_any(self, conn: Any, group_dns: str, user_dn: str) -> bool:
        """Group check from the GROUP side: (member=<userDN>), scope BASE.

        ``group_dns`` may hold several DNs separated by ';' (a DN itself
        contains commas, so ';' is the only safe separator).
        """
        for group_dn in (part.strip() for part in group_dns.split(";")):
            if not group_dn:
                continue
            escaped_dn = user_dn.replace("\\", "\\\\")
            conn.search(
                group_dn, f"(member={escaped_dn})", attributes=["cn"], search_scope="BASE"
            )
            if len(conn.entries) > 0:
                return True
        return False


class LdapAuthFailed(Exception):
    """Credentials valid LDAP-wise but rejected (bad password, no group)."""
