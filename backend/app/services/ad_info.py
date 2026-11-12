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
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.ad_directory import AdDirectory, AdUnavailableError, demo_card
from app.repositories.users import UserRepository
from app.services._tx import unit_of_work

logger = logging.getLogger(__name__)


class AdInfoService:
    def __init__(
        self,
        directory: AdDirectory | None = None,
        users: UserRepository | None = None,
    ) -> None:
        self._directory = directory or AdDirectory(get_settings())
        self._users = users or UserRepository()

    async def get_for_user(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> dict[str, Any]:
        """Public card: ``available=False`` when AD is not configured."""
        user = await self._users.get(session, user_id)
        if user is None:
            raise LookupError(f"User {user_id} not found")
        settings = get_settings()

        fresh = (
            user.ad_info is not None
            and user.ad_synced_at is not None
            and (
                datetime.now(UTC) - user.ad_synced_at
            ).total_seconds() < settings.ad_info_ttl_seconds
        )
        if not fresh and (self._directory.configured or settings.ad_demo):
            await self._refresh(session, user_id)
            user = await self._users.get(session, user_id)

        info = dict(user.ad_info or {}) if user is not None else {}
        info["available"] = bool(info)
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

    async def _refresh(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        """Fetch from AD and store; failures leave the stale copy in place."""
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
                return
            # UI preview without AD (AD_DEMO=true, dev only).
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
            return
        for candidate in candidates:
            try:
                card = await self._directory.get_user(candidate)
            except AdUnavailableError as exc:
                logger.info("AD card unavailable for %s: %s", candidate, exc)
                return
            if card is None:
                continue
            async with unit_of_work(session):
                user = await self._users.get(session, user_id)
                assert user is not None  # checked by the caller
                user.ad_info = {
                    # jsonb cannot hold bytes/datetimes: flatten to primitives.
                    k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in card.items()
                    if k != "_photo"
                }
                user.ad_photo = card.get("_photo") or None
                user.ad_synced_at = datetime.now(UTC)
            return
        # Not found in AD under any identity: nothing to cache (no negative
        # caching) - the next request may retry after e.g. HR data lands.
