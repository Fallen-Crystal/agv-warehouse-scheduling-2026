# WEPA integration evidence — 2026-10-29

See ../../docs/experiments/wepa-integration-20261029.md for scope and interpretation.
Formal measurements use ccff577 and protocols/wepa-20261029-frozen.json.
The 64 paired runs all completed and passed independent audit. The 8 sealed
windows have no algorithm runs. Windows are not independent source dates:
development has 2 dates, validation has 3; both window and date-cluster intervals
are reported. Gate remains the default because the selected anchor has two
regressions and exceeds the 10% CPU-cost adoption target.

Raw trajectories and failed prototype attempts stay in ignored local runs/.
These compact rows intentionally omit machine-specific absolute trace paths.
Verification records the three later CLI/cache/metadata-only source fixes;
old measurements are never re-signed with their new fingerprint.
