"""Runtime dependency container.

Built once at app creation (connections are lazy), closed on lifespan shutdown.
Object storage is NOT a local dependency: attachments arrive at stage 5 and the
corporate network provides its own storage (see deploy/docker-compose.yml).
"""

from dataclasses import dataclass

from app.auth.ldap import LdapAuthenticator
from app.config import Settings
from app.infra.db import DatabaseClient
from app.infra.redis_client import RedisClient


@dataclass
class Dependencies:
    db: DatabaseClient
    redis: RedisClient
    # LDAP authenticator (D-047); tests inject a fake via this field.
    ldap: LdapAuthenticator | None = None

    async def close(self) -> None:
        await self.db.close()
        await self.redis.close()


def build_dependencies(settings: Settings) -> Dependencies:
    return Dependencies(
        db=DatabaseClient(settings.database_url),
        redis=RedisClient(settings.redis_url),
        ldap=LdapAuthenticator(settings),
    )
