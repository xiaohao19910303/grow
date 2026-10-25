"""Restart-safe source delivery sweep over server-owned account identities."""
import asyncio
import logging
from tenancy import current_user

log=logging.getLogger(__name__)


def sweep(accounts,plans_store=None):
    from action_source_delivery import retry_due
    # Enumerate only server-owned identities. No schema/account names from requests.
    with accounts.conn() as c:
        columns='id,schema_name,is_owner'+(',github_config' if plans_store is not None else '')
        users=[dict(r) for r in c.execute('SELECT '+columns+' FROM auth_users ORDER BY id')]
    for user in users:
        token=current_user.set(user)
        try:
            import db
            # Avoid creating action tables for accounts which have never used them.
            with db.connect() as c:
                present=c.execute("SELECT to_regclass('action_source_outbox')").fetchone()[0]
            if present:
                retry_due(limit=10)
                if plans_store is not None:
                    from mobile_progress import sync
                    sync(plans_store)
        except Exception:
            log.warning('Source delivery sweep deferred for one account',exc_info=False)
        finally:current_user.reset(token)


async def run(accounts,plans_store=None):
    while True:
        try:await asyncio.to_thread(sweep,accounts,plans_store)
        except Exception:log.warning('Source delivery sweep deferred',exc_info=False)
        await asyncio.sleep(30)
