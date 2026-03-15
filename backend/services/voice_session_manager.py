"""
voice_session_manager.py
========================
Clean encapsulation of per-WebSocket voice session state.

DuplexSession (in routers/duplex_router.py) owns the async tasks and the
WebSocket handle.  VoiceSessionManager owns the *mutable state* those tasks read
and write, making it easy to:
  • unit-test state transitions without a live WebSocket
  • snapshot / restore session state for debugging
  • extend with new fields without touching router logic

Usage (inside DuplexSession)
-----------------------------
    from services.voice_session_manager import VoiceSessionManager

    class DuplexSession:
        def __init__(self, ws, language, output_language):
            self._mgr = VoiceSessionManager(language, output_language)
            ...

        async def _run_pipeline(self):
            # history lives on the manager
            self._mgr.append_user(transcript)
            ...
            self._mgr.append_assistant(bot_response)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional


# ─ Conversation turn ──────────────────────────────────────────────────────────

@dataclass
class Turn:
    role: str           # "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.monotonic)
    intent: Optional[str] = None
    confidence: Optional[float] = None
    latency_ms: Optional[float] = None


# ─ Session manager ────────────────────────────────────────────────────────────

class VoiceSessionManager:
    """
    Owns all mutable state for a single voice WebSocket session.

    Attributes
    ----------
    language        : BCP-47 code for the user's speech input  (e.g. "en-US")
    output_language : BCP-47 code for the bot's TTS output     (e.g. "en-US")
    history         : Bedrock-format message list [{role, content}, ...]
    turn_count      : Monotonically increasing turn index
    intent_warmup   : (intent, conf, phrase) from the last STT-partial cosine
                      classification; consumed once per turn, then set to None
    hangup          : True after the session has been terminated
    session_start   : monotonic timestamp of session creation
    """

    def __init__(self, language: str, output_language: str) -> None:
        self.language        = language
        self.output_language = output_language

        # Bedrock-format conversation history
        self.history: List[dict] = []
        self.turn_count: int     = 0
        self.session_start: float = time.monotonic()
        self.hangup: bool = False

        # Intent pre-warming: last cosine-only result from STT partial events.
        # Set by _on_intent_warmup(); consumed (→ None) at pipeline start.
        self.intent_warmup: Optional[tuple] = None

    # ── History helpers ───────────────────────────────────────────────────────

    def append_user(self, text: str) -> None:
        """
        Append a user turn.  Enforces Bedrock's requirement that messages
        alternate strictly user/assistant: if the last message is already a
        user message (e.g. from a barged-in turn with no bot response),
        replace it rather than creating two consecutive user turns.
        """
        if self.history and self.history[-1]["role"] == "user":
            self.history[-1]["content"] = text
        else:
            self.history.append({"role": "user", "content": text})

    def append_assistant(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": text})

    def trim_history(self, max_turns: int = 10) -> None:
        """
        Keep only the most recent `max_turns` *complete* turn pairs to
        bound Bedrock context size and latency.
        """
        # A full pair is 2 messages (user + assistant).  Keep 2*max_turns.
        keep = max_turns * 2
        if len(self.history) > keep:
            self.history = self.history[-keep:]

    # ── Intent warmup helpers ─────────────────────────────────────────────────

    def cache_warmup(self, intent: str, conf: float, phrase: str) -> None:
        """Store a new warmup result, overwriting any previous one."""
        self.intent_warmup = (intent, conf, phrase)

    def consume_warmup(self) -> Optional[tuple]:
        """Return cached warmup (intent, conf, phrase) and clear it."""
        result = self.intent_warmup
        self.intent_warmup = None
        return result

    # ── Turn lifecycle ────────────────────────────────────────────────────────

    def start_turn(self) -> int:
        """Increment and return the new turn counter."""
        self.turn_count += 1
        return self.turn_count

    def elapsed_seconds(self) -> float:
        """Seconds since session creation."""
        return time.monotonic() - self.session_start

    def terminate(self) -> None:
        """Mark session as terminated."""
        self.hangup = True

    # ── Repr ─────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"VoiceSessionManager("
            f"lang={self.language!r}, turns={self.turn_count}, "
            f"history_len={len(self.history)}, hangup={self.hangup})"
        )
