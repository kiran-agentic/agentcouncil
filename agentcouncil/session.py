"""agentcouncil.session — OutsideSession lifecycle and OutsideSessionAdapter shim.

Provides:
    OutsideSession        — Composes OutsideProvider + OutsideRuntime into an
                            open/call/close lifecycle with session-strategy-aware
                            message routing.
    OutsideSessionAdapter — Backward-compatibility shim wrapping OutsideSession
                            as an AgentAdapter for existing protocol engines.

Design notes:
    - OutsideSession derives session_strategy and workspace_access from the
      provider's class-level capability attributes (UPROV-04) at init time.
    - Persistent providers (codex, claude, kiro) receive only the latest user
      message per call() — they maintain their own conversation state (USESS-01).
    - Replay providers (ollama, openrouter, bedrock, stub) receive the full
      accumulated message history on every call() — they are stateless (USESS-02).
    - self._messages always accumulates the full history regardless of strategy.
      turn_messages is a local view passed to run_turn, sliced by session_strategy.
    - session_mode is kept in sync with session_strategy for TranscriptMeta
      backward compatibility (server.py reads session.session_mode).
    - OutsideSessionAdapter.call() raises RuntimeError — the adapter is async-only.
    - The DeprecationWarning in AgentAdapter.__init_subclass__ fires at class
      definition time for this module (cls.__module__ == "agentcouncil.session").
      This is correct and intentional — it signals that AgentAdapter is the
      deprecated extension point. New backends should implement OutsideProvider.
"""
from __future__ import annotations

from typing import Any

from agentcouncil.adapters import AdapterError, AgentAdapter
from agentcouncil.providers.base import OutsideProvider
from agentcouncil.runtime import OutsideRuntime

__all__ = ["OutsideSession", "OutsideSessionAdapter"]


# ---------------------------------------------------------------------------
# OutsideSession — open/call/close lifecycle
# ---------------------------------------------------------------------------


class OutsideSession:
    """Stateful session over an OutsideProvider + OutsideRuntime pair.

    Manages the message history for multi-turn conversations. Routing of
    messages to run_turn is determined by session_strategy, which is derived
    from the provider's class-level capability attribute (UPROV-04):

        session_strategy="persistent" (codex, claude, kiro):
            Only the latest user message is sent to run_turn each turn.
            The provider maintains its own conversation state internally.
            Full history is still tracked in self._messages for recovery.

        session_strategy="replay" (ollama, openrouter, bedrock, stub):
            The full accumulated message history is sent to run_turn each turn.
            Stateless providers require replayed history to have context.

    Attributes:
        session_strategy — "persistent" | "replay" (derived from provider)
        session_mode     — Always equals session_strategy (TranscriptMeta compat)
        workspace_access — "native" | "assisted" | "none" (derived from provider)

    Args:
        provider         — Backend provider (auth + chat_complete)
        runtime          — Execution layer (tool loop, budget checks)
        session_mode     — Fallback deliberation mode hint (default: "replay")
        workspace_access — Fallback workspace access hint (default: "assisted")
        profile          — Named config profile (optional)
        model            — Model identifier override (optional)
        provider_name    — Provider name string (optional)
    """

    def __init__(
        self,
        provider: OutsideProvider,
        runtime: OutsideRuntime,
        session_mode: str = "replay",
        workspace_access: str = "assisted",
        profile: str | None = None,
        model: str | None = None,
        provider_name: str | None = None,
    ) -> None:
        self._provider = provider
        self._runtime = runtime
        self._messages: list[dict[str, Any]] = []
        # USESS-01/02: derive session_strategy from provider capability (UPROV-04)
        self.session_strategy: str = getattr(provider, "session_strategy", session_mode)
        # Backward compat: session_mode tracks session_strategy for TranscriptMeta consumers
        self.session_mode = self.session_strategy
        # USESS-03: derive workspace_access from provider capability
        self.workspace_access: str = getattr(provider, "workspace_access", workspace_access)
        self.profile = profile
        self.model = model
        self.provider_name = provider_name

    async def open(self) -> None:
        """Verify provider credentials.

        Calls provider.auth_check() — raises ProviderError if credentials are
        invalid or unavailable.
        """
        await self._provider.auth_check()

    async def call(self, prompt: str) -> str:
        """Send a prompt and return the assistant response as text.

        Appends a user message, runs a single turn via OutsideRuntime, then
        appends the assistant response. The messages sent to run_turn are
        determined by session_strategy (USESS-01 / USESS-02):

            persistent — only the latest user message is sent (turn_messages = [last])
            replay     — full accumulated history is sent (turn_messages = self._messages)

        self._messages always accumulates the full history regardless of strategy.

        Args:
            prompt — User message to send.

        Returns:
            Text response from the provider.
        """
        self._messages.append({"role": "user", "content": prompt})
        # USESS-01: persistent providers receive only the latest user message
        # USESS-02: replay providers receive the full accumulated history
        if self.session_strategy == "persistent":
            turn_messages = [self._messages[-1]]
        else:
            turn_messages = self._messages
        response = await self._runtime.run_turn(turn_messages)
        self._messages.append({"role": "assistant", "content": response})
        return response

    async def close(self) -> None:
        """Close the session.

        No-op for HTTP providers. Override in subclasses if cleanup is needed
        (e.g., terminating a subprocess or releasing a connection pool).
        """
        pass


# ---------------------------------------------------------------------------
# OutsideSessionAdapter — backward-compatibility shim
# ---------------------------------------------------------------------------


class OutsideSessionAdapter(AgentAdapter):
    """Wraps OutsideSession as an AgentAdapter for existing protocol engines.

    Provides backward compatibility with run_deliberation() and other callers
    expecting the AgentAdapter interface. The adapter is async-only — call()
    raises RuntimeError to prevent accidental synchronous usage.

    Note: This class subclasses AgentAdapter, which triggers a DeprecationWarning
    at import time. This is intentional — it signals that AgentAdapter is the
    deprecated extension point. New backends should implement OutsideProvider.

    Args:
        session — An OutsideSession instance to delegate calls to.
    """

    def __init__(self, session: OutsideSession) -> None:
        self._session = session

    def call(self, prompt: str) -> str:
        """Not supported — OutsideSessionAdapter is async-only.

        Raises:
            RuntimeError: always, with a message directing users to acall().
        """
        raise RuntimeError(
            "OutsideSessionAdapter is async-only — use acall() or run_deliberation()"
        )

    async def acall(self, prompt: str) -> str:
        """Send prompt via the underlying OutsideSession and return the response.

        Args:
            prompt — User message to send.

        Returns:
            Text response from the provider.

        Raises:
            AdapterError: if the underlying session.call() raises any exception.
        """
        try:
            return await self._session.call(prompt)
        except Exception as e:
            raise AdapterError(f"OutsideSession call failed: {e}") from e
