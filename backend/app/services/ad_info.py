"""Employee card service (P-29): AD reads behind a DB cache.

Cache policy (owner question "what if the user changes the photo later?"):
a fresh copy (younger than ad_info_ttl_seconds, default 24 h) is served
without touching AD; an older copy is refreshed on the next read. The photo
therefore follows AD changes within the TTL window - no manual invalidation.

Login resolution for a Support Hub user: the Tag webhook carries
``user_name`` (the Tag/Mattermost username, typically the domain login) and
``user_id`` (a Tag-side id that does NOT match AD). Identities are tried in
order: external_user_name, then external_user_id (some channels may pass the
login directly).

AD unavailability or a missing service account degrades gracefully: the
card is returned with ``available=False`` and cached misses are retried on
the next request (no negative caching).
"""

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.ad_directory import AdDirectory, AdUnavailableError, demo_card
from app.repositories.users import UserRepository
from app.services._tx import unit_of_work

logger = logging.getLogger(__name__)

# Owner (2026-11-17): only ORGANIZATIONAL data is persisted in the DB —
# title, department, phones, manager. Access-related fields (groups,
# disabled/locked, password dates) are sensitive: they are fetched LIVE
# from AD when the full card is opened and never stored.
SAFE_AD_FIELDS = frozenset(
    {"login", "full_name", "email", "title", "department", "company", "phone", "mobile", "manager"}
)


def _persistable_card(card: dict[str, Any]) -> dict[str, Any]:
    """Strip access-related fields before writing into users.ad_info."""
    return {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in card.items()
        if k in SAFE_AD_FIELDS
    }

# Perf (2026-11-17): /me/photo used to hit LDAP on EVERY workspace render
# (bind + search + thumbnailPhoto, up to 10 s on a slow AD). Photos change
# rarely — same policy as the card cache: serve a copy younger than the TTL.
_PHOTO_CACHE: dict[str, tuple[float, bytes | None]] = {}
_PHOTO_CACHE_TTL_SECONDS = 3600.0
_PHOTO_CACHE_MAX_ENTRIES = 512


def _cached_photo(login: str) -> tuple[bytes | None, bool]:
    entry = _PHOTO_CACHE.get(login.lower())
    if entry is None:
        return None, False
    stored_at, photo = entry
    if time.monotonic() - stored_at > _PHOTO_CACHE_TTL_SECONDS:
        _PHOTO_CACHE.pop(login.lower(), None)
        return None, False
    return photo, True


def _store_photo(login: str, photo: bytes | None) -> None:
    if len(_PHOTO_CACHE) >= _PHOTO_CACHE_MAX_ENTRIES:
        _PHOTO_CACHE.clear()  # small self-healing cache, no LRU machinery
    _PHOTO_CACHE[login.lower()] = (time.monotonic(), photo)

# Perf (2026-11-17): a login that does NOT exist in AD used to trigger a
# fresh LDAP walk on every /ad/user call (each up to the 30 s search
# budget). Cache the miss for 10 minutes — a newly created account becomes
# visible within that window.
_AD_MISS_CACHE: dict[str, float] = {}
_AD_MISS_TTL_SECONDS = 600.0
_AD_MISS_MAX_ENTRIES = 1024


def _recently_missed(login: str) -> bool:
    stored = _AD_MISS_CACHE.get(login.lower())
    return stored is not None and time.monotonic() - stored < _AD_MISS_TTL_SECONDS


def _mark_miss(login: str) -> None:
    if len(_AD_MISS_CACHE) >= _AD_MISS_MAX_ENTRIES:
        _AD_MISS_CACHE.clear()
    _AD_MISS_CACHE[login.lower()] = time.monotonic()


class AdInfoService:
    def __init__(
        self,
        directory: AdDirectory | None = None,
        users: UserRepository | None = None,
    ) -> None:
        self._directory = directory or AdDirectory(get_settings())
        self._users = users or UserRepository()

    async def get_for_user(
        self, session: AsyncSession, user_id: uuid.UUID, *, force: bool = False
    ) -> dict[str, Any]:
        """Public card: ``available=False`` when AD is not configured.

        ``force=True`` bypasses the 24h TTL — the operator's manual
        "Обновить из AD" button (owner 2026-11-17)."""
        user = await self._users.get(session, user_id)
        if user is None:
            raise LookupError(f"User {user_id} not found")
        settings = get_settings()

        fresh = (
            not force
            and user.ad_info is not None
            and user.ad_synced_at is not None
            and (
                datetime.now(UTC) - user.ad_synced_at
            ).total_seconds() < settings.ad_info_ttl_seconds
        )
        live_card: dict[str, Any] | None = None
        if not fresh and (self._directory.configured or settings.ad_demo):
            live_card = await self._refresh(session, user_id)
            user = await self._users.get(session, user_id)

        info = dict(user.ad_info or {}) if user is not None else {}
        if live_card:
            # Owner (2026-11-17): the RESPONSE carries the full fresh card
            # (groups, account status, password dates) — but only the safe
            # organizational fields were persisted by _refresh.
            info.update(
                {
                    k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in live_card.items()
                    if k != "_photo"
                }
            )
        info["available"] = bool(info)
        if info and not self._directory.configured and settings.ad_demo:
            # Canned "Иван Петров" preview (AD_DEMO=true, no service account):
            # mark it so the UI can tell demo data from real AD data.
            info["demo"] = True
        info["photo_url"] = f"/api/v1/operator/users/{user_id}/ad-photo" if info else ""
        info["synced_at"] = (
            user.ad_synced_at.isoformat() if user is not None and user.ad_synced_at else None
        )
        return info

    async def get_photo(self, session: AsyncSession, user_id: uuid.UUID) -> bytes | None:
        """Cached photo bytes; None = no photo known for the user."""
        user = await self._users.get(session, user_id)
        if user is None:
            raise LookupError(f"User {user_id} not found")
        return user.ad_photo or None

    async def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """People search for the AD lookup dialog (owner request 2026-11-12).

        Without a service account (and with AD_DEMO) returns a small demo
        roster filtered by the query, so the dialog works in dev."""
        query = query.strip()
        if not query:
            return []
        if not self._directory.configured:
            if not get_settings().ad_demo:
                return []
            roster = [demo_card(login) for login in ("i.petrov", "m.ivanova", "a.smirnova")]
            lowered = query.lower()
            return [
                {
                    **{k: v for k, v in card.items() if not k.startswith("_")},
                    "demo": True,
                }
                for card in roster
                if lowered in card["login"].lower()
                or lowered in card["full_name"].lower()
                or lowered in card["email"].lower()
            ][:limit]
        return await self._directory.search(query, limit=limit)
    async def user_by_login(self, login: str) -> dict[str, Any] | None:
        """Full card for an arbitrary AD login (the search dialog detail view)."""
        login = login.strip()
        if not login:
            return None
        if not self._directory.configured:
            if not get_settings().ad_demo:
                return None
            card = demo_card(login)
            return {**{k: v for k, v in card.items() if not k.startswith("_")}, "demo": True}
        if _recently_missed(login):
            return None
        found: dict[str, Any] | None = await self._directory.get_user(login)
        if not found:
            _mark_miss(login)
        return found

    async def photo_for_login(self, login: str) -> bytes | None:
        """AD photo bytes for an arbitrary login (operator self avatar)."""
        login = login.strip()
        if not login:
            return None
        photo, hit = _cached_photo(login)
        if hit:
            return photo
        result: bytes | None
        if not self._directory.configured:
            if not get_settings().ad_demo:
                result = None
            else:
                result = demo_card(login).get("_photo")
        else:
            try:
                card = await self._directory.get_user(login)
            except AdUnavailableError:
                return None  # AD down: not cached, retried next request
            result = (card or {}).get("_photo")
        _store_photo(login, result)
        return result

    async def _refresh(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Fetch from AD, persist the SAFE fields, and hand the FULL fresh
        card back to the caller (only organizational data reaches the DB).
        Failures leave the stale copy in place and return None."""
        identities = await self._users.list_identities(session, user_id)
        candidates: list[str] = []
        for identity in identities:
            for value in (identity.external_user_name, identity.external_user_id):
                if value and value not in candidates:
                    candidates.append(value)
        settings = get_settings()
        card: dict[str, Any] | None = None
        if not self._directory.configured:
            if not settings.ad_demo or not candidates:
                return None
            # UI preview without AD (AD_DEMO=true, dev only). Fake data —
            # no need to strip access fields.
            card = demo_card(candidates[0])
            async with unit_of_work(session):
                user = await self._users.get(session, user_id)
                assert user is not None
                user.ad_info = {
                    k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in card.items()
                    if k != "_photo"
                }
                user.ad_photo = card.get("_photo") or None
                user.ad_synced_at = datetime.now(UTC)
            return card
        for candidate in candidates:
            try:
                card = await self._directory.get_user(candidate)
            except AdUnavailableError as exc:
                logger.info("AD card unavailable for %s: %s", candidate, exc)
                return None
            if card is None:
                continue
            async with unit_of_work(session):
                user = await self._users.get(session, user_id)
                assert user is not None  # checked by the caller
                user.ad_info = _persistable_card(card)
                user.ad_photo = card.get("_photo") or None
                user.ad_synced_at = datetime.now(UTC)
            return card
        # Not found in AD under any identity: nothing to cache (no negative
        # caching) - the next request may retry after e.g. HR data lands.
        return None
