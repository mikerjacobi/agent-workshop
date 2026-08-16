"""``mothership`` CLI entry point."""

import contextlib
import re
import sys
import typing as _t
from importlib.metadata import PackageNotFoundError, version

from mothership_cli.commands.agents import AgentsCmd
from mothership_cli.commands.chat import ChatCmd
from mothership_cli.commands.evals import EvalsCmd
from mothership_cli.commands.feedback import FeedbackCmd
from mothership_cli.commands.messages import MessagesCmd
from mothership_cli.commands.profile import ProfileCmd
from mothership_cli.commands.publish import PublishCmd
from mothership_cli.commands.sandboxes import SandboxesCmd
from mothership_cli.commands.threads import ThreadsCmd
from mothership_cli.errors import MothershipCliError
from mothership_cli.config import ConfigError, resolve_profile, set_active_profile, set_identity_override, set_json_output, set_org_override, set_verbose
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import CliApp, CliSubCommand

try:
    __version__ = version("mothership-cli")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0+unknown"

_BOLD_RED = "\033[1;31m"
_RESET = "\033[0m"

# The synthetic model pydantic-settings builds to validate argv, and so the
# title carried by a ValidationError that came from the command line.
_CLI_PARSE_MODEL = "CliAppBaseSettings"


class Mothership(BaseModel):
    """Mothership CLI — manage agents, sandboxes, and profiles."""

    version: bool = Field(default=False, description="Show version and exit")
    profile: str | None = Field(default=None, description="Named profile from ~/.mothership/config.json")
    org: str | None = Field(default=None, description="Org id for tenancy-scoped resources (default: the shared 'default' org)")
    external_id: str | None = Field(default=None, description="Identity asserted via X-External-Id (default: the profile's default_external_id)")
    json_output: bool = Field(default=False, description="Output raw JSON instead of human-readable tables", alias="json")
    verbose: bool = Field(default=False, description="Trace HTTP requests and responses to stderr")

    agents: CliSubCommand[AgentsCmd]
    chat: CliSubCommand[ChatCmd]
    evals: CliSubCommand[EvalsCmd]
    feedback: CliSubCommand[FeedbackCmd]
    messages: CliSubCommand[MessagesCmd]
    profiles: CliSubCommand[ProfileCmd]
    publish: CliSubCommand[PublishCmd]
    sandboxes: CliSubCommand[SandboxesCmd]
    threads: CliSubCommand[ThreadsCmd]

    def cli_cmd(self) -> None:
        if self.version:
            print(f"mothership {__version__}")
            sys.exit(0)
        set_json_output(self.json_output)
        set_verbose(self.verbose)
        # Overrides are set before profile resolution so they apply even when
        # there is no profile to fall back to (e.g. MOTHERSHIP_BASE_URL alone).
        set_org_override(self.org)
        set_identity_override(self.external_id)
        try:
            name, prof = resolve_profile(self.profile)
            set_active_profile(name, prof)
        except ConfigError:
            # An unresolvable profile is only fatal for commands that go on to
            # need one — `profiles set` has to work with no config at all. But a
            # --profile the user named explicitly and got wrong is worth saying
            # so, rather than letting it surface later as "no active profile".
            if self.profile:
                raise
        CliApp.run_subcommand(self)


_REPEATED_V = re.compile(r"^-(v+)$")

# Where the root's flags end and a subcommand's begin, for argv rewriting done
# before the parser exists. Held to the declared groups by a test.
_SUBCOMMAND_NAMES = frozenset({"agents", "chat", "evals", "feedback", "messages", "profiles", "publish", "sandboxes", "threads"})


def _expand_repeated_verbosity(argv: list[str]) -> list[str]:
    """Make repeated ``-v`` mean what each scope's flag means.

    Before the subcommand it is the root's binary ``--verbose``; after it, it is
    ``chat``'s level, so ``-vvv`` becomes ``-v 3`` and a bare ``-v`` becomes
    ``-v 1``. ``chat`` documents the repeated form, but pydantic-settings has no
    count-style flag — ``-v`` is an int option, so ``-vvv`` would otherwise reach
    the parser as the value ``"vv"``. An explicit ``-v 2`` is left alone.
    """
    out: list[str] = []
    in_subcommand = False
    for i, token in enumerate(argv):
        if token in _SUBCOMMAND_NAMES:
            in_subcommand = True
        match = _REPEATED_V.match(token)
        if match is None:
            out.append(token)
            continue
        if not in_subcommand:
            # The root flag is binary: any number of repeats just turns it on.
            out.append("--verbose")
            continue
        following = argv[i + 1] if i + 1 < len(argv) else None
        if len(match.group(1)) == 1 and following is not None and _is_int(following):
            out.append(token)
        else:
            out.extend(["-v", str(len(match.group(1)))])
    return out


def _is_int(token: str) -> bool:
    try:
        int(token)
    except ValueError:
        return False
    return True


def _print_help_for_invocation() -> None:
    """Print the help for the subcommand the user ran, on stderr.

    ``--help`` is handled while parsing, before the model is built, so replaying
    the original argv with it appended reaches the same parser the invocation
    did and exits there — no command runs twice.

    argparse writes help to stdout, which is where ``--json`` output goes, so it
    is redirected: a failed command must not put a usage wall where a caller is
    piping JSON.
    """
    try:
        with contextlib.redirect_stdout(sys.stderr):
            CliApp.run(Mothership, cli_args=[*_expand_repeated_verbosity(sys.argv[1:]), "--help"])
    except SystemExit:
        pass


def _exit_with_usage(message: str) -> _t.NoReturn:
    label = f"{_BOLD_RED}Error:{_RESET}" if sys.stderr.isatty() else "Error:"
    # Blank lines above and below: the message sits between the shell prompt
    # and a wall of usage text, and runs together with both without them.
    # Continuations indent under the label, since one invocation can be wrong
    # in more than one way.
    body = message.replace("\n", "\n" + " " * len("Error: "))
    sys.stderr.write(f"\n{label} {body}\n\n")
    sys.stderr.flush()
    _print_help_for_invocation()
    sys.exit(1)


def _describe_field(loc: tuple[int | str, ...]) -> str:
    """Render a pydantic error location as the flag the user actually typed:
    ``('sandboxes', 'search', 'limit')`` → ``sandboxes search --limit``."""
    if not loc:
        return ""
    *path, field = (str(part) for part in loc)
    flag = f"-{field}" if len(field) == 1 else f"--{field.replace('_', '-')}"
    return " ".join([*path, flag])


def _format_validation_error(error: ValidationError) -> str:
    return "\n".join(f"{_describe_field(e['loc'])}: {e['msg']}".lstrip(": ") for e in error.errors())


def main() -> None:
    try:
        CliApp.run(Mothership, cli_args=_expand_repeated_verbosity(sys.argv[1:]), cli_exit_on_error=True)
    except MothershipCliError as e:
        sys.stderr.write(f"\nError: {e}\n")
        sys.exit(1)
    except ConfigError as e:
        # Missing profile/agent_id/external_id is user error, not a crash: the
        # subcommands resolve these lazily, so this is the only place that sees
        # all of them.
        _exit_with_usage(str(e))
    except ValidationError as e:
        # A badly typed argument, e.g. --limit abc. Only the arg parse is user
        # error: pydantic-settings validates argv against this synthetic model,
        # so any other title is a mismatch against an API response and should
        # keep its traceback rather than be dressed up as a usage error.
        if e.title != _CLI_PARSE_MODEL:
            raise
        _exit_with_usage(_format_validation_error(e))


if __name__ == "__main__":
    main()
