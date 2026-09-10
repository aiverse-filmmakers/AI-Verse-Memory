import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_semantic_test", ROOT / "scripts" / "memory.py")
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)


class SemanticRecallCandidateTests(unittest.TestCase):
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

    def test_long_semantic_query_keeps_late_task_signals_in_fts_candidates(self):
        target_id, _, _ = mem.write_atomic(
            text="Aurora whisper transcode dialogue delivery sentinel",
            mem_type="experience",
            scope="project:aurora",
            source="brain-style-query-regression",
            root=self.root,
            mode=mem.MODE_STANDALONE,
        )

        # These records deliberately match the generic prefix that comes before
        # the real task signals in Brain retrieval queries. Under the old
        # first-12-token FTS behavior, only these decoys could become candidates.
        for index in range(4):
            mem.write_atomic(
                text=f"prior facts decisions outcomes attempts constraints lessons generic decoy {index}",
                mem_type="fact",
                scope="project:aurora",
                source="brain-style-query-regression",
                root=self.root,
                mode=mem.MODE_STANDALONE,
                force=True,
            )

        query = (
            "Recall prior facts, decisions, outcomes, attempts, constraints, and lessons relevant to "
            "gaps between current state and confirmed goals, including blockers, constraints, prior attempts, "
            "decisions, and outcomes. Signals: Aurora release is preparing for delivery. The next task is "
            "dialogue transcription and transcode validation using Whisper-compatible tooling. Ship the Aurora "
            "release after whisper dialogue transcription and transcode validation."
        )

        terms = mem._fts_query_terms(query)
        self.assertLessEqual(len(terms), mem._MAX_FTS_QUERY_TERMS)
        self.assertIn("aurora", terms)
        self.assertIn("whisper-compatible", terms)
        self.assertIn("transcode", terms)

        rows = mem.recall(
            query,
            scope="project:aurora",
            limit=8,
            root=self.root,
            mode=mem.MODE_STANDALONE,
        )
        self.assertIn(target_id, {row["id"] for row in rows})

    def test_fts_term_selection_is_unique_and_bounded(self):
        query = " ".join(["repeat"] * 30 + [f"signal-{index}" for index in range(100)])
        terms = mem._fts_query_terms(query)
        self.assertEqual(terms[0], "repeat")
        self.assertEqual(len(terms), mem._MAX_FTS_QUERY_TERMS)
        self.assertEqual(len(terms), len(set(terms)))


if __name__ == "__main__":
    unittest.main()
