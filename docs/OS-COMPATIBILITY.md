# AI-Verse OS compatibility states

AI-Verse Memory classifies a target before choosing an integration mode.

| State | Meaning | Memory behavior |
|---|---|---|
| `no-os` | `AI-VERSE.yaml` is absent | standalone mode is allowed |
| `compatible` | supported AI-Verse OS v2 `unified-workspace` manifest and required layout are present | native AI-Verse OS mode is allowed |
| `incompatible` | an AI-Verse manifest exists but is unsupported, malformed, ambiguous, unreadable, or missing required v2 layout | installation and engine auto-detection fail closed before Memory writes |

The presence of `AI-VERSE.yaml` is therefore never treated as equivalent to “no OS.” An unsupported future schema such as v3 must be explicitly supported by a Memory release before native integration can proceed.

The installer and engine both use `scripts/os_compat.py` as the compatibility authority. Standalone fallback is only for repositories that do not contain an AI-Verse OS manifest.
