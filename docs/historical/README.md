# Historical Documents

This directory holds documentation snapshots that describe ForgeOS as it was
at a particular point in time. They are kept for reference but are **not**
canonical — they describe past states of the project that may not match
current main.

## Why these documents are here

- **They captured a real moment in the project's history.** Deleting them
  would erase that record.
- **They are no longer kept in sync with main.** Reading them as current
  documentation will mislead you.
- **The canonical, always-current state of the project** lives in
  [`../../PRODUCTION_READINESS.md`](../../PRODUCTION_READINESS.md) at the
  repo root.

## What's here

| File | Date | What it described |
|---|---|---|
| `FINAL_STATUS_REPORT.md` | 2026-04-25 | Windowed desktop UI feature inventory (UI since redesigned) |
| `FUNCTIONAL_VERIFICATION_REPORT.md` | 2026-04-25 | Comprehensive feature review against then-current state |
| `HARDWARE_TEST_REPORT.md` | (April) | Hardware test results from an earlier build |
| `SAVE_TO_RESUME.md` | (April) | Resume-from-here notes for then-current windowed UI |
| `SECURITY_AUDIT.md` | 2026-04-20 | Security audit findings (grade A-) — many findings since fixed |
| `VERIFICATION_CHECKLIST.md` | (April) | Manual verification checklist for then-current build |
| `snapshots/20260417/` | 2026-04-17 | Full file-tree snapshot of `src/`, `install/`, `web/` |
| `snapshots/working/` | 2026-04-19 to 20 | HTML working snapshots from active development |

## Reading these

Treat them as you would any archived report: useful for understanding what
was tried and what was known at a particular time. **Do not use them to
infer current behavior or current API surface.** Run the tests in the
current `tests/` directory if you want to know what works today.

If you find yourself wishing one of these documents were updated to reflect
current state — that's the registry's job. Open an issue against
`PRODUCTION_READINESS.md` instead of editing what's in here.
