# Design Constraints & Architecture Decisions

This document outlines the critical design choices that safeguard the application's stability and cultural neutrality. 

> **⚠️ WARNING FOR MAINTAINERS**
> Do not modify these behaviors without understanding the full implications for international users (CJK, Arabic, Vietnamese) and Windows filesystem quirks.

## 1. Critical Invariants (Must Never Break)

*   **Cultural Preservation**: We prioritize keeping original scripts (Kanji, Hangul, Arabic) over "readability" for English speakers. `remove_zalgo` must **NOT** strip valid diacritics (e.g., Vietnamese tones, French accents).
*   **Windows Path Safety**:
    *   **Ghost Files**: Files must never start with a combining mark. The logic `seen_base` in `remove_zalgo` prevents this.
    *   **Length Limits**: Paths > 260 chars must be handled via `\\?\` prefix.
    *   **Reserved Names**: Filenames like `CON`, `PRN`, `AUX` must be escaped (e.g., `_CON`).
*   **Byte-Level Precision**: Truncation logic (`truncate_filepath_to_max`) **MUST** operate on UTF-8 bytes, not characters.
    *   *Why*: In CJK, 1 character = 3 bytes. A 255-char string is 765 bytes, causing `File name too long` crashes if not truncated by bytes.

## 2. Deliberate Design Decisions

### Unicode Normalization: NFC vs NFKC
*   **Decision**: We use **NFC** (Canonical Decomposition, followed by Canonical Composition).
*   **Why**: We preserve artistic intent. `NFKC` aggressively normalizes compatibility characters:
    *   `™` → `TM`
    *   `①` → `1`
    *   `x²` → `x2`
    *   `ﬁ` → `fi`
    This alteration is undesirable for music metadata where styling matters.
*   **Constraint**: Do not switch to `NFKC` globally.

### Zalgo Removal Strategy
*   **Decision**: We use a **3-layer approach** (NFC → Script-aware Limits → Emergency Strip).
*   **Why**: 
    *   Pure "strip all marks" destroys Vietnamese and Arabic.
    *   Pure "allow all" breaks Windows with Zalgo titles.
*   **Constraint**: The "Script-aware limit" (e.g., Latin=2 marks, Arabic=3 marks) is the only robust way to balance these conflicting goals.

### Fallback Logic
*   **Decision**: If a name has < 15% alphanumeric content ("symbol soup"), we fallback to `Item_<ID>`.
*   **Why**: Filesystems and shells struggle with names like `.......` or `___`. We need a guaranteed safe, sortable filename.

## 3. Flags & Defaults (By Design)

*   **ASCII_FALLBACK**: Default is `False`.
    *   *Why*: We do not force transliteration to ASCII unless the filesystem encoding physically fails. We respect the user's language.
*   **STRICT_FS_MODE**: Default is `False`.
    *   *Why*: We apply Windows restrictions to sanitization (to ensure portability), but we do not enforce strict ASCII compliance.

## 4. Testing
*   **Cultural Regression Tests**: `tests/test_cultural_regression.py` protects these constraints. 
*   **Requirement**: Run these tests before any changes to `strings.py`.
