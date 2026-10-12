# Release Descriptor Maintainer Handoff

`release/component-release.json` is the owner-local release record for AI-Verse Memory. The owner-local gate is `.github/workflows/release-descriptor.yml`, and its designated native workflow is `.github/workflows/test.yml` (`Test`).

For an `accepted` descriptor, the gate must find a successful native workflow run whose `head_sha` equals `descriptor.revision` exactly. Do not substitute current branch health, a later commit, or a latest-success result. Missing, inaccessible, malformed, mismatched, or unsuccessful evidence fails closed.

A pinned accepted revision remains valid after later metadata-only maintainer commits unless component code or the designated native workflow contract changes.

This is owner-local acceptance only. It does not qualify the AI-Verse Distribution current component set and it is not a member feature-release record. Distribution qualification and member release records are separate authorities.
