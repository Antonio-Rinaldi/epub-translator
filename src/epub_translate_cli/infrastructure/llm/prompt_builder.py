from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from epub_translate_cli.domain.models import (
    Glossary,
    GlossaryEntry,
    TranslationRequest,
    TranslationSettings,
)

# Language codes (lowercase) mapped to canonical names used in prompts.
_LANGUAGE_NAMES: dict[str, str] = {
    "it": "Italian",
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "ar": "Arabic",
    "pl": "Polish",
    "cs": "Czech",
    "hu": "Hungarian",
    "ro": "Romanian",
    "tr": "Turkish",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "nb": "Norwegian",
}

# Language-specific orthographic and typographic rules injected into the system prompt.
_LANGUAGE_RULES: dict[str, list[str]] = {
    "it": [
        "Use correct Italian accents: grave accent (`) for è, à, ì, ò, ù; "
        "acute accent (´) ONLY for é (as in 'perché', 'né', 'affinché', 'poiché'). "
        "NEVER write 'e'' (letter + apostrophe) instead of 'è', "
        "and NEVER write 'po'' instead of 'può' or other accented forms. "
        "Common errors to avoid: 'e'' → 'è', 'a'' → 'à', 'i'' → 'ì', 'o'' → 'ò', 'u'' → 'ù'.",
        "Italian translations of English prose are typically 5–15% longer. "
        "Do not compress text to match the source length character-for-character; "
        "natural Italian phrasing takes priority over length matching.",
        "Use the apostrophe (') ONLY for genuine elisions and contractions: "
        "l'uomo, dell'arte, all'alba, quell'ora, un'ora (feminine), "
        "but 'un uomo' (masculine, NO apostrophe). "
        "Do NOT use the apostrophe as a substitute for accented letters.",
        "Do not add a space before colons (:), semicolons (;), "
        "exclamation marks (!), or question marks (?). "
        "These marks follow the preceding word directly without a space.",
        "Months and days of the week are lowercase in Italian: "
        "gennaio, febbraio, marzo, lunedì, martedì, mercoledì.",
        "For dialogue, prefer Italian guillemets «…» (caporali) "
        "unless the source text consistently uses a different quotation style throughout.",
        "Preserve Italian capitalization conventions: the pronoun 'io' (I) is lowercase "
        "except at the start of a sentence. Honorifics 'signor', 'dottor', 'professor' "
        "are lowercase unless abbreviated (Sig., Dott., Prof.).",
    ],
    "fr": [
        "Add a non-breaking space (U+00A0) before :, ;, !, and ? as required by French typography.",
        "Use French guillemets « … » for direct speech and quotations.",
        "Months and days of the week are lowercase in French: janvier, février, lundi, mardi.",
    ],
    "de": [
        "Use 'ß' where correct (e.g., Straße, heiß, weißen) "
        "and 'ss' only after short vowels or when 'ß' is not applicable (e.g., Swiss German).",
        "All nouns are capitalised in German, including common nouns.",
        "Use „…“ (lower-9 opening, upper-6 closing) for German quotation marks.",
    ],
    "es": [
        "Use inverted punctuation marks ¿ and ¡ at the start of questions and exclamations.",
        "Months and days of the week are lowercase in Spanish: enero, febrero, lunes, martes.",
    ],
    "pt": [
        "Months and days of the week are lowercase in Portuguese: "
        "janeiro, fevereiro, segunda-feira, terça-feira.",
        "Use the correct nasal vowels: ã, õ. The tilde must not be dropped or replaced.",
    ],
}


def _resolve_lang_name(lang_code: str) -> str:
    """Return canonical language name for a BCP-47-style code, or the code itself."""
    return _LANGUAGE_NAMES.get(lang_code.lower().split("-")[0], lang_code)


def _target_language_rules(target_lang: str) -> str:
    """Return language-specific orthographic/typographic rules block, or empty string."""
    key = target_lang.lower().split("-")[0]
    rules = _LANGUAGE_RULES.get(key)
    if not rules:
        return ""
    lines = "\n".join(f"- {rule}" for rule in rules)
    lang_name = _LANGUAGE_NAMES.get(key, target_lang)
    return f"Language-specific rules for {lang_name}:\n{lines}\n\n"


@dataclass(frozen=True)
class PromptBuilder:
    """Builds deterministic translation prompts for Ollama /api/chat requests."""

    def build_system_prompt(self, settings: TranslationSettings) -> str:
        """Build the system role message: persona, output rules, language-specific guidance."""
        src_name = _resolve_lang_name(settings.source_lang)
        tgt_name = _resolve_lang_name(settings.target_lang)
        return (
            f"You are a professional book translator from {src_name} to {tgt_name}.\n\n"
            "OUTPUT RULES (follow exactly):\n"
            "- Output ONLY the translated text. Nothing else.\n"
            "- Do NOT add commentary, labels, quotes, explanations, or meta-text.\n"
            "- Do NOT repeat the instructions, context blocks, or source text.\n"
            "- Preserve the meaning, tone, narrative voice, and style of the original.\n"
            "- Keep sentence-ending punctuation (., !, ?, ;, :) when the source uses it.\n"
            "- Do not drop commas or full stops; maintain natural read-aloud rhythm.\n"
            "- Translate proper nouns consistently: use the same rendering for each name "
            "throughout the text.\n\n"
            f"{_target_language_rules(settings.target_lang)}"
        )

    def build_user_prompt(self, request: TranslationRequest) -> str:
        """Build the user role message: context blocks and the text to translate."""
        return (
            f"{self._context_block(request.chapter_context)}"
            f"{self._prior_translations_block(request.prior_translations)}"
            "Translate the following text:\n"
            f"<<<\n{request.text}\n>>>"
        )

    @staticmethod
    def _context_block(chapter_context: str) -> str:
        """Format chapter-level context used only for tone and terminology guidance."""
        if not chapter_context:
            return ""
        return (
            "CHAPTER CONTEXT (for tone/terminology guidance only — "
            "do NOT reproduce this in your response):\n"
            f"<<<\n{chapter_context}\n>>>\n\n"
        )

    @staticmethod
    def _prior_translations_block(prior_translations: str) -> str:
        """Format rolling source→target pairs for terminology continuity."""
        if not prior_translations:
            return ""
        return (
            "RECENT TRANSLATIONS (for terminology continuity only — "
            "do NOT reproduce these in your response):\n"
            f"<<<\n{prior_translations}\n>>>\n\n"
        )


@dataclass(frozen=True)
class GlossaryAwarePromptBuilder:
    """Prompt builder that injects a mandatory term-translation block when glossary is non-empty."""

    def build_system_prompt(self, settings: TranslationSettings) -> str:
        """Delegate to PromptBuilder for the system prompt."""
        return PromptBuilder().build_system_prompt(settings)

    def build_user_prompt(self, request: TranslationRequest) -> str:
        """Build user prompt with optional glossary block prepended."""
        glossary_block = self._glossary_block(request.glossary_terms)
        base = (
            f"{PromptBuilder._context_block(request.chapter_context)}"
            f"{PromptBuilder._prior_translations_block(request.prior_translations)}"
            "Translate the following text:\n"
            f"<<<\n{request.text}\n>>>"
        )
        return f"{glossary_block}{base}"

    @staticmethod
    def _glossary_block(glossary_terms: dict[str, str]) -> str:
        """Format mandatory term-translation block, or empty string when no terms."""
        if not glossary_terms:
            return ""
        lines = "\n".join(f"  {src} -> {tgt}" for src, tgt in glossary_terms.items())
        return f"MANDATORY TERM TRANSLATIONS (always use these exact translations):\n{lines}\n\n"


def _load_toml(fh: IO[bytes]) -> dict[str, Any]:
    """Load TOML from a binary file handle using stdlib tomllib (Python 3.11+)."""
    try:
        import tomllib  # type: ignore[import-not-found]

        return tomllib.load(fh)  # type: ignore[no-any-return]
    except ImportError as exc:
        raise RuntimeError(
            "TOML support requires Python 3.11+ (for stdlib tomllib). "
            "This runtime does not provide it."
        ) from exc


@dataclass(frozen=True)
class TomlGlossaryLoader:
    """Load a glossary from a TOML file with schema [glossary]\\n"term" = "translation"."""

    def load(self, path: Path) -> Glossary:
        """Parse TOML glossary file and return domain Glossary."""
        with open(path, "rb") as fh:
            data = _load_toml(fh)
        glossary_data = data.get("glossary", {})
        if not isinstance(glossary_data, dict):
            glossary_data = {}
        entries = tuple(
            GlossaryEntry(term=str(k), translation=str(v)) for k, v in glossary_data.items()
        )
        return Glossary(entries=entries)


@dataclass(frozen=True)
class JsonGlossaryLoader:
    """Load a glossary from a JSON file with schema {"glossary": {"term": "translation"}}."""

    def load(self, path: Path) -> Glossary:
        """Parse JSON glossary file and return domain Glossary."""
        data = json.loads(path.read_text(encoding="utf-8"))
        glossary_data = data.get("glossary", {}) if isinstance(data, dict) else {}
        if not isinstance(glossary_data, dict):
            glossary_data = {}
        entries = tuple(
            GlossaryEntry(term=str(k), translation=str(v)) for k, v in glossary_data.items()
        )
        return Glossary(entries=entries)
