import json
from pathlib import Path


def mark_native_ready(root: Path, mem) -> None:
    root = Path(root)
    registry = root / ".aiverse" / "extensions" / "registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "extensions": {
                    "ai-verse-memory": {
                        "id": "ai-verse-memory",
                        "supported": True,
                        "installed": True,
                        "enabled": True,
                        "version": getattr(mem, "VERSION", "test"),
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    mem.public_beta_write_component_state(
        root,
        mem.MODE_NATIVE,
        installed=True,
        setup_completed=True,
        enabled=True,
        last_action="test-fixture",
    )
