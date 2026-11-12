"""Unit tests of the AD employee card service (P-29) on real PostgreSQL.

The directory is faked; the service under test is the real cache/refresh
logic and the login resolution from user identities.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import User, UserIdentity
from app.repositories.users import UserRepository
from app.services.ad_info import AdInfoService


class FakeDirectory:
    def __init__(self, cards: dict[str, dict | None]) -> None:
        self.cards = cards
        self.calls: list[str] = []
        self.configured = True

    async def get_user(self, login: str) -> dict | None:
        self.calls.append(login)
        return self.cards.get(login)


def fake_card(login: str) -> dict:
    return {
        "login": login,
        "full_name": "Иван Петров",
        "email": f"{login}@corp.tander.ru",
        "title": "Специалист",
        "department": "ИТ",
        "company": "Магнит",
        "phone": "8-800",
        "mobile": "+7-900",
        "manager": "Мария Иванова",
        "disabled": False,
        "locked": False,
        "password_changed_at": datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
        "password_expires_at": None,
        "groups": ["1C-Users", "VPN-Access"],
        "has_photo": True,
        "_photo": b"jpeg-bytes",
    }


async def make_user(session_factory, *, name: str | None, ext_id: str) -> uuid.UUID:
    async with session_factory() as session:
        user = User(display_name=name or ext_id)
        session.add(user)
        await session.flush()
        session.add(
            UserIdentity(
                user_id=user.id,
                channel_type="tag",
                external_user_id=ext_id,
                external_user_name=name,
            )
        )
        await session.commit()
        return user.id


@pytest.mark.anyio
async def test_card_fetched_cached_and_photo_stored(session_factory, monkeypatch) -> None:
    user_id = await make_user(session_factory, name="petrov", ext_id="tag-id-1")
    directory = FakeDirectory({"petrov": fake_card("petrov")})
    service = AdInfoService(directory=directory)

    async with session_factory() as session:
        card = await service.get_for_user(session, user_id)
        assert card["available"] is True
        assert card["full_name"] == "Иван Петров"
        assert card["groups"] == ["1C-Users", "VPN-Access"]
        photo = await service.get_photo(session, user_id)
        assert photo == b"jpeg-bytes"

    # Cache hit: the second read does not touch AD.
    async with session_factory() as session:
        again = await service.get_for_user(session, user_id)
        assert again["available"] is True
    assert directory.calls == ["petrov"]


@pytest.mark.anyio
async def test_stale_cache_is_refreshed(session_factory, monkeypatch) -> None:
    user_id = await make_user(session_factory, name="petrov", ext_id="tag-id-2")
    directory = FakeDirectory({"petrov": fake_card("petrov")})
    service = AdInfoService(directory=directory)

    async with session_factory() as session:
        await service.get_for_user(session, user_id)

    # Simulate TTL expiry by backdating the sync stamp.
    async with session_factory() as session:
        user = await UserRepository().get(session, user_id)
        assert user is not None and user.ad_synced_at is not None
        user.ad_synced_at = user.ad_synced_at - timedelta(seconds=86401)
        await session.commit()

    async with session_factory() as session:
        card = await service.get_for_user(session, user_id)
        assert card["available"] is True
    assert directory.calls == ["petrov", "petrov"]


@pytest.mark.anyio
async def test_not_found_in_ad_degrades_gracefully(session_factory) -> None:
    user_id = await make_user(session_factory, name="unknown", ext_id="tag-id-3")
    directory = FakeDirectory({})  # AD has nobody under these identities
    service = AdInfoService(directory=directory)

    async with session_factory() as session:
        card = await service.get_for_user(session, user_id)
        assert card["available"] is False

    # No negative caching: the next request retries AD (all candidates again).
    async with session_factory() as session:
        await service.get_for_user(session, user_id)
    assert directory.calls == ["unknown", "tag-id-3", "unknown", "tag-id-3"]


@pytest.mark.anyio
async def test_unconfigured_directory_reports_unavailable(session_factory) -> None:
    user_id = await make_user(session_factory, name="petrov", ext_id="tag-id-4")
    directory = FakeDirectory({"petrov": fake_card("petrov")})
    directory.configured = False
    service = AdInfoService(directory=directory)

    async with session_factory() as session:
        card = await service.get_for_user(session, user_id)
        assert card["available"] is False
    assert directory.calls == []


@pytest.mark.anyio
async def test_demo_mode_serves_preview_card(session_factory, monkeypatch) -> None:
    """AD_DEMO=true: a synthetic card + photo without any AD access."""
    from app.config import get_settings

    monkeypatch.setattr("app.services.ad_info.get_settings", get_settings)
    monkeypatch.setenv("AD_DEMO", "true")
    get_settings.cache_clear()
    try:
        user_id = await make_user(session_factory, name="petrov", ext_id="tag-id-5")
        directory = FakeDirectory({})
        directory.configured = False
        service = AdInfoService(directory=directory)

        async with session_factory() as session:
            card = await service.get_for_user(session, user_id)
            assert card["available"] is True
            assert card["full_name"]
            assert card["groups"]
            photo = await service.get_photo(session, user_id)
            assert photo and photo.startswith(b"\x89PNG")
    finally:
        get_settings.cache_clear()
