---
name: dependency_maintenance
description: "Triage a dependency update: classify the semver bump, assess changelog risk, and recommend auto-merge vs. human review. Dogfoods the repo's own maintenance policy."
tools:
  - triage_dependency
  - classify_bump
---
You can triage dependency updates using the same policy the CI automation uses
(`maintenance/dak_maintenance`). This lets the agent reason about upgrades itself.

# Policy (must match CI)
Auto-merge ONLY when: bump is patch/minor AND CI is green AND the changelog is
assessed SAFE (no breaking changes). Everything else -> human review.

# Available Actions
- `classify_bump(from_version, to_version)` — returns the semver bump level
  (major/minor/patch/none/unknown). 0.x is classified like any other version
  (only a major-component change counts as major); changelog risk assessment
  is what catches actual breaking changes.
- `triage_dependency(package, from_version, to_version, ci_passed, changelog)` —
  full decision: bump × CI × changelog-risk → "auto-merge" or "needs-human-review"
  with a reason. Pass the changelog text you have; leave empty if unknown
  (unknown risk is treated conservatively as needs-review).

Never claim an update is safe to auto-merge unless the policy above is satisfied.
