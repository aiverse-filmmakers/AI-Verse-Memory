from pathlib import Path

path = Path("scripts/public_beta.py")
text = path.read_text(encoding="utf-8")

def replace_block(source: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = source.find(start_marker)
    if start < 0:
        raise SystemExit(f"{label}: start marker not found")
    end = source.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"{label}: end marker not found")
    return source[:start] + replacement.rstrip() + "\n\n" + source[end:]

anchor = '_LOCK_PROCESS_LOCKS: Dict[str, threading.Lock] = {}\n'
if anchor not in text:
    raise SystemExit("handoff hook anchor not found")
if "_HANDOFF_FAULT_INJECTOR" not in text:
    text = text.replace(
        anchor,
        anchor
        + '_HANDOFF_FAULT_INJECTOR = None\n\n\n'
        + 'def _handoff_fault(stage: str) -> None:\n'
        + '    hook = _HANDOFF_FAULT_INJECTOR\n'
        + '    if hook is not None:\n'
        + '        hook(stage)\n',
        1,
    )

native_migration_required = r'''
def _native_migration_required(engine, root: Path) -> Tuple[bool, str]:
    handoff = _read_authority_json(
        _authority_file(engine, root, engine.MODE_NATIVE),
        "native Memory authority handoff",
    )

    if handoff is not None:
        handoff_status = str(handoff.get("status") or "")
        if handoff_status not in {"prepared", "pending", "complete"}:
            return True, f"native Memory authority handoff has invalid state: {handoff_status or 'missing'}"
        if handoff_status != "complete":
            return True, f"native Memory authority handoff is {handoff_status}"
        if handoff.get("source_retirement_verified") is not True:
            return True, "native Memory authority handoff completion has not durably verified source retirement"

    plan = root / "operator" / "memory" / "migrations" / "legacy-ai-verse-memory-plan.json"
    if plan.exists():
        if plan.is_symlink() or not plan.is_file():
            return True, "migration plan is unsafe"
        if handoff is None:
            return True, "reviewed legacy migration plan has not completed authority handoff"

    legacy = root / ".ai-verse-memory"
    if legacy.exists():
        if legacy.is_symlink() or not legacy.is_dir():
            return True, "legacy standalone Memory root is unsafe"
        source_authority = _read_authority_json(
            legacy / "AUTHORITY.json",
            "legacy Memory authority marker",
        )
        retired = bool(
            source_authority
            and source_authority.get("status") == "retired"
            and handoff
            and handoff.get("status") == "complete"
            and handoff.get("source_retirement_verified") is True
            and source_authority.get("handoff_id") == handoff.get("handoff_id")
        )
        if not retired:
            return True, "legacy standalone Memory is still an active writable canonical route"
    return False, ""
'''
text = replace_block(
    text,
    "def _native_migration_required(engine, root: Path) -> Tuple[bool, str]:",
    "def _native_write_readiness(engine, root: Path) -> dict:",
    native_migration_required,
    "native migration readiness",
)

old_retired = '''        if payload.get("status") == "retired":
            replacement = payload.get("replacement_root") or "the adopted AI-Verse OS"
            raise RuntimeError(
                "This standalone Memory store is retired and preserved as historical evidence. "
                f"Canonical writes moved to {replacement}."
            )
'''
if old_retired not in text:
    raise SystemExit("standalone retired authority block not found")
new_retired = '''        if payload.get("status") == "retiring":
            replacement = payload.get("replacement_root") or "the adopted AI-Verse OS"
            raise RuntimeError(
                "This standalone Memory store is being retired during canonical authority handoff. "
                f"Canonical writes are temporarily fenced while ownership moves to {replacement}."
            )
        if payload.get("status") == "retired":
            replacement = payload.get("replacement_root") or "the adopted AI-Verse OS"
            raise RuntimeError(
                "This standalone Memory store is retired and preserved as historical evidence. "
                f"Canonical writes moved to {replacement}."
            )
'''
text = text.replace(old_retired, new_retired, 1)

retire_block = r'''
def _retire_legacy_authority(engine, root: Path, snapshot: dict, counts: dict) -> dict:
    source_base = Path(snapshot["source_root"]).resolve(strict=True)
    legacy = Path(snapshot["legacy_root"])
    if not legacy.exists() or legacy.is_symlink() or not legacy.is_dir():
        raise RuntimeError(f"Unsafe legacy Memory authority root: {legacy}")
    legacy = legacy.resolve(strict=True)
    root = Path(root).resolve(strict=True)

    handoff_id = "handoff-" + hashlib.sha256(
        (snapshot["source_fingerprint"] + "\n" + str(root)).encode("utf-8")
    ).hexdigest()[:24]
    identity = {
        "schema_version": PUBLIC_BETA_SCHEMA,
        "handoff_protocol": "2",
        "handoff_id": handoff_id,
        "source_root": snapshot["source_root"],
        "legacy_root": snapshot["legacy_root"],
        "source_fingerprint": snapshot["source_fingerprint"],
        "target_root": str(root),
        "target_scope_fingerprint": snapshot["target_scope_fingerprint"],
    }

    native_authority = _authority_file(engine, root, engine.MODE_NATIVE)
    source_authority = legacy / "AUTHORITY.json"

    def validate_identity(payload: dict, label: str) -> None:
        for key in (
            "handoff_id",
            "source_root",
            "legacy_root",
            "source_fingerprint",
            "target_root",
            "target_scope_fingerprint",
        ):
            if payload.get(key) != identity[key]:
                raise RuntimeError(f"{label} identity mismatch for {key}")

    def native_payload(status: str, current: Optional[dict] = None, **extra) -> dict:
        payload = dict(identity)
        payload["status"] = status
        if current:
            for key in ("prepared_at", "pending_at"):
                if current.get(key):
                    payload[key] = current[key]
            if current.get("recovered_from_unverified_complete"):
                payload["recovered_from_unverified_complete"] = True
        payload.update(extra)
        return payload

    def source_payload(status: str, current: Optional[dict] = None, **extra) -> dict:
        payload = {
            "schema_version": PUBLIC_BETA_SCHEMA,
            "handoff_protocol": "2",
            "handoff_id": handoff_id,
            "status": status,
            "source_root": snapshot["source_root"],
            "legacy_root": snapshot["legacy_root"],
            "source_fingerprint": snapshot["source_fingerprint"],
            "replacement_root": str(root),
            "reason": "Canonical Memory authority adopted by native AI-Verse Memory.",
        }
        if current:
            for key in ("retiring_at", "retired_at"):
                if current.get(key):
                    payload[key] = current[key]
        payload.update(extra)
        return payload

    with _mutation_lock(engine, source_base, engine.MODE_STANDALONE):
        locked_snapshot = _legacy_snapshot(engine, root, source_base)
        if locked_snapshot["source_fingerprint"] != snapshot["source_fingerprint"]:
            raise RuntimeError("Legacy source memory bytes changed before authority handoff")
        if locked_snapshot["target_scope_fingerprint"] != snapshot["target_scope_fingerprint"]:
            raise RuntimeError("Target workspace topology changed before authority handoff")

        native = _read_authority_json(native_authority, "native Memory authority handoff")
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

        _handoff_fault("after-target-prepared")

        source = _read_authority_json(source_authority, "legacy Memory authority marker")
        if source is None:
            source = source_payload("retiring", retiring_at=_now_iso())
            _atomic_write_json(source_authority, source)
        else:
            if source.get("handoff_id") != handoff_id:
                raise RuntimeError("Legacy Memory authority belongs to a different handoff")
            if source.get("source_fingerprint") != snapshot["source_fingerprint"]:
                raise RuntimeError("Legacy Memory authority source fingerprint mismatch")
            if source.get("replacement_root") != str(root):
                raise RuntimeError("Legacy Memory authority replacement root mismatch")
            if source.get("status") not in {"retiring", "retired"}:
                raise RuntimeError("Legacy Memory authority is in an unsupported handoff state")

        _handoff_fault("after-source-retiring")

        native = _read_authority_json(native_authority, "native Memory authority handoff")
        if native is None:
            raise RuntimeError("Native Memory handoff state disappeared during retirement")
        validate_identity(native, "native Memory handoff")
        if native.get("status") != "pending":
            native = native_payload(
                "pending",
                native,
                pending_at=native.get("pending_at") or _now_iso(),
            )
            _atomic_write_json(native_authority, native)

        _handoff_fault("after-target-pending")

        old_writer = legacy / "memory.py"
        backup = legacy / "memory.py.pre-handoff"
        expected_stub = _retirement_stub(source_authority)
        if old_writer.exists():
            if old_writer.is_symlink() or not old_writer.is_file():
                raise RuntimeError(f"Cannot retire unsafe legacy Memory writer: {old_writer}")
            if backup.exists():
                if backup.is_symlink() or not backup.is_file():
                    raise RuntimeError(f"Unsafe legacy Memory writer backup: {backup}")
            else:
                current_text = old_writer.read_text(encoding="utf-8")
                if current_text == expected_stub:
                    raise RuntimeError("Legacy writer is already retired but its original backup is missing")
                _atomic_write_bytes(backup, old_writer.read_bytes())
            if old_writer.read_text(encoding="utf-8") != expected_stub:
                _atomic_write_text(old_writer, expected_stub)
            if old_writer.read_text(encoding="utf-8") != expected_stub:
                raise RuntimeError("Legacy Memory writer retirement stub verification failed")

        _handoff_fault("after-writer-fenced")

        final_locked_snapshot = _legacy_snapshot(engine, root, source_base)
        if final_locked_snapshot["source_fingerprint"] != snapshot["source_fingerprint"]:
            raise RuntimeError("Legacy source memory bytes changed during authority handoff")

        source = _read_authority_json(source_authority, "legacy Memory authority marker")
        if source is None:
            raise RuntimeError("Legacy Memory authority marker disappeared during handoff")
        if source.get("status") != "retired":
            source = source_payload(
                "retired",
                source,
                retired_at=source.get("retired_at") or _now_iso(),
            )
            _atomic_write_json(source_authority, source)

        source = _read_authority_json(source_authority, "legacy Memory authority marker")
        if (
            not source
            or source.get("status") != "retired"
            or source.get("handoff_id") != handoff_id
            or source.get("source_fingerprint") != snapshot["source_fingerprint"]
            or source.get("replacement_root") != str(root)
        ):
            raise RuntimeError("Legacy Memory source retirement verification failed")

        _handoff_fault("after-source-retired")

        native = _read_authority_json(native_authority, "native Memory authority handoff")
        if native is None:
            raise RuntimeError("Native Memory handoff state disappeared before completion")
        validate_identity(native, "native Memory handoff")
        complete = native_payload(
            "complete",
            native,
            completed_at=native.get("completed_at") or _now_iso(),
            source_retirement_verified=True,
            source_retired_at=source.get("retired_at"),
            counts=dict(counts),
        )
        _atomic_write_json(native_authority, complete)

        verified = _read_authority_json(native_authority, "native Memory authority handoff")
        if (
            not verified
            or verified.get("status") != "complete"
            or verified.get("source_retirement_verified") is not True
            or verified.get("handoff_id") != handoff_id
        ):
            raise RuntimeError("Native Memory authority completion verification failed")

        _handoff_fault("after-target-complete")
        return verified
'''
text = replace_block(
    text,
    "def _retire_legacy_authority(engine, root: Path, snapshot: dict, counts: dict) -> dict:",
    "def _patched_migrate_legacy(engine, original_rebuild):",
    retire_block,
    "legacy authority retirement",
)

old_migration_complete = '''                    if receipt.get("status") != "complete" or receipt.get("source_fingerprint") != plan.get("source_fingerprint"):
                        raise ValueError("Migration handoff receipt does not match the reviewed source snapshot")
'''
if old_migration_complete not in text:
    raise SystemExit("migration-complete receipt validation anchor not found")
text = text.replace(
    old_migration_complete,
    '''                    if (
                        receipt.get("status") != "complete"
                        or receipt.get("source_retirement_verified") is not True
                        or receipt.get("source_fingerprint") != plan.get("source_fingerprint")
                    ):
                        raise ValueError("Migration handoff receipt does not prove verified source retirement for the reviewed snapshot")
''',
    1,
)

path.write_text(text, encoding="utf-8")
