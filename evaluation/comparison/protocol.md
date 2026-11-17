# Manual versus automated workflow comparison: measurement protocol (V41-21.14)

The specification asks to compare manual and automated workflows using equivalent synthetic tasks, to distinguish simulated baselines from observed human performance, and not to claim real customer productivity gains from fictional scenarios. This protocol makes those distinctions mechanical.

## Evidence classes (never mixed)
| Class | What it is | Where it comes from | In this repository |
|---|---|---|---|
| **A. Measured automated** | Wall-clock time of the platform's own steps for equivalent synthetic tasks | `python scripts/demo.py smoke --compare --no-browser` (real API and worker on an isolated database, local mocks) | Measured on each run; **system time only**: no human reading or thinking time, no real external systems |
| **B. Observed manual** | Times a real person was actually watched taking for the same tasks | A CSV the observer fills in: `evaluation/comparison/observed-manual.csv` (columns `task_id, participant_role, seconds, notes`; template provided) | **None.** No human was observed. Without the file the report says so and makes no comparison |
| **C. Simulated manual** | A hypothetical baseline computed from assumptions the reader supplies | `evaluation/comparison/assumptions.json` (`source` plus `[low, high]` seconds per step; template provided; nulls are refused) | **None shipped.** The repository contains no assumed manual times and the code never invents any |

## Tasks
`synthetic-tasks.json`: 20 equivalent fictional fault reports for the three registered Apex demonstration pumps (seven component parts, four report templates). Every task goes through the same steps: extract an incident, draft a ticket, request approval, approve (a different person), worker submission to the mock ticketing system. Equivalence means the same steps and similar report length; it does not mean the tasks are representative of any real plant.

## What is timed and what is not
Timed (A): the five platform steps above. Not timed and listed in every report: the human touchpoints that remain in the automated workflow (writing the report, reviewing the incident, drafting and requesting approval, the supervisor's decision) and everything outside the platform. Therefore the automated number is **not** the duration of the whole workflow with people in it.

## Reporting rules
Median and p95 per step and end to end (nearest rank). Backend labels are recorded (deterministic test-only backends are CI/functional only and are labelled so). A class C figure is always printed as HYPOTHETICAL with its assumptions and source. A report with no class B data and no class C assumptions contains class A only, plus the statement that no comparison is possible. No sentence in any report or document may describe these results as productivity gains for a customer.

## How to complete the comparison honestly
1. Have a real person perform the 20 tasks manually (search the documents, write the structured incident, enter a ticket, obtain approval) while an observer records the seconds per task in `observed-manual.csv`.
2. Optionally write `assumptions.json` if a hypothetical baseline is wanted before observation, with its source.
3. Re-run the command; the report then shows B (and C) next to A, still as separate sections.
Limits: single author, deterministic backends by default, local mocks, 20 tasks.
