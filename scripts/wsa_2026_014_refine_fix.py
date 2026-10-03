from pathlib import Path
import runpy

runpy.run_path("scripts/wsa_2026_014_refine.py", run_name="__main__")

path = Path("scripts/public_beta.py")
text = path.read_text(encoding="utf-8")
old = '            for key in ("prepared_at", "pending_at"):\n'
new = '            for key in ("prepared_at", "pending_at", "replaced_prepared_handoff_id"):\n'
if text.count(old) != 1:
    raise SystemExit(f"expected one native handoff audit-field preservation loop, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
