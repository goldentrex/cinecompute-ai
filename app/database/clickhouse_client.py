import logging

import clickhouse_connect

from app.config import settings

logger = logging.getLogger(__name__)


def get_client(readonly: bool = True):
    """Return a ClickHouse client. Read-only is enforced by default.

    TLS certificates are verified by default. `verify=False` was originally set
    to work around a handshake failure, but that failure was the server refusing
    the connection outright (it never sent a certificate), so disabling
    verification fixed nothing and only removed MITM protection - which matters
    once this runs on a public URL. Set CLICKHOUSE_VERIFY=False to opt out.
    """
    kwargs = dict(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
        secure=settings.clickhouse_secure,
        compress=True,
        connect_timeout=settings.clickhouse_connect_timeout,
        send_receive_timeout=settings.clickhouse_query_timeout,
    )
    if settings.clickhouse_secure:
        kwargs["verify"] = settings.clickhouse_verify
    if readonly:
        kwargs["settings"] = {"readonly": 1}

    try:
        return clickhouse_connect.get_client(**kwargs)
    except Exception as e:
        logger.error("Failed to connect to ClickHouse at %s:%s - %s",
                     settings.clickhouse_host, settings.clickhouse_port, e)
        raise
