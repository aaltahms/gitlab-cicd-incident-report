# GitLab CI/CD Incident Report Pipeline

A dependency-free Python reporting tool that turns incident records into a JSON summary and a static HTML report. Its GitLab pipeline validates the source, runs deterministic unit tests, builds the report, preserves build artifacts and publishes the HTML output through GitLab Pages on the default branch.

The application and tests were newly implemented with Codex assistance in September 2026, inspired by earlier CI/CD coursework. The original course implementation has not been recovered. See [PROVENANCE.md](PROVENANCE.md).

## What it demonstrates

- multi-stage GitLab CI/CD with `validate`, `test`, `build` and `deploy` stages;
- reusable job configuration in `ci/jobs.yml`;
- deterministic tests using only the Python standard library;
- artifacts passed from the build job to the Pages job;
- branch and merge-request rules through `workflow:rules` and job-level rules;
- a GitHub Actions mirror that runs validation, tests and artifact generation when the portfolio repository is hosted on GitHub;
- a practical output that a reviewer can inspect locally or in a Pages preview.

## Run locally

Python 3.9 or newer is sufficient. The project has no third-party runtime dependencies.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m incident_summary.cli \
  examples/incidents.json \
  --json build/summary.json \
  --html build/index.html --as-of 2026-09-21T00:00:00Z
```

Open `build/index.html` to inspect the generated report.

## Input format

The input is a JSON array. Each record requires:

- `id`: non-empty string;
- `severity`: `low`, `medium`, `high` or `critical`;
- `status`: `open`, `investigating`, `resolved` or `closed`;
- `service`: non-empty string;
- `opened_at`: ISO-8601 timestamp;
- `resolved_at`: ISO-8601 timestamp or `null`.

Resolved and closed incidents must include `resolved_at`, which cannot precede `opened_at`.

## Pipeline

```text
validate_source -> unit_tests -> build_report -> pages
```

`build_report` retains `build/summary.json` and `build/index.html` for one week. The `pages` job consumes those artifacts and publishes the static report only from the default branch.

## Repository layout

```text
.
├── .gitlab-ci.yml
├── .github/workflows/ci.yml
├── ci/jobs.yml
├── examples/incidents.json
├── src/incident_summary/
├── tests/
└── scripts/test.sh
```

## Verification status

- Local unit and subprocess integration tests: 19 passed on Python 3.9.6
- Python bytecode compilation: passed
- Report generation from the included fixture: passed
- YAML parsing with Ruby's standard YAML parser: passed
- GitHub Actions and GitLab-hosted pipelines: pending publication

## Limitations

This demonstration reads a local JSON fixture and produces a static report. It does not connect to a production ticketing system, deploy an application server or handle real credentials. The final GitLab pipeline result should be linked here after publication.

## Reporting and failure behavior

- Active backlog is sorted by age with stable ID tie-breaking. An explicit `--as-of` timestamp makes output reproducible; future events relative to that snapshot are rejected rather than guessed into a historical state.
- Mean, median and nearest-rank p90 describe resolved/closed records only. Sample size is included; an empty sample produces null, not zero.
- IDs are trimmed before duplicate detection; unknown fields, invalid statuses and missing timezones fail validation. Active records cannot carry resolution timestamps.
- The CLI returns exit code 2 with a concise error for invalid input or filesystem failures. It protects the input from path, symlink and hard-link aliases. Both outputs are staged before replacement; individual replacements are atomic, but the pair is not a filesystem transaction.
- Included incidents are synthetic. No City of Guelph tickets, identities or workplace data are used.

## CI design choices

The GitLab workflow switches branch pushes to merge-request pipelines when an MR exists, avoiding duplicate push/MR runs. The GitHub mirror declares read-only repository permissions, cancels superseded runs, and tests Python 3.9, 3.12 and 3.13. The matrix is configured but remains unverified until hosted runs complete.

References: [GitLab workflow rules](https://docs.gitlab.com/ci/yaml/workflow/), [GitLab CI YAML](https://docs.gitlab.com/ci/yaml/), [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

## Failure demonstration

Copy the example fixture, give two incidents the same ID, and run the CLI against that copy. It exits with code 2 before replacing reports. Restore the fixture and rerun to generate identical report bytes for the same snapshot. The subprocess suite exercises this behavior automatically, including existing-report preservation and invalid UTF-8.
