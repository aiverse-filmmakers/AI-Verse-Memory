# Security and Privacy

AI-Verse Memory stores persistent context as local plaintext Markdown plus a local SQLite search index.

## Important boundary

This project is **not** a secret manager and does not provide encryption at rest, access-control lists, or multi-user isolation.

Do not automatically store:

- passwords
- API keys
- authentication tokens
- private keys
- recovery codes
- financial credentials
- government identifiers
- highly sensitive medical details
- other secrets or regulated data that should live in a dedicated secure system

Prefer storing a reference such as "credentials are in the approved password manager" rather than the credential itself.

## AI-Verse OS v2 isolation

Native mode follows AI-Verse OS workspace boundaries. Normal workspace recall searches that workspace plus operator-level context only. Cross-workspace retrieval requires an explicit `--all-workspaces` request.

Memory is historical context. It must not silently override newer canonical `CURRENT.md`, profile, decision, or curated knowledge sources.

## Git safety

AI-Verse OS v2 already Git-ignores operator/workspace user state and `runtime/` by default. Standalone mode adds `.ai-verse-memory/` to `.gitignore`.

If you deliberately version persistent memory, use an appropriate private repository and review what is being committed.

## Derived index

The SQLite database is never canonical. It may be deleted and rebuilt from Markdown. In native mode it belongs under `runtime/indexes/ai-verse-memory/`.

## Provenance

Use the `source` field so important memories can be traced to their origin. Lower `confidence` when information is uncertain or inferred.

## Deletion

`forget <id> --yes` removes the canonical atomic Markdown memory and rebuilds the index. Separate backups, Git history, snapshots, exports, or source documents may still contain the original information.

## Reporting security issues

Open a GitHub issue only for non-sensitive security discussions. Never paste secrets or private memory content into a public issue.
