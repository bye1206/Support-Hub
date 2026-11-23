"""LDAP group membership probe (owner, 2026-11-23).

Run on the VM with the service env loaded:

    cd ~/Support_hub/backend
    set -a && . ../.env && set +a
    ../venv/bin/python scripts/probe_ldap_group.py <доменной_логин>

Prints: the configured group DNs, the groups' real DNs found by CN,
their direct members (or the ranged-reading note), the user's DN and
both membership directions.
"""

import ssl
import sys

import ldap3
import ldap3.utils.conv

from app.config import get_settings


def _connect(settings, user_dn, password):
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
        user=user_dn,
        password=password,
        auto_bind=False,
        receive_timeout=settings.ldap_timeout_seconds,
    )
    if not conn.bind():
        print(f"BIND FAILED as {user_dn}: {conn.result}")
        sys.exit(1)
    return conn


def main() -> None:
    login = sys.argv[1] if len(sys.argv) > 1 else ""
    settings = get_settings()
    if not settings.ldap_service_user_dn:
        print("LDAP_SERVICE_USER_DN is not configured")
        sys.exit(1)
    print(f"host={settings.ldap_host}:{settings.ldap_port} base={settings.ldap_base_dn}")
    print(f"operator_dn_env={settings.ldap_group_operator_dn!r}")
    print(f"admin_dn_env={settings.ldap_group_admin_dn!r}")

    conn = _connect(settings, settings.ldap_service_user_dn, settings.ldap_service_password)
    try:
        # 1. The user's real DN.
        user_dn = ""
        if login:
            escaped = ldap3.utils.conv.escape_filter_chars(login)
            conn.search(
                settings.ldap_base_dn,
                f"(sAMAccountName={escaped})",
                attributes=["distinguishedName", "memberOf"],
                search_scope="SUBTREE",
            )
            for entry in conn.entries:
                user_dn = str(entry.entry_dn)
                print(f"user_dn={user_dn}")
                member_of = (
                    list(entry["memberOf"].values)
                    if "memberOf" in entry
                    else "(absent/stripped)"
                )
                print(f"user_memberOf={member_of}")
                break
            if not user_dn:
                print(f"USER NOT FOUND by sAMAccountName={login}")
        # 2. The groups' real DNs and members.
        for label, name in (
            ("operator", "support_hub_operator"),
            ("admin", "support_hub_admin"),
        ):
            escaped = ldap3.utils.conv.escape_filter_chars(name)
            conn.search(
                settings.ldap_base_dn,
                f"(&(objectClass=group)(cn={escaped}))",
                attributes=["distinguishedName", "member"],
                search_scope="SUBTREE",
            )
            if not conn.entries:
                print(f"[{label}] group cn={name}: NOT FOUND under the base DN")
                continue
            for entry in conn.entries:
                dn = str(entry.entry_dn)
                members = list(entry["member"].values) if "member" in entry else []
                print(f"[{label}] real_dn={dn}")
                print(f"[{label}] direct_members={len(members)}")
                for member in members[:10]:
                    print(f"[{label}]   member: {member}")
                if len(members) >= 1500:
                    print(f"[{label}]   (>=1500 members: ranged reading, list truncated)")
                if user_dn and user_dn in members:
                    print(f"[{label}] MEMBERSHIP: YES (direct)")
                elif user_dn:
                    print(f"[{label}] MEMBERSHIP: NO (not among direct members)")
    finally:
        conn.unbind()


if __name__ == "__main__":
    main()
