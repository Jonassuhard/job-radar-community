"""Canonical registry for connectors delivered by this distribution."""

DELIVERED_REMOTE_CONNECTORS: frozenset[str] = frozenset()


def remote_connector_available(name: str, mode: str) -> bool:
    """Return whether this build can execute the configured remote connector."""

    return mode in {"api", "ats"} and name in DELIVERED_REMOTE_CONNECTORS
