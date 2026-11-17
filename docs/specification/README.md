# V4.1 specification reconciliation (framework; specification text not yet supplied)

**Status: specification completeness UNVERIFIED.** The authoritative V4.1 specification is not in the repository and is not reconstructed from memory. The 83 internal requirement ids (`R<part>.<n>`) do not
represent verified coverage of V4.1.

## When the specification file is supplied
1. Save the original, unmodified, as `docs/specification/source/<original-name>`; record its source, version and SHA-256 in `docs/specification/SOURCE.md`.
2. Extract each requirement verbatim into `docs/specification/requirements-extract.json` (`id`, `part`, `text`, `source_location`).
3. Map every extracted requirement to catalogue ids in `docs/specification/mapping.json` (`spec_id` -> `[catalogue ids]` or `[]`).
4. `python scripts/spec_reconcile.py` reports: spec requirements without a catalogue entry (MISSING), catalogue entries without a spec requirement (UNMAPPED/duplicate), conflicts flagged by the mapper, and writes `docs/specification/reconciliation-report.md`.
5. Update `scripts/traceability_data.py` and regenerate the matrix; never edit the catalogue to hide a gap. Record evidence needed and responsible phase for each new or changed requirement.
Until step 4 has been run, the final report states: "Specification completeness: UNVERIFIED".

## Status (updated)
The reconciliation framework above has been executed with a stricter, line-referenced method: `python scripts/generate_v41_reconciliation.py` extracts 238 requirements from the original file by line number, validates every referenced path and test, and writes
`v4.1-requirements-baseline.md`, `v4.1-reconciliation-matrix.md`, `v4.1-gap-register.md`, `v4.1-acceptance-criteria.md` and `v4.1-requirements.json`; provenance is in `v4.1-specification-provenance.md`. The 85-item catalogue (`scripts/traceability_data.py`) is **kept provisional and unchanged**; the matrix maps 225 of the 238 original requirements to it and lists the 13 newly discovered ones.
