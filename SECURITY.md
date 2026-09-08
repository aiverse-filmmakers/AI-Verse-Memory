# Security and Privacy

AI-Verse Memory stores persistent context as local plaintext Markdown plus a local SQLite search index.

## Important boundary

This project is **not a secret manager** and does not provide encryption at rest, access-control lists, or multi-user isolation.

Do not automatically store:

- passwords
- API keys
- authentication tokens
- private keys
- recovery codes
- financial credentials
- government identifiers
- other highly sensitive secrets

Prefer storing a reference such as "credentials are in the team's password manager" rather than the credential itself.

## Git safety

The installer Git-ignores `.ai-verse-memory/` by default because memory may contain personal or business context.

If you deliberately remove that ignore rule to sync memory through Git, use a private repository and review what is being committed.

## Provenance

Use the `source` field so important memories can be traced back to their origin. Lower `confidence` when information is uncertain or inferred.

## Deletion

Canonical memories are ordinary local files. Deleting the relevant Markdown memory and running:

```bash
python .ai-verse-memory/memory.py rebuild
```

removes it from the active index.

Remember that separate backups, Git history, filesystem snapshots, exported transcripts, or other source files may still contain the original information.

## Reporting security issues

Open a GitHub issue only for non-sensitive security discussions. Do not paste secrets or private memory content into a public issue.
