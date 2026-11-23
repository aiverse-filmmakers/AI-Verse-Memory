import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_safe_locks_tests", ROOT / "scripts" / "memory.py")
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)
PB = mem._public_beta

INSTALL_SPEC = importlib.util.spec_from_file_location("ai_verse_memory_safe_locks_install", ROOT / "scripts" / "install_engine.py")
install = importlib.util.module_from_spec(INSTALL_SPEC)
assert INSTALL_SPEC.loader is not None
INSTALL_SPEC.loader.exec_module(install)

DEAD_PID = 999999999

WORKER = r"""
import importlib.util, os, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("m", sys.argv[1])
mem = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mem)
root = Path(sys.argv[2])
counter = Path(sys.argv[3])
inside = Path(sys.argv[4])
rounds = int(sys.argv[5])
bad = 0
for _ in range(rounds):
    with mem.public_beta_mutation_lock(root, mem.MODE_STANDALONE):
        try:
            fd = os.open(str(inside), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            os.close(fd)
        except FileExistsError:
            bad += 1
        value = int(counter.read_text(encoding="utf-8") or "0")
        time.sleep(0.005)
        counter.write_text(str(value + 1), encoding="utf-8")
        try:
            inside.unlink()
        except FileNotFoundError:
            bad += 1
print("overlap" if bad else "ok")
"""


def write_lock(path, pid, token="legacy", age_seconds=0):
    path.write_text(json.dumps({"pid": pid, "token": token}) + "\n", encoding="utf-8")
    if age_seconds:
        when = time.time() - age_seconds
        os.utime(path, (when, when))


def flaky_unlink(target, failures):
    """Path.unlink replacement that fails with PermissionError a set number of times for one file."""
    real_unlink = Path.unlink
    state = {"left": failures, "calls": 0}

    def unlink(path, *args, **kwargs):
        if Path(path) == target:
            state["calls"] += 1
            if state["left"] > 0:
                state["left"] -= 1
                raise PermissionError("file in use")
        return real_unlink(path, *args, **kwargs)

    return unlink, state


class MutationLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "agent"
        self.root.mkdir()
        mem.ensure_layout(self.root, mem.MODE_STANDALONE)
        self.state = PB._state_dir(mem._engine, self.root, mem.MODE_STANDALONE)
        self.lock = self.state / "mutation.lock"
        self.guard = self.state / "mutation.lock.clearing"

    def test_each_hold_carries_its_own_unique_token(self):
        tokens = []
        for _ in range(3):
            with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
                payload = json.loads(self.lock.read_text(encoding="utf-8"))
                self.assertEqual(payload["pid"], os.getpid())
                tokens.append(payload["token"])
            self.assertFalse(self.lock.exists())
        self.assertEqual(len(set(tokens)), 3)
        self.assertTrue(all(len(token) >= 32 for token in tokens))

    def test_release_never_deletes_a_lock_owned_by_someone_else(self):
        with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
            self.lock.unlink()
            write_lock(self.lock, os.getpid(), token="someone-else")
        self.assertTrue(self.lock.exists())
        self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["token"], "someone-else")

    def test_release_leaves_a_lock_that_was_already_removed(self):
        with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
            self.lock.unlink()
        self.assertFalse(self.lock.exists())

    def test_stale_lock_is_cleared_and_no_guard_is_left_behind(self):
        write_lock(self.lock, DEAD_PID, age_seconds=PB.LOCK_DEAD_PROCESS_GRACE_SECONDS + 5)
        with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
            self.assertNotEqual(json.loads(self.lock.read_text(encoding="utf-8"))["token"], "legacy")
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.guard.exists())

    def test_clear_leaves_a_lock_that_changed_after_it_was_judged_stale(self):
        write_lock(self.lock, DEAD_PID, token="old", age_seconds=3600)
        observed = PB._lock_identity(self.lock)
        # The old owner is cleared by someone else and a live owner takes over.
        self.lock.unlink()
        write_lock(self.lock, os.getpid(), token="fresh-live-owner")
        self.assertEqual(PB._clear_stale_lock(self.lock, observed), "fresh")
        self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["token"], "fresh-live-owner")
        self.assertFalse(self.guard.exists())

    def test_clear_rechecks_staleness_under_the_guard(self):
        write_lock(self.lock, os.getpid(), token="alive", age_seconds=3600)
        observed = PB._lock_identity(self.lock)
        self.assertEqual(PB._clear_stale_lock(self.lock, observed), "fresh")
        self.assertTrue(self.lock.exists())

    def test_clear_reports_gone_when_the_lock_vanished(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        observed = PB._lock_identity(self.lock)
        self.lock.unlink()
        self.assertEqual(PB._clear_stale_lock(self.lock, observed), "gone")

    def test_only_one_waiter_clears_at_a_time(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        observed = PB._lock_identity(self.lock)
        write_lock(self.guard, os.getpid(), token="other-waiter")
        self.assertEqual(PB._clear_stale_lock(self.lock, observed), "busy")
        self.assertTrue(self.lock.exists())
        # A busy guard is not removed by the loser.
        self.assertEqual(json.loads(self.guard.read_text(encoding="utf-8"))["token"], "other-waiter")

    def test_guard_left_by_a_crashed_waiter_is_taken_over(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        observed = PB._lock_identity(self.lock)
        write_lock(self.guard, DEAD_PID, token="crashed", age_seconds=PB.LOCK_GUARD_STALE_SECONDS + 5)
        self.assertEqual(PB._clear_stale_lock(self.lock, observed), "cleared")
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.guard.exists())

    def test_young_guard_of_a_dead_pid_is_still_respected(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        observed = PB._lock_identity(self.lock)
        write_lock(self.guard, DEAD_PID, token="just-now")
        self.assertEqual(PB._clear_stale_lock(self.lock, observed), "busy")

    def test_stale_lock_that_cannot_be_removed_fails_instead_of_looping(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        real_unlink = Path.unlink

        def refuse(path, *args, **kwargs):
            if Path(path) == self.lock:
                raise PermissionError("not allowed")
            return real_unlink(path, *args, **kwargs)

        original_wait = PB.LOCK_WAIT_SECONDS
        PB.LOCK_WAIT_SECONDS = 30
        started = time.monotonic()
        try:
            with mock.patch.object(Path, "unlink", refuse):
                with self.assertRaises(RuntimeError) as caught:
                    with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
                        pass
        finally:
            PB.LOCK_WAIT_SECONDS = original_wait
        self.assertIn("Could not clear stale", str(caught.exception))
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertFalse(self.guard.exists())

    def test_release_retries_when_the_file_is_briefly_in_use(self):
        unlink, state = flaky_unlink(self.lock, 2)
        with mock.patch.object(PB, "LOCK_UNLINK_PAUSE_SECONDS", 0.001):
            with mock.patch.object(Path, "unlink", unlink):
                with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
                    pass
        self.assertFalse(self.lock.exists())
        self.assertEqual(state["calls"], 3)

    def test_release_failure_never_masks_the_real_error(self):
        unlink, _ = flaky_unlink(self.lock, 1000)
        with mock.patch.object(PB, "LOCK_UNLINK_PAUSE_SECONDS", 0.001):
            with mock.patch.object(Path, "unlink", unlink):
                with self.assertRaises(ValueError):
                    with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
                        raise ValueError("the real error")
        self.assertTrue(self.lock.exists())

    def test_clearing_retries_a_busy_stale_lock_before_giving_up(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        observed = PB._lock_identity(self.lock)
        unlink, state = flaky_unlink(self.lock, 2)
        with mock.patch.object(PB, "LOCK_UNLINK_PAUSE_SECONDS", 0.001):
            with mock.patch.object(Path, "unlink", unlink):
                self.assertEqual(PB._clear_stale_lock(self.lock, observed), "cleared")
        self.assertEqual(state["calls"], 3)
        self.assertFalse(self.lock.exists())

    def test_live_holder_is_waited_for_not_cleared(self):
        write_lock(self.lock, os.getpid(), token="live", age_seconds=3600)
        original_wait = PB.LOCK_WAIT_SECONDS
        PB.LOCK_WAIT_SECONDS = 0.3
        try:
            with self.assertRaises(RuntimeError) as caught:
                with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
                    pass
        finally:
            PB.LOCK_WAIT_SECONDS = original_wait
        self.assertIn("Timed out", str(caught.exception))
        self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["token"], "live")

    def _run_workers(self, count, rounds):
        counter = self.state / "counter.txt"
        counter.write_text("0", encoding="utf-8")
        inside = self.state / "inside.marker"
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", WORKER, str(ROOT / "scripts" / "memory.py"), str(self.root),
                 str(counter), str(inside), str(rounds)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            for _ in range(count)
        ]
        outputs = [proc.communicate(timeout=120) for proc in procs]
        for proc, (out, err) in zip(procs, outputs):
            self.assertEqual(proc.returncode, 0, err)
            self.assertEqual(out.strip(), "ok", err)
        return int(counter.read_text(encoding="utf-8"))

    def test_competing_processes_never_overlap_and_lose_no_updates(self):
        self.assertEqual(self._run_workers(6, 15), 90)
        self.assertFalse(self.lock.exists())

    def test_competing_processes_with_a_stale_lock_never_overlap(self):
        # Several real processes all find the same dead owner at once and race
        # to clear it. Exactly one holds the lock at any moment afterwards.
        write_lock(self.lock, DEAD_PID, age_seconds=PB.LOCK_DEAD_PROCESS_GRACE_SECONDS + 5)
        self.assertEqual(self._run_workers(8, 10), 80)
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.guard.exists())

    def test_repeated_stale_races_never_overlap(self):
        for _ in range(3):
            write_lock(self.lock, DEAD_PID, age_seconds=PB.LOCK_DEAD_PROCESS_GRACE_SECONDS + 5)
            self.assertEqual(self._run_workers(6, 4) % 24, 0)

    def test_threads_share_one_hold_and_stay_serialized(self):
        active = []
        overlap = []

        def work():
            with mem.public_beta_mutation_lock(self.root, mem.MODE_STANDALONE):
                active.append(1)
                if len(active) > 1:
                    overlap.append(1)
                time.sleep(0.01)
                active.pop()

        threads = [threading.Thread(target=work) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(overlap, [])


class RegistryLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.target = Path(self._tmp.name)
        self.extensions = install._ensure_extension_dir(self.target)
        self.lock = self.extensions / "registry.json.lock"
        self.guard = self.extensions / "registry.json.lock.clearing"

    def test_lock_has_unique_token_and_is_removed_on_release(self):
        tokens = []
        for _ in range(2):
            with install._registry_lock(self.target):
                tokens.append(json.loads(self.lock.read_text(encoding="utf-8"))["token"])
            self.assertFalse(self.lock.exists())
        self.assertNotEqual(tokens[0], tokens[1])

    def test_release_never_deletes_a_lock_owned_by_someone_else(self):
        with install._registry_lock(self.target):
            self.lock.unlink()
            write_lock(self.lock, os.getpid(), token="someone-else")
        self.assertTrue(self.lock.exists())

    def test_stale_lock_is_cleared(self):
        write_lock(self.lock, DEAD_PID, age_seconds=install.REGISTRY_LOCK_STALE_SECONDS + 5)
        with install._registry_lock(self.target):
            self.assertNotEqual(json.loads(self.lock.read_text(encoding="utf-8"))["token"], "legacy")
        self.assertFalse(self.lock.exists())
        self.assertFalse(self.guard.exists())

    def test_live_or_young_lock_is_never_cleared(self):
        write_lock(self.lock, os.getpid(), token="live", age_seconds=install.REGISTRY_LOCK_STALE_SECONDS + 5)
        with self.assertRaises(RuntimeError):
            with install._registry_lock(self.target):
                pass
        write_lock(self.lock, DEAD_PID, token="young")
        with self.assertRaises(RuntimeError):
            with install._registry_lock(self.target):
                pass
        self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["token"], "young")

    def test_clear_leaves_a_lock_that_changed_after_it_was_judged_stale(self):
        write_lock(self.lock, DEAD_PID, token="old", age_seconds=3600)
        observed = install._file_identity(self.lock)
        self.lock.unlink()
        write_lock(self.lock, os.getpid(), token="fresh-live-owner")
        self.assertEqual(install._clear_stale_registry_lock(self.lock, observed), "fresh")
        self.assertEqual(json.loads(self.lock.read_text(encoding="utf-8"))["token"], "fresh-live-owner")

    def test_only_one_installer_clears_at_a_time(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        observed = install._file_identity(self.lock)
        write_lock(self.guard, os.getpid(), token="other-installer")
        self.assertEqual(install._clear_stale_registry_lock(self.lock, observed), "busy")
        self.assertTrue(self.lock.exists())

    def test_guard_left_by_a_crashed_installer_is_taken_over(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        observed = install._file_identity(self.lock)
        write_lock(self.guard, DEAD_PID, token="crashed", age_seconds=install.REGISTRY_GUARD_STALE_SECONDS + 5)
        self.assertEqual(install._clear_stale_registry_lock(self.lock, observed), "cleared")
        self.assertFalse(self.guard.exists())

    def test_release_retries_and_never_masks_the_real_error(self):
        unlink, state = flaky_unlink(self.lock, 2)
        with mock.patch.object(install, "REGISTRY_UNLINK_PAUSE_SECONDS", 0.001):
            with mock.patch.object(Path, "unlink", unlink):
                with install._registry_lock(self.target):
                    pass
        self.assertFalse(self.lock.exists())
        unlink, _ = flaky_unlink(self.lock, 1000)
        with mock.patch.object(install, "REGISTRY_UNLINK_PAUSE_SECONDS", 0.001):
            with mock.patch.object(Path, "unlink", unlink):
                with self.assertRaises(ValueError):
                    with install._registry_lock(self.target):
                        raise ValueError("the real error")

    def test_clearing_retries_a_busy_stale_lock(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        observed = install._file_identity(self.lock)
        unlink, state = flaky_unlink(self.lock, 2)
        with mock.patch.object(install, "REGISTRY_UNLINK_PAUSE_SECONDS", 0.001):
            with mock.patch.object(Path, "unlink", unlink):
                self.assertEqual(install._clear_stale_registry_lock(self.lock, observed), "cleared")
        self.assertEqual(state["calls"], 3)

    def test_unremovable_stale_lock_fails_with_plain_error(self):
        write_lock(self.lock, DEAD_PID, age_seconds=3600)
        real_unlink = Path.unlink

        def refuse(path, *args, **kwargs):
            if Path(path) == self.lock:
                raise PermissionError("not allowed")
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", refuse):
            with self.assertRaises(RuntimeError) as caught:
                with install._registry_lock(self.target):
                    pass
        self.assertIn("Could not clear stale", str(caught.exception))
        self.assertFalse(self.guard.exists())


if __name__ == "__main__":
    unittest.main()
