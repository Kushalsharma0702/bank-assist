"""Shared custom exceptions."""


class NoSpeechDetectedError(Exception):
    """Raised when Azure STT returns NoMatch (silence / inaudible audio)."""
