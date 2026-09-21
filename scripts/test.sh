#!/usr/bin/env sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"

export PYTHONPYCACHEPREFIX="$repo_dir/.pycache"
PYTHONPATH=src python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
mkdir -p build
PYTHONPATH=src python3 -m incident_summary.cli examples/incidents.json --json build/summary.json --html build/index.html --as-of 2026-09-21T00:00:00Z
ruby -e "require 'yaml'; YAML.load_file('.gitlab-ci.yml'); YAML.load_file('ci/jobs.yml'); YAML.load_file('.github/workflows/ci.yml')"
printf '%s\n' "Local validation passed."
