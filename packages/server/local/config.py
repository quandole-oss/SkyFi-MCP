"""SkyFi MCP local server — configuration and environment validation."""

from __future__ import annotations

import os


class ServerConfig:
    """Configuration for the local MCP server, loaded from environment."""

    def __init__(self) -> None:
        self.api_key = self._require_env("SKYFI_API_KEY")

    @staticmethod
    def _require_env(name: str) -> str:
        """Read a required environment variable or raise a clear error."""
        value = os.environ.get(name)
        if not value:
            raise RuntimeError(
                f"Environment variable {name} is not set. "
                f"Add it to your MCP client configuration:\n\n"
                f'  "env": {{ "{name}": "sk-..." }}\n\n'
                f"You can obtain an API key at https://app.skyfi.com/settings/api"
            )
        return value


def load_config() -> ServerConfig:
    """Load and validate the server configuration.

    Returns:
        A validated ``ServerConfig`` instance.

    Raises:
        RuntimeError: If required environment variables are missing.
    """
    return ServerConfig()
