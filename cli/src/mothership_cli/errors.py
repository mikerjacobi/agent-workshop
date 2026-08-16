"""The one exception base the CLI's top-level handler knows how to print."""


class MothershipCliError(Exception):
    """A failure worth showing the user as a message rather than a traceback."""
