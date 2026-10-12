import unittest
from linkmusicbot.text_encoding import repair_text
from linkmusicbot.security import normalize_query


class EncodingTests(unittest.TestCase):
    def test_non_ascii_music_names_survive_correct_and_broken_encoding(self):
        for text in ["Miraaž STEFAN", "Beyoncé Déjà Vu", "Björk Jóga", "Sigur Rós Svefn-g-englar",
                     "Stromae Papaoutai", "Zoë Keating", "MØ", "Françoise Hardy", "Снежа Я не вернусь",
                     "快眠!安眠!スヤリスト生活", "🎵 Miraaž"]:
            with self.subTest(text=text):
                self.assertEqual(repair_text(text), text)
                self.assertEqual(repair_text(text.encode("utf8").decode("latin1")), text)
                try:
                    broken = text.encode("utf8").decode("cp1252")
                except UnicodeDecodeError:
                    continue
                self.assertEqual(repair_text(broken), text)

    def test_mixed_alphabets_and_double_encoding(self):
        self.assertEqual(repair_text("MiraaÅ¾ Снежа"), "Miraaž Снежа")
        original = "Miraaž"
        broken = original.encode("utf8").decode("latin1").encode("utf8").decode("latin1")
        self.assertEqual(repair_text(broken), original)

    def test_valid_accented_words_are_not_rewritten(self):
        for text in ["Âme", "Åse", "François", "Beyoncé", "Æther", "São Paulo", "ð"]:
            self.assertEqual(repair_text(text), text)

    def test_broken_utf8_query_is_repaired_before_casefold(self):
        self.assertEqual(normalize_query("MiraaÅ¾ Stefan"), "miraaž stefan")

    def test_valid_artist_names_are_preserved(self):
        for value in ["Åse", "Miraaž", "Снежа", "快眠!安眠!スヤリスト生活"]:
            self.assertEqual(repair_text(value), value)

    def test_russian_mojibake_is_reversible(self):
        text = "Она не твоя"
        self.assertEqual(repair_text(text.encode("utf8").decode("latin1")), text)
