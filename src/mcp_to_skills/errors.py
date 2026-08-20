class McpToSkillsError(Exception):
    """An expected, user-facing error."""


class ConfigError(McpToSkillsError):
    """A server configuration is missing or invalid."""


class BrokerError(McpToSkillsError):
    """The local session broker could not complete an operation."""


class McpError(McpToSkillsError):
    """An MCP server or protocol operation failed."""


class McpResponseError(McpError):
    """A JSON-RPC error returned by an MCP server."""

    def __init__(self, code, message, data=None):
        super().__init__("MCP error %s: %s" % (code, message))
        self.code = code
        self.data = data
