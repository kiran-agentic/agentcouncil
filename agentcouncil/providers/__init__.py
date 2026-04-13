"""agentcouncil.providers — Outside LLM provider contracts and implementations.

Re-exports:
    OutsideProvider    — Abstract base class for all backend providers
    ProviderResponse   — Pydantic model for chat_complete results
    ToolCall           — Pydantic model for a single tool invocation
    ProviderError      — Exception raised on provider failures
    StubProvider       — Deterministic test double
    ClaudeProvider     — Claude CLI subprocess provider (requires claude CLI)
    OllamaProvider     — Local Ollama instance provider (requires ollama SDK)
    OpenRouterProvider — OpenRouter cloud provider via openai SDK (requires openai SDK)
    BedrockProvider    — AWS Bedrock provider via boto3 (requires boto3)
    KiroProvider       — Kiro CLI ACP subprocess provider (requires kiro-cli)
    CodexProvider      — Codex MCP server provider (requires fastmcp + codex CLI)
"""
from __future__ import annotations

from .base import (
    OutsideProvider,
    ProviderError,
    ProviderResponse,
    StubProvider,
    ToolCall,
)

from .claude import ClaudeProvider

# Optional providers — available only when their SDK extras are installed.
# __all__ is built dynamically so it only advertises what's actually importable.

_optional_providers: list[str] = []

try:
    from .ollama import OllamaProvider
    _optional_providers.append("OllamaProvider")
except ImportError:
    pass

try:
    from .openrouter import OpenRouterProvider
    _optional_providers.append("OpenRouterProvider")
except ImportError:
    pass

try:
    from .bedrock import BedrockProvider
    _optional_providers.append("BedrockProvider")
except ImportError:
    pass

try:
    from .kiro import KiroProvider
    _optional_providers.append("KiroProvider")
except ImportError:
    pass

try:
    from .codex import CodexProvider
    _optional_providers.append("CodexProvider")
except ImportError:
    pass

__all__ = [
    "OutsideProvider",
    "ProviderResponse",
    "ToolCall",
    "ProviderError",
    "StubProvider",
    "ClaudeProvider",
    *_optional_providers,
]
