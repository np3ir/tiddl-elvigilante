from __future__ import annotations
import re
import sys
import unicodedata
from typing import Optional, List, Union

# ============================================================
# Character Conversion Map
# ============================================================
CHAR_TO_FULL_WIDTH = {
    '<': '＜',  # U+FF1C
    '>': '＞',  # U+FF1E
    ':': '：',  # U+FF1A
    '"': '＂',  # U+FF02
    '/': '／',  # U+FF0F
    '\\': '＼',  # U+FF3C
    '|': '｜',  # U+FF5C
    '?': '？',  # U+FF1F
    '*': '＊',  # U+FF0A
}


# ============================================================
# Security & Length Limits
# ============================================================
# DESIGN NOTE:
# Flags for future extensibility (currently constants, could be config-driven):
# STRICT_FS_MODE = True/False  # Force stricter Windows-like rules even on Linux
# ASCII_FALLBACK = True/False  # Force aggressive transliteration to ASCII
# AGGRESSIVE_NORMALIZATION = True/False # Use NFKC instead of NFC (collapses ®, ™, etc.)

MAX_FILENAME_BYTES = 250
MAX_COMPONENT_LEN = 250
RESERVED_BYTE_COUNT = 50

_WIN_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
_DRIVE_RE = re.compile(r"^[A-Za-z]:$")
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)}
}
_RE_NORMALIZE = re.compile(r'[\W_]+')
_NFD = unicodedata.normalize

# ============================================================
# Zalgo Detection
# ============================================================

# Common diacritics that survive NFC precomposition for SOME bases but not others.
# e.g. "o" + U+0308 precomposes to "ö", but "x" + U+0308 stays decomposed.
# After NFC, these are the marks we expect to see legitimately (1 per base max).
_COMMON_DIACRITICS = frozenset([
    0x0300,  # GRAVE
    0x0301,  # ACUTE
    0x0302,  # CIRCUMFLEX
    0x0303,  # TILDE
    0x0304,  # MACRON
    0x0306,  # BREVE
    0x0307,  # DOT ABOVE
    0x0308,  # DIAERESIS
    0x0309,  # HOOK ABOVE (Vietnamese)
    0x030A,  # RING ABOVE
    0x030B,  # DOUBLE ACUTE
    0x030C,  # CARON
    0x030F,  # DOUBLE GRAVE
    0x0311,  # INVERTED BREVE
    0x0323,  # DOT BELOW (Vietnamese, Indic romanization)
    0x0327,  # CEDILLA
    0x0328,  # OGONEK
    0x031B,  # HORN (Vietnamese)
])


# ============================================================
# Script Classification & Stacking Limits
# ============================================================
# Per-character mark limits after NFC normalization.
# - Latin/Greek/Cyrillic: NFC precomposes most, so 2 surviving marks is the max
#   legitimate case (e.g. Vietnamese ệ = e + circumflex + dot below in some NFCs)
# - Thai: tone mark + vowel mark = 2-3 legitimate
# - Hebrew: vowel + cantillation + dagesh = up to 3
# - Arabic: vowel marks (harakat) stack legitimately up to 2-3
# - Devanagari/Indic: nukta + vowel = 2

def _script_of(ch: str) -> str:
    """Classify character into script family for stacking rules."""
    code = ord(ch)
    if code <= 0x024F or (0x1E00 <= code <= 0x1EFF) or (0x2C60 <= code <= 0x2C7F) or (0xA720 <= code <= 0xA7FF):
        return "latin"
    if 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF:
        return "greek"
    if 0x0400 <= code <= 0x052F or 0x2DE0 <= code <= 0x2DFF or 0xA640 <= code <= 0xA69F:
        return "cyrillic"
    if 0x0590 <= code <= 0x05FF or 0xFB1D <= code <= 0xFB4F:
        return "hebrew"
    if 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F or 0x08A0 <= code <= 0x08FF:
        return "arabic"
    if 0x0E00 <= code <= 0x0E7F:
        return "thai"
    if 0x0E80 <= code <= 0x0EFF:
        return "lao"
    if 0x0900 <= code <= 0x097F:
        return "devanagari"
    if 0x0980 <= code <= 0x09FF:
        return "bengali"
    if 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF:
        return "japanese_kana"
    if 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F or 0xAC00 <= code <= 0xD7AF:
        return "korean"
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
        return "cjk"
    return "other"


# Max combining marks allowed per base character, per script (after NFC)
_SCRIPT_MARK_LIMITS = {
    "latin": 2,  # Vietnamese ệ edge case
    "greek": 2,  # polytonic Greek: ᾧ
    "cyrillic": 1,  # very few combining marks post-NFC
    "hebrew": 3,  # vowel + cantillation + dagesh
    "arabic": 3,  # harakat stacking
    "thai": 3,  # tone + vowel + special
    "lao": 3,  # similar to Thai
    "devanagari": 2,  # nukta + vowel sign
    "bengali": 2,
    "japanese_kana": 1,  # dakuten/handakuten (usually precomposed)
    "korean": 0,  # Hangul shouldn't have combining marks
    "cjk": 0,  # CJK shouldn't have combining marks
    "other": 2,  # conservative default
}


# ============================================================
# Core: remove_zalgo v2
# ============================================================

def remove_zalgo(text: str) -> str:
    """
    Remove Zalgo/stacked combining marks while preserving legitimate diacritics.

    Strategy (3-layer):
      1. NFC normalization — precomposes what Unicode defines as canonical
      2. Per-character stacking enforcement — limits marks per base using script-aware rules
      3. Emergency global strip — if density is still extreme after per-char limits

    Key insight from Zalgo-1.0 analysis: Zalgo generators use the SAME codepoints
    as legitimate diacritics. The difference is purely in quantity (stacking).
    You cannot distinguish them by codepoint — only by count per base character.
    """
    if not text:
        return ""

    # Layer 1: NFC normalization
    # This precomposes most Latin diacritics (é, ñ, ü, etc.) into single codepoints,
    # making them immune to the combining mark counter.
    # DESIGN NOTE: NFC chosen deliberately to preserve artistic intent.
    # Do NOT switch to NFKC unless explicitly desired (NFKC collapses ™ -> TM, etc.)
    s = unicodedata.normalize("NFC", str(text))

    if not s:
        return ""

    # Layer 2: Per-character stacking enforcement
    out = []
    current_script = "other"
    mark_count = 0  # marks accumulated on current base
    mark_limit = 2  # limit for current base's script
    seen_base = False  # Track if we've seen a base char yet

    for ch in s:
        cat = unicodedata.category(ch)

        if cat.startswith("M"):
            # If we haven't seen a base character yet, drop the mark
            # This prevents files starting with combining marks (Windows/SMB issue)
            if not seen_base:
                continue

            # This is a combining mark
            mark_count += 1
            cp = ord(ch)

            if mark_count <= mark_limit:
                # Within budget — allow the mark
                # But for Latin/Greek/Cyrillic, only allow common diacritics
                # (exotic marks like COMBINING ZIGZAG ABOVE are almost certainly noise)
                if current_script in ("latin", "greek", "cyrillic"):
                    if cp in _COMMON_DIACRITICS:
                        out.append(ch)
                    # else: silently drop exotic mark on Latin base
                else:
                    # Non-Latin scripts: allow any mark within the limit
                    out.append(ch)
            # else: over budget, drop

        else:
            # Base character — reset counter, determine script
            seen_base = True
            out.append(ch)
            current_script = _script_of(ch)
            mark_limit = _SCRIPT_MARK_LIMITS.get(current_script, 2)
            mark_count = 0

    result = "".join(out)

    # Layer 3: Emergency global check
    # If after per-char limiting we STILL have extreme density, something is wrong.
    # This catches edge cases like very short strings that are mostly marks.
    total = len(result)
    if total > 0:
        remaining_marks = sum(1 for c in result if unicodedata.category(c).startswith("M"))
        if total <= 4 and remaining_marks > total * 0.5:
            # Very short string that's mostly marks — strip all
            result = "".join(c for c in result if not unicodedata.category(c).startswith("M"))

    return unicodedata.normalize("NFC", result)


# ============================================================
# Transliteration Map
# ============================================================
TRANSLITERATION_MODE = "smart"

UNICODE_TO_ASCII_MAP = {
    '★': '*', '☆': '*', '✪': '*', '✯': '*', '✭': '*',
    '→': '->', '←': '<-', '↔': '<->', '⇒': '=>', '⇐': '<=',
    '・': '.', '。': '.', '•': '.', '●': '.', '○': '.',
    '♥': '<3', '♡': '<3', '❤': '<3',
    '（': '(', '）': ')', '【': '[', '】': ']', '「': '"', '」': '"',
    '『': '"', '』': '"', '〈': '<', '〉': '>', '《': '<<', '》': '>>',
    '～': '~', '–': '-', '—': '-', '―': '-',
    '×': 'x', '÷': '/', '＋': '+', '＝': '=',
    '＆': '&', '＠': '@', '＃': '#', '＄': '$', '％': '%',
    '\u3000': ' ',
}


# ============================================================
# Core String Functions (unchanged from v1 where not affected)
# ============================================================

def is_unicode_safe(ch: str) -> bool:
    """
    Check if a character is safe for filenames.

    Blacklist approach: block known-bad Unicode categories, allow everything else.
    Modern filesystems (ext4, NTFS, APFS, Btrfs) support UTF-8/UTF-16 natively.
    The old whitelist approach blocked legitimate scripts (Tibetan, Tamil, Lao,
    Bengali, etc.) causing artist names like ⣎⡇ꉺლ༽இ•̛)ྀ◞ to be destroyed.
    """
    cat = unicodedata.category(ch)
    # Block: Unassigned (Cn), Control (Cc), Surrogates (Cs), Private Use (Co)
    if cat in ("Cn", "Cc", "Cs", "Co"):
        return False
    # Format chars (Cf): block most, allow a few commonly used ones
    if cat == "Cf":
        cp = ord(ch)
        return cp in (0x200C, 0x200D, 0xFEFF)  # ZWNJ, ZWJ, BOM
    return True

def transliterate_unicode(text: str, mode: str = 'smart') -> str:
    if mode == 'preserve':
        for old, new in UNICODE_TO_ASCII_MAP.items():
            text = text.replace(old, new)
        return text
    elif mode == 'aggressive':
        try:
            from unidecode import unidecode
            return unidecode(text)
        except ImportError:
            text = unicodedata.normalize('NFKD', text)
            return text.encode('ascii', 'ignore').decode('ascii')
    else:  # smart
        encoding = sys.getfilesystemencoding() or 'utf-8'
        result = []
        for ch in text:
            if ch in UNICODE_TO_ASCII_MAP:
                result.append(UNICODE_TO_ASCII_MAP[ch])
            elif 0x20 <= ord(ch) <= 0x7E:
                result.append(ch)
            elif is_unicode_safe(ch):
                # Preserve if the filesystem can encode it
                try:
                    ch.encode(encoding)
                    result.append(ch)
                except UnicodeEncodeError:
                    # Can't encode on this FS → decompose to ASCII fallback
                    decomposed = unicodedata.normalize('NFKD', ch)
                    ascii_part = ''.join(c for c in decomposed if ord(c) < 128)
                    result.append(ascii_part if ascii_part else '_')
            else:
                decomposed = unicodedata.normalize('NFKD', ch)
                ascii_part = ''.join(c for c in decomposed if ord(c) < 128)
                if ascii_part:
                    result.append(ascii_part)
                else:
                    result.append('_')
        return ''.join(result)

def normalize_text(text: str) -> str:
    if not text:
        return ""
    return _RE_NORMALIZE.sub("", text).lower()


def _truncate(s: str, max_len: int) -> str:
    if not isinstance(s, str):
        s = str(s)
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[:max_len]


def truncate_str_bytes(text: str, max_bytes: int = 240) -> str:
    b = str(text).encode("utf-8")
    if len(b) <= max_bytes:
        return text
    decoded = b[:max_bytes].decode("utf-8", errors="ignore")
    return decoded


def get_alpha_bucket(name: str) -> str:
    if not name:
        return "#"
    s = remove_zalgo(str(name).strip())
    if not s:
        return "#"
    ch = s[0].upper()
    decomposed = unicodedata.normalize("NFD", ch)
    base = "".join(c for c in decomposed if unicodedata.category(c) != "Mn").upper()
    return base if ("A" <= base <= "Z") else "#"


def extract_readable_parts(text: str, min_length: int = 2) -> list:
    if not text:
        return []
    parts = re.findall(r'[a-zA-Z0-9]+', text)
    parts = [p for p in parts if len(p) >= min_length]
    return parts


def _generate_fallback_name(original: Union[str, None] = None, item_id: Union[int, None] = None) -> str:
    if original:
        ascii_parts = extract_readable_parts(original, min_length=2)
        if ascii_parts:
            ascii_parts = sorted(ascii_parts, key=len, reverse=True)[:3]
            readable = '_'.join(ascii_parts)
            if len(readable) > 50:
                readable = readable[:50]
            if item_id:
                return f"{readable}_{item_id}"
            return readable
    if item_id:
        return f"Item_{item_id}"
    return "Unknown"


def sanitize_filename(s: str, item_id: Optional[int] = None, max_len: int = 100, reserve_bytes: int = 0) -> str:
    if not s or not s.strip():
        return _generate_fallback_name(None, item_id)

    original_input = s
    s = remove_zalgo(s)
    s = transliterate_unicode(s, mode=TRANSLITERATION_MODE)
    s = unicodedata.normalize("NFC", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf", "Cs"))

    # 1. Main rule: Convert forbidden characters to their full-width counterparts.
    for char, full_width in CHAR_TO_FULL_WIDTH.items():
        s = s.replace(char, full_width)

    # 2. Post-cleanup: Consolidate whitespace and other cosmetic fixes.
    s = re.sub(r'\s+', ' ', s)  # Collapse multiple spaces into one
    s = re.sub(r'_+', '_', s)    # Collapse multiple underscores
    s = re.sub(r'\.+', '.', s)    # Collapse multiple dots

    # 3. Strip problematic characters ONLY from the very end, as per Windows rules.
    # We do NOT strip from the start, to preserve names like '.Flakes'.
    s = s.rstrip('. ')

    total_chars = len(s) if s else 0
    if s == "#":
        return s
    if total_chars == 0:
        return _generate_fallback_name(original_input, item_id)

    if total_chars > 3:
        # "Meaningful content" check — catch strings that are entirely junk
        # Improved: check for alphanumeric content ratio
        alnum_count = sum(1 for c in s if c.isalnum())
        ratio = alnum_count / total_chars
        if ratio < 0.15:  # Threshold for "mostly symbols"
            return _generate_fallback_name(original_input, item_id)

        # Long decorative guard: if the string is large but has NO readable
        # ASCII/Latin content at all, it may cause SMB/CIFS issues.
        # Fallback to Item_<id> with readable excerpt if available.
        if len(s.encode("utf-8")) > 60 and not extract_readable_parts(s, min_length=2):
            return _generate_fallback_name(original_input, item_id)

    base_name = s.upper().split('.')[0].strip()
    if base_name in _RESERVED_NAMES:
        s = f"_{s}"

    try:
        encoding = sys.getfilesystemencoding() or "utf-8"
        s.encode(encoding, errors='strict')
    except (UnicodeEncodeError, Exception):
        fallback_replacements = {
            "/": "-", "\\": "-",
            ":": "-", "*": "x",
            "?": "", '"': "'",
            "<": "(", ">": ")",
            "|": "-"
        }
        for char, repl in fallback_replacements.items():
            s = s.replace(char, repl)
        s = _WIN_FORBIDDEN_RE.sub("_", s)
    
    # Apply byte reserve for downloader suffixes (.flac.part.<hash>)
    # Folders should pass reserve_bytes=0, filenames should pass reserve_bytes=50
    effective_max = max(max_len - reserve_bytes, 20)
    return truncate_str_bytes(s, effective_max)
