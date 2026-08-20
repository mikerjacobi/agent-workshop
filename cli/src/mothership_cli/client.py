"""CLI-facing surface of the mothership REST client: re-exports the shared
client (mothership_cli.client) and adds profile-driven construction plus the
verbose-tracing hook. Commands import from here; non-CLI code (the evaluator)
imports mothership_cli.client directly."""

from mothership_cli.http import *  # noqa: F401,F403
from mothership_cli.http import MothershipClient, set_verbose_hook


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


def ensure_org_member(external_id: str) -> None:
    """Enroll ``external_id`` in the active org via the bare org key.

    Sends are only delivered for thread owners who are org members, and only a
    key with no identity asserted beside it holds the org-admin role the
    members endpoint needs. No-op for the default org (implicit enrollment)
    and for non-admin credentials (membership must already exist there).
    """
    from mothership_cli.config import get_active_profile, resolve_api_key, resolve_org
    from mothership_cli.http import ApiError, MothershipClient
    from mothership_cli.models.org import DEFAULT_ORG_ID

    org = resolve_org()
    if org == DEFAULT_ORG_ID:
        return
    _, profile = get_active_profile()
    bare = MothershipClient(profile.base_url, org=org, external_id=None, api_key=resolve_api_key())
    try:
        bare._request("POST", f"/api/orgs/{org}/members", json={"external_id": external_id})
    except ApiError as exc:
        if exc.status not in (403, 409):
            raise
