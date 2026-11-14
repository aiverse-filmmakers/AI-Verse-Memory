"""Meaning search finds memories with no shared words, only when switched on, and never breaks recall."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_meaning_test", ROOT / "scripts" / "memory.py")
mem = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mem)
meaning = sys.modules["_aiverse_memory_meaning_search"]

# A tiny stand in for the model: words that mean the same land on the same axis.
AXES = [{"cinema", "film", "movie", "camera", "footage"}, {"money", "price", "rate", "pounds", "income", "pay"},
        {"gym", "training", "jiu", "jitsu", "fitness"}]


def fake_embed(texts):
    out = []
    for text in texts:
        words = {w.strip(".,").lower() for w in text.split()}
        out.append([float(len(words & axis)) + 0.01 for axis in AXES])
    return out


class MeaningSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "agent-os"
        self.root.mkdir()
        os.environ["AI_VERSE_MEMORY_ROOT"] = str(self.root)
        os.environ["AI_VERSE_MEMORY_HOME"] = str(self.root / ".ai-verse-memory")
        mem.ensure_layout(self.root, mem.MODE_STANDALONE)
        for text in ("My freelance rate is 350 pounds per sponsored post.",
                     "I shoot cinematic footage with a cinema camera.",
                     "I go to jiu jitsu training three times a week."):
            mem.write_atomic(text=text, mem_type="fact", scope="global", source="meaning-test",
                             root=self.root, mode=mem.MODE_STANDALONE)
        mem.rebuild(silent=True, root=self.root, mode=mem.MODE_STANDALONE)
        self.db = mem.ensure_layout(self.root, mem.MODE_STANDALONE)["db"]
        meaning.EMBEDDER = fake_embed

    def tearDown(self):
        meaning.EMBEDDER = None
        os.environ.pop("AI_VERSE_MEMORY_ROOT", None)
        os.environ.pop("AI_VERSE_MEMORY_HOME", None)
        self.tmp.cleanup()

    def texts(self, query):
        return [row["text"] for row in mem.recall(query, scope="global", limit=5, root=self.root, mode=mem.MODE_STANDALONE)]

    def test_off_by_default_so_recall_is_word_only(self):
        self.assertEqual(self.texts("how much do I charge"), [])

    def test_on_finds_a_memory_with_no_shared_words(self):
        meaning.write_config(self.db, True)
        found = self.texts("what is my price and income")
        self.assertTrue(found and "350 pounds" in found[0], found)

    def test_a_broken_model_falls_back_to_word_search(self):
        meaning.write_config(self.db, True)
        meaning.EMBEDDER = lambda texts: (_ for _ in ()).throw(RuntimeError("model crashed"))
        self.assertEqual(self.texts("jiu jitsu"), ["I go to jiu jitsu training three times a week."])

    def test_vectors_are_reused_until_a_memory_changes(self):
        meaning.write_config(self.db, True)
        calls = []
        meaning.EMBEDDER = lambda texts: (calls.append(len(texts)), fake_embed(texts))[1]
        self.texts("camera")
        self.texts("camera")
        self.assertGreaterEqual(calls[0], 3)
        self.assertEqual(calls[1:], [1, 1], "memories embedded once, then only the question")


if __name__ == "__main__":
    unittest.main()
