"""Harness wire enums: which harness runs in a sandbox and how the
coordinator reaches it. Part of the agent-catalog wire contract."""

from enum import StrEnum


class HarnessType(StrEnum):
    OPENCLAW = "openclaw"
    ZEROCLAW = "zeroclaw"


class TransportMode(StrEnum):
    """How the coordinator reaches the harness, orthogonal to the harness itself; a (harness, transport) pair picks the concrete :class:`Harness`. Only ``relay`` is wired today.

    This is the *harness* transport (coordinator ↔ agent gateway), not the coordinator's SSE *receive* transport (coordinator ↔ client).
    """

    RELAY = "relay"
    BUS = "bus"
