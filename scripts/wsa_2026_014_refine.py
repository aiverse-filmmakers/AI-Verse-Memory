from pathlib import Path

code_path = Path("scripts/public_beta.py")
code = code_path.read_text(encoding="utf-8")
old = '''        native = _read_authority_json(native_authority, "native Memory authority handoff")
        if native is None:
            native = native_payload("prepared", prepared_at=_now_iso())
            _atomic_write_json(native_authority, native)
        else:
            validate_identity(native, "native Memory handoff")
            status = str(native.get("status") or "")
            if status == "complete" and native.get("source_retirement_verified") is True:
                source = _read_authority_json(source_authority, "legacy Memory authority marker")
                if not source or source.get("status") != "retired" or source.get("handoff_id") != handoff_id:
                    raise RuntimeError("Completed native handoff is missing matching retired source authority")
                return native
            if status == "complete":
                native = native_payload(
                    "pending",
                    native,
                    pending_at=native.get("pending_at") or _now_iso(),
                    recovered_from_unverified_complete=True,
                )
                _atomic_write_json(native_authority, native)
            elif status not in {"prepared", "pending"}:
                raise RuntimeError(f"Unsupported native Memory handoff state: {status or 'missing'}")
'''
new = '''        native = _read_authority_json(native_authority, "native Memory authority handoff")
        if native is None:
            native = native_payload("prepared", prepared_at=_now_iso())
            _atomic_write_json(native_authority, native)
        else:
            status = str(native.get("status") or "")
            if status == "prepared" and native.get("handoff_id") != handoff_id:
                # A crash immediately after target preparation intentionally leaves
                # the source as the sole writable authority. If that authoritative
                # source changes before retry, a newly reviewed dry run gets a new
                # fingerprint/handoff identity. The stale target-only prepared
                # reservation can be replaced only while no source-side handoff
                # marker exists, so no committed/fenced authority is discarded.
                source = _read_authority_json(source_authority, "legacy Memory authority marker")
                if source is not None:
                    raise RuntimeError("Cannot replace stale prepared handoff after source-side handoff state exists")
                replaced_handoff_id = str(native.get("handoff_id") or "")
                native = native_payload(
                    "prepared",
                    prepared_at=_now_iso(),
                    replaced_prepared_handoff_id=replaced_handoff_id,
                )
                _atomic_write_json(native_authority, native)
            else:
                validate_identity(native, "native Memory handoff")
                if status == "complete" and native.get("source_retirement_verified") is True:
                    source = _read_authority_json(source_authority, "legacy Memory authority marker")
                    if not source or source.get("status") != "retired" or source.get("handoff_id") != handoff_id:
                        raise RuntimeError("Completed native handoff is missing matching retired source authority")
                    return native
                if status == "complete":
                    native = native_payload(
                        "pending",
                        native,
                        pending_at=native.get("pending_at") or _now_iso(),
                        recovered_from_unverified_complete=True,
                    )
                    _atomic_write_json(native_authority, native)
                elif status not in {"prepared", "pending"}:
                    raise RuntimeError(f"Unsupported native Memory handoff state: {status or 'missing'}")
'''
if code.count(old) != 1:
    raise SystemExit(f"expected exactly one handoff admission block, found {code.count(old)}")
code_path.write_text(code.replace(old, new, 1), encoding="utf-8")

test_path = Path("tests/test_migration_handoff_atomicity.py")
test = test_path.read_text(encoding="utf-8")
anchor = '''    def test_old_premature_complete_receipt_is_fenced_and_recovered(self):
'''
if test.count(anchor) != 1:
    raise SystemExit("test insertion anchor missing")
new_test = '''    def test_prepared_crash_allows_reviewed_replan_if_source_changes_before_fencing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, _, _, _ = self._setup(Path(tmp))
            mem._public_beta._HANDOFF_FAULT_INJECTOR = self._inject("after-target-prepared")
            try:
                with self.assertRaisesRegex(RuntimeError, "injected handoff fault: after-target-prepared"):
                    mem.migrate_legacy(target, apply=True, source_root=source)
            finally:
                mem._public_beta._HANDOFF_FAULT_INJECTOR = None

            native_authority = mem.public_beta_authority_file(target, mem.MODE_NATIVE)
            stale = json.loads(native_authority.read_text(encoding="utf-8"))
            stale_handoff_id = stale["handoff_id"]
            self.assertEqual(stale["status"], "prepared")
            self.assertFalse(self._target_normal_writable(target))
            self.assertFalse((source / ".ai-verse-memory" / "AUTHORITY.json").exists())

            _, _, created = mem.write_atomic(
                "source changed after target-only prepared crash",
                "fact",
                "global",
                source="standalone:wsa-014-replan",
                root=source,
                mode=mem.MODE_STANDALONE,
            )
            self.assertTrue(created)

            replanned = mem.migrate_legacy(target, apply=False, source_root=source)
            self.assertEqual(replanned["migratable"], 1)
            recovered = mem.migrate_legacy(target, apply=True, source_root=source)
            self.assertEqual(recovered["handoff_complete"], 1)

            final = json.loads(native_authority.read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "complete")
            self.assertIs(final["source_retirement_verified"], True)
            self.assertNotEqual(final["handoff_id"], stale_handoff_id)
            self.assertEqual(final["replaced_prepared_handoff_id"], stale_handoff_id)
            source_authority = json.loads(
                (source / ".ai-verse-memory" / "AUTHORITY.json").read_text(encoding="utf-8")
            )
            self.assertEqual(source_authority["handoff_id"], final["handoff_id"])
            self.assertEqual(source_authority["status"], "retired")
            self.assertTrue(self._target_normal_writable(target))

'''
test_path.write_text(test.replace(anchor, new_test + anchor, 1), encoding="utf-8")
