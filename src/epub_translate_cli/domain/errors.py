from __future__ import annotations


class EpubTranslatorError(Exception):
    """Base domain error for EPUB translation workflows."""


# Backward-compatible alias retained for existing imports.
EpubTranslateError = EpubTranslatorError


class ValidationError(EpubTranslatorError):
    """Input validation error."""


class EpubReadError(EpubTranslatorError):
    """EPUB read/unpack/parse error."""


class EpubWriteError(EpubTranslatorError):
    """EPUB write/pack error."""


class TranslationError(EpubTranslatorError):
    """Base error for translation provider failures."""


class RetryableTranslationError(TranslationError):
    """Retryable translation error (transient)."""


class NonRetryableTranslationError(TranslationError):
    """Non-retryable translation error."""
