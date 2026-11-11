"""Promote the first verified Keycloak-backed administrator.

Run from ``backend`` after configuring DATABASE_URL. The identity must already
exist and its Keycloak subject must match; the command is refused if an active
administrator already exists. This is an offline deployment operation, not an
unauthenticated HTTP bootstrap endpoint.
"""

import argparse
import asyncio

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import AuditActorType, AuditLog, Operator, OperatorRole


async def bootstrap(email: str, keycloak_sub: str | None = None) -> None:
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(1297040467)"))
            existing_admin = await session.scalar(
                select(func.count())
                .select_from(Operator)
                .where(
                    Operator.role == OperatorRole.ADMIN,
                    Operator.is_active.is_(True),
                )
            )
            if existing_admin:
                raise SystemExit("An active administrator already exists; refusing bootstrap.")
            operator = await session.scalar(
                select(Operator)
                .where(
                    func.lower(Operator.email) == email.lower(),
                    Operator.is_active.is_(True),
                    *( [Operator.keycloak_sub == keycloak_sub] if keycloak_sub else [] ),
                )
                .with_for_update()
            )
            if operator is None:
                raise SystemExit(
                    "No active profile matches the email"
                    + (" and Keycloak subject." if keycloak_sub else ".")
                )
            operator.role = OperatorRole.ADMIN
            session.add(
                AuditLog(
                    actor_type=AuditActorType.SYSTEM,
                    actor_id=None,
                    action="operator.initial_admin_bootstrapped",
                    entity_type="operator",
                    entity_id=operator.id,
                    details={"email": operator.email},
                )
            )
        print(f"Initial administrator enabled for {email}.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Existing operator email")
    parser.add_argument(
        "--keycloak-sub",
        default=None,
        help="Verified Keycloak subject (omit for LDAP-based profiles)",
    )
    args = parser.parse_args()
    asyncio.run(bootstrap(args.email.strip(), (args.keycloak_sub or "").strip() or None))


if __name__ == "__main__":
    main()
