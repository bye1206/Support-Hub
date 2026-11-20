# -*- coding: utf-8 -*-
"""
LDAP/AD авторизация для FastAPI-сервисов: HTTP Basic + проверка доменной группы.

Самодостаточный модуль. Подключение — 2 строки:

    from ldap_auth_module import install_auth
    install_auth(app, protected_prefixes=("/admin", "/api/admin"), realm="MyApp")

Зависимости: ldap3 (pip install ldap3>=2.9), fastapi (для install_auth).
Проверено в проде (дашборд RAG-чата, ноябрь 2026). Особенности нашей AD,
учтённые в коде (подробности в LDAP_AUTH_ТЕХДОК.md):

  1. Анонимный поиск в AD ЗАБЛОКИРОВАН — сначала bind под учёткой пользователя
     (по UPN user@домен), потом self-read (поиск своего DN).
  2. Атрибут memberOf в self-read НЕ приходит (прокси AD его вырезает) —
     принадлежность группе проверяется поиском ПО ГРУППЕ: (member=<userDN>).
  3. ldap3 2.9 (Debian): Tls(validate=ssl.CERT_NONE) — НЕ validity=;
     receive_timeout — НЕ receive_time_limit; таймаут передаётся КАК int
     (float даёт TypeError при коннекте).

Конфигурация — только переменные окружения (см. LDAP_AUTH_ТЕХДОК.md).
Безопасность: пароли не логируются; кэш ключуется (логин, sha256(пароль));
успешный вход кэшируется; лимит неудачных попыток с одного IP;
fail-closed: без ldap3/при недоступности AD работает только локальный юзер.
"""

import os
import ssl
import time
import base64
import hashlib
import hmac
import threading
from collections import defaultdict, deque

try:
    import ldap3
    HAS_LDAP3 = True
except ImportError:
    HAS_LDAP3 = False

# ---------------------------------------------------------------------------
# Конфигурация (env)
# ---------------------------------------------------------------------------

LDAP_HOST = os.environ.get("LDAP_HOST", "adldap.corp.tander.ru")
LDAP_PORT = int(os.environ.get("LDAP_PORT", "636"))
LDAP_DOMAIN = os.environ.get("LDAP_DOMAIN", "corp.tander.ru")
LDAP_BASE_DN = os.environ.get("LDAP_BASE_DN", "DC=corp,DC=tander,DC=ru")
# Пусто = пропустить проверку группы (любой доменный юзер проходит)
LDAP_GROUP_DN = os.environ.get("LDAP_GROUP_DN", "")
LDAP_TIMEOUT = int(os.environ.get("LDAP_TIMEOUT", "10"))  # int, НЕ float!

AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes")
# Аварийный локальный вход (работает даже если AD недоступен)
AUTH_LOCAL_USER = os.environ.get("AUTH_LOCAL_USER", "")
AUTH_LOCAL_PASS = os.environ.get("AUTH_LOCAL_PASS", "")

AUTH_CACHE_TTL = int(os.environ.get("AUTH_CACHE_TTL", "900"))  # сек, 15 мин
AUTH_RATELIMIT_MAX = int(os.environ.get("AUTH_RATELIMIT_MAX", "20"))
AUTH_RATELIMIT_WINDOW = int(os.environ.get("AUTH_RATELIMIT_WINDOW", "300"))  # сек

# ---------------------------------------------------------------------------
# Кэш успешных входов: key = (логин, sha256(пароль)), value = expiry ts
# ---------------------------------------------------------------------------

_cache = {}
_cache_lock = threading.Lock()

# Лимитер неудачных попыток по IP
_fails = defaultdict(deque)
_fails_lock = threading.Lock()


def _cache_purge(now: float):
    for k in [k for k, v in _cache.items() if v <= now]:
        _cache.pop(k, None)


def check_user(username: str, password: str):
    """Проверить учётные данные. Возвращает (ok: bool, detail: str)."""
    # 1. Локальный аварийный юзер
    if AUTH_LOCAL_USER and AUTH_LOCAL_PASS:
        if hmac.compare_digest(username, AUTH_LOCAL_USER) and \
           hmac.compare_digest(password, AUTH_LOCAL_PASS):
            return True, "local user"

    # 2. Без ldap3 — fail-closed (только локальный юзер выше)
    if not HAS_LDAP3:
        return False, "ldap3 is not installed"

    # 3. Кэш успешных входов
    key = (username.lower(), hashlib.sha256(password.encode("utf-8")).hexdigest())
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit > now:
            return True, "cached"
        _cache_purge(now)

    # 4. Живая проверка в AD
    ok, detail = _ldap_check(username, password)
    if ok:
        with _cache_lock:
            _cache[key] = time.time() + AUTH_CACHE_TTL
    return ok, detail


def _ldap_check(username: str, password: str):
    """Bind по UPN → self-read DN → проверка группы через (member=userDN)."""
    upn = username if "@" in username else f"{username}@{LDAP_DOMAIN}"
    tls = ldap3.Tls(validate=ssl.CERT_NONE)  # НЕ validity= (не работает в ldap3 2.9)
    server = ldap3.Server(
        LDAP_HOST, port=LDAP_PORT, use_ssl=True, tls=tls,
        connect_timeout=LDAP_TIMEOUT,
    )
    try:
        conn = ldap3.Connection(
            server, user=upn, password=password,
            auto_bind=False, receive_timeout=LDAP_TIMEOUT,  # int
        )
        if not conn.bind():
            desc = "?"
            try:
                desc = conn.result.get("description", "?")
            except Exception:
                pass
            return False, f"bind failed: {desc}"

        # Self-read: ищем DN пользователя (анонимный поиск заблокирован,
        # поэтому bind уже выполнен под самим пользователем)
        esc_user = ldap3.utils.conv.escape_filter_chars(username)
        conn.search(
            LDAP_BASE_DN, f"(sAMAccountName={esc_user})",
            attributes=["distinguishedName"], search_scope="SUBTREE",
        )
        user_dn = None
        for entry in conn.entries:
            user_dn = str(entry.entry_dn)
            break
        if not user_dn:
            conn.unbind()
            return False, "user DN not found (check LDAP_BASE_DN / account)"

        # Группа: поиск по объекту группы, (member=<DN пользователя>)
        if not LDAP_GROUP_DN:
            conn.unbind()
            return True, f"ok (group check disabled), dn={user_dn}"

        esc_dn = user_dn.replace("\\", "\\\\")
        conn.search(
            LDAP_GROUP_DN, f"(member={esc_dn})",
            attributes=["cn"], search_scope="BASE",
        )
        in_group = len(conn.entries) > 0
        conn.unbind()
        if in_group:
            return True, f"ok (group member), dn={user_dn}"
        return False, "user is NOT a member of the required group"
    except Exception as e:
        return False, f"ldap error: {e}"


# ---------------------------------------------------------------------------
# Rate limit: AUTH_RATELIMIT_MAX неудач с одного IP за AUTH_RATELIMIT_WINDOW сек
# ---------------------------------------------------------------------------

def _record_fail(ip: str):
    now = time.time()
    with _fails_lock:
        q = _fails[ip]
        q.append(now)
        while q and q[0] < now - AUTH_RATELIMIT_WINDOW:
            q.popleft()


def _ratelimited(ip: str) -> bool:
    now = time.time()
    with _fails_lock:
        q = _fails.get(ip)
        if not q:
            return False
        while q and q[0] < now - AUTH_RATELIMIT_WINDOW:
            q.popleft()
        return len(q) >= AUTH_RATELIMIT_MAX


# ---------------------------------------------------------------------------
# Подключение к FastAPI
# ---------------------------------------------------------------------------

def _is_protected(path: str, prefixes) -> bool:
    return any(path == p or path.startswith(p) for p in prefixes)


def install_auth(app, protected_prefixes, realm: str = "Restricted"):
    """
    Добавить HTTP Basic auth к FastAPI-приложению.

    app               — FastAPI instance
    protected_prefixes— кортеж префиксов путей, которые защищаем,
                        напр. ("/admin", "/api/admin"). Публичные пути
                        (/health, /api/v1/* и т.п.) просто НЕ вписывать.
    realm             — имя realm в WWW-Authenticate.
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    def _unauthorized():
        return JSONResponse(
            {"detail": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{realm}", charset="UTF-8"'},
        )

    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):
        if AUTH_DISABLED or not _is_protected(request.url.path, protected_prefixes):
            return await call_next(request)

        client_ip = request.client.host if request.client else "?"

        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("basic "):
            return _unauthorized()
        try:
            raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
            username, _, password = raw.partition(":")
        except Exception:
            return _unauthorized()
        if not username or not password:
            return _unauthorized()

        if _ratelimited(client_ip):
            return JSONResponse(
                {"detail": "Too many failed attempts. Try later."},
                status_code=403,
            )

        ok, detail = check_user(username, password)
        if ok:
            return await call_next(request)

        _record_fail(client_ip)
        return _unauthorized()

    return app


# ---------------------------------------------------------------------------
# CLI-самопроверка:  python3 ldap_auth_module.py <логин>
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import getpass

    user = sys.argv[1] if len(sys.argv) > 1 else input("Логин: ").strip()
    pwd = getpass.getpass(f"Пароль для {user}: ")

    print(f"LDAP: {LDAP_HOST}:{LDAP_PORT}  base={LDAP_BASE_DN}")
    print(f"Группа: {LDAP_GROUP_DN or '(проверка отключена)'}")
    ok, detail = check_user(user, pwd)
    print("РЕЗУЛЬТАТ:", "OK — доступ разрешён" if ok else "ОТКАЗ")
    print("ДЕТАЛИ:", detail)
