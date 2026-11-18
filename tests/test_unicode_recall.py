import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_unicode_test", ROOT / "scripts" / "memory.py")
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)


class TokenizerTests(unittest.TestCase):
    def test_english_tokens_are_unchanged(self):
        self.assertEqual(
            mem.tokenize("Ship the Aurora release, whisper-compatible v2 a I_O"),
            ["ship", "the", "aurora", "release", "whisper-compatible", "v2", "i_o"],
        )

    def test_romanian_words_stay_whole(self):
        tokens = mem.tokenize("Locuiesc în București și lucrez la o școală din Brașov, într-un oraș frumos.")
        self.assertIn("bucuresti", tokens)
        self.assertIn("si", tokens)
        self.assertIn("scoala", tokens)
        self.assertIn("brasov", tokens)
        self.assertNotIn("ucure", tokens)

    def test_comma_and_cedilla_forms_match(self):
        self.assertEqual(mem.tokenize("Brașov"), mem.tokenize("Braşov"))
        self.assertEqual(mem.tokenize("ț"), mem.tokenize("ţ"))

    def test_non_latin_text_is_tokenized(self):
        self.assertEqual(mem.tokenize("привет мир"), ["привет", "мир"])


class RomanianRecallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "agent-os"
        self.root.mkdir()
        os.environ["AI_VERSE_MEMORY_ROOT"] = str(self.root)
        os.environ["AI_VERSE_MEMORY_HOME"] = str(self.root / ".ai-verse-memory")
        mem.ensure_layout(self.root, mem.MODE_STANDALONE)
        mem.rebuild(silent=True, root=self.root, mode=mem.MODE_STANDALONE)

    def tearDown(self):
        os.environ.pop("AI_VERSE_MEMORY_ROOT", None)
        os.environ.pop("AI_VERSE_MEMORY_HOME", None)
        self.tmp.cleanup()

    def _remember(self, text):
        mem_id, _, _ = mem.write_atomic(
            text=text,
            mem_type="fact",
            scope="global",
            source="unicode-test",
            root=self.root,
            mode=mem.MODE_STANDALONE,
            force=True,
        )
        return mem_id

    def _ids(self, query):
        rows = mem.recall(query, limit=8, root=self.root, mode=mem.MODE_STANDALONE)
        return {row["id"] for row in rows}

    def test_romanian_sentence_is_found_with_and_without_accents(self):
        target = self._remember("Echipa se întâlnește în București, iar șeful de proiect locuiește în Brașov.")
        self._remember("Unrelated English note about shipping the release.")
        for query in ("București", "bucuresti", "BUCUREȘTI", "șeful de proiect", "seful proiect", "Brașov"):
            with self.subTest(query=query):
                self.assertIn(target, self._ids(query))

    def test_romanian_query_does_not_return_unrelated_memory(self):
        self._remember("Echipa se întâlnește în București.")
        other = self._remember("Unrelated English note about shipping the release.")
        self.assertNotIn(other, self._ids("întâlnește București"))


if __name__ == "__main__":
    unittest.main()
