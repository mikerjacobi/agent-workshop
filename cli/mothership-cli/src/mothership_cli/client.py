"""CLI-facing surface of the mothership REST client: re-exports the shared
client (mothership_client.client) and adds profile-driven construction plus the
verbose-tracing hook. Commands import from here; non-CLI code (the evaluator)
imports mothership_client.client directly."""

from mothership_client.client import *  # noqa: F401,F403
from mothership_client.client import MothershipClient, set_verbose_hook


def _is_verbose() -> bool:
    from mothership_cli.config import is_verbose  # cycle: config imports nothing from here, but keep lazy for import cost

    return is_verbose()


set_verbose_hook(_is_verbose)


def get_client() -> MothershipClient:
    """Return a client for the active profile's API."""
    from mothership_cli.config import get_active_profile, resolve_api_key, resolve_identity, resolve_org  # deferred: circular with config

    _, profile = get_active_profile()
    return MothershipClient(
        profile.base_url,
        org=resolve_org(),
        external_id=resolve_identity(),
        api_key=resolve_api_key(),
    )
