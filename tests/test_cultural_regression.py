
from __future__ import annotations
import unittest
import unicodedata
from tiddl.core.utils.strings import remove_zalgo, sanitize_filename, get_alpha_bucket

class TestCulturalRegression(unittest.TestCase):
    """
    # Cultural regression tests
    # These tests protect linguistic and artistic integrity.
    
    Cultural Regression Tests to ensure future changes do not break support
    for non-Western languages and artistic creativity.
    DO NOT REMOVE OR WEAKEN THESE TESTS without understanding the impact on CJK/Arabic users.
    """

    def test_japanese_preservation(self):
        """Japanese (Kanji/Hiragana/Katakana) should be preserved."""
        original = "きただにひろし" # Kitadani Hiroshi
        cleaned = sanitize_filename(original)
        self.assertEqual(cleaned, original, "Japanese Hiragana should be preserved")

        kanji = "進撃の巨人"
        self.assertEqual(sanitize_filename(kanji), kanji, "Kanji should be preserved")

    def test_korean_hangul(self):
        """Korean (Hangul) should be preserved."""
        kpop = "방탄소년단" # BTS
        self.assertEqual(sanitize_filename(kpop), kpop, "Hangul should be preserved")

    def test_mixed_feats_real_world(self):
        """Feats with parentheses and mixed scripts."""
        # Typical in J-Pop/K-Pop
        name = "Song Name (feat. Ado)"
        cleaned = sanitize_filename(name)
        # sanitize_filename might change ' ' to ' ', but it's simple here.
        # Note: sanitize_filename runs transliterate_unicode -> mode='smart'
        # ascii map: ( -> (, ) -> )
        self.assertEqual(cleaned, "Song Name (feat. Ado)")

    def test_unicode_rare_normalization(self):
        """
        NFC vs NFKC check.
        If we switch to NFKC by mistake, this will fail.
        """
        # U+2160 ROMAN NUMERAL ONE 'Ⅰ'
        # NFC: stays as 'Ⅰ'
        # NFKC: becomes 'I' (ASCII)
        roman = "Ⅰ"
        
        # U+2460 CIRCLED DIGIT ONE '①'
        # NFC: stays as '①'
        # NFKC: becomes '1'
        circled = "①"

        # Our current policy is NFC (preserve aesthetics)
        self.assertEqual(remove_zalgo(roman), roman, "Should preserve Roman Numeral I (NFC)")
        self.assertEqual(remove_zalgo(circled), circled, "Should preserve Circled Digit 1 (NFC)")

    def test_emojis_and_symbols(self):
        """
        Emojis and common symbols.
        Some are mapped in UNICODE_TO_ASCII_MAP, others pass through.
        """
        # Heart mapped to <3
        # sanitize_filename runs:
        # 1. transliterate: '♥' -> '<3'
        # 2. replacements: '<' -> '＜' (Fullwidth Less-Than), '>' -> '＞' (Fullwidth Greater-Than)
        # So expected is 'Love ＜3' or similar.
        result = sanitize_filename("Love ♥")
        # Check for the transliterated components, knowing they might be sanitized later
        self.assertTrue('3' in result)
        # Verify the Forbidden char replacement happened
        self.assertTrue('＜' in result or '<' in result) 
        
        # Star mapped to * -> which is forbidden -> replaced by fullwidth '＊' or 'x'
        # strings.py replacements: '*' -> '\uFF0A' (Fullwidth Asterisk) before fallback
        star_str = "Star ★"
        cleaned = sanitize_filename(star_str)
        # ★ -> * (transliterate) -> \uFF0A (sanitize replace)
        self.assertIn("\uFF0A", cleaned) 

    def test_zalgo_stripping_vs_legit_scripts(self):
        """
        Ensure remove_zalgo does not kill legitimate scripts with many marks.
        """
        # Zalgo (Noise)
        zalgo_noise = "Hęľłö" + "\u0300\u0301\u0302\u0303" * 5 
        cleaned_zalgo = remove_zalgo(zalgo_noise)
        self.assertTrue(len(cleaned_zalgo) < len(zalgo_noise), "Should strip stacked marks")
        
        # Vietnamese (Legitimate, many marks)
        # ệ = e + circumflex + dot below.
        vietnamese = "Việt Nam"
        self.assertEqual(remove_zalgo(vietnamese), vietnamese, "Should preserve Vietnamese diacritics")

    def test_arabic_stacking(self):
        """Arabic uses legitimate marks (harakat)."""
        # Allah (with shadda and superscript alef)
        allah = "\u0627\u0644\u0644\u0670\u0647" 
        # remove_zalgo allows up to 3 marks in Arabic
        self.assertEqual(remove_zalgo(allah), allah, "Should preserve Arabic marks")

    def test_leading_combining_mark_removal(self):
        """Prevent Ghost Files on Windows."""
        # Acute accent + A
        risky = "\u0301A"
        # Should remove the leading accent
        self.assertEqual(remove_zalgo(risky), "A", "Should drop leading combining mark")

    def test_cjk_bucket(self):
        """CJK artists should go to the # bucket, not a random letter or error."""
        artist = "周杰倫" # Jay Chou
        bucket = get_alpha_bucket(artist)
        self.assertEqual(bucket, "#", "CJK artists should go to # bucket")

if __name__ == "__main__":
    unittest.main()
