#!/usr/bin/env python3
"""Fail a pull request that changes a Helm chart without bumping its version.

On a push to main, chart-releaser releases every chart changed since the last
release tag. A release whose version is already in index.yaml is skipped, so
a merged chart change that kept its version never reaches anybody. This check
is run on pull requests to catch that before the merge.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

import yaml

DEFAULT_BASE = "origin/main"
DEFAULT_INDEX_REF = "origin/gh-pages"
DEFAULT_CHARTS_DIR = "charts"
INDEX_FILE = "index.yaml"
CHART_FILE = "Chart.yaml"


def git(*args: str) -> subprocess.CompletedProcess:
    """Run git in the current directory."""
    return subprocess.run(["git", *args], capture_output=True, text=True)


def die(message: str) -> int:
    print(f"check_chart_versions: {message}", file=sys.stderr)
    return 2


def parse_chart(text: str) -> dict:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"not a YAML mapping ({type(data).__name__})")
    return data


def load_published(ref: str) -> set:
    proc = git("show", f"{ref}:{INDEX_FILE}")
    if proc.returncode != 0:
        verify = git("rev-parse", "--verify", "--quiet", ref)
        if verify.returncode != 0:
            raise LookupError(f"unknown git ref {ref!r}")
        raise LookupError(f"no {INDEX_FILE} on {ref!r}")
    try:
        index = yaml.safe_load(proc.stdout)
    except yaml.YAMLError as exc:
        raise ValueError(f"{ref}:{INDEX_FILE} is not valid YAML: {exc}") from exc
    if not isinstance(index, dict):
        raise ValueError(f"{ref}:{INDEX_FILE} is not a YAML mapping")
    published = set()
    for name, versions in (index.get("entries") or {}).items():
        for entry in versions or []:
            if not isinstance(entry, dict):
                continue
            version = entry.get("version")
            if version is not None:
                published.add((str(name), str(version)))
    return published


def changed_chart_dirs(charts_dir: str, merge_base: str) -> list:
    proc = git("diff", "--name-only", merge_base, "HEAD", "--", f"{charts_dir}/")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    names = set()
    prefix = f"{charts_dir}/"
    for line in proc.stdout.splitlines():
        if not line.startswith(prefix):
            continue
        parts = line[len(prefix):].split("/")
        # charts/<chart>/<path>: the first component below charts/ is the chart.
        if len(parts) >= 2 and parts[0]:
            names.add(parts[0])
    return sorted(names)


def base_version(chart_path: str, merge_base: str):
    proc = git("show", f"{merge_base}:{chart_path}")
    if proc.returncode != 0:
        return None
    try:
        return parse_chart(proc.stdout).get("version")
    except (ValueError, yaml.YAMLError):
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="Base ref to compare against (default: $GITHUB_BASE_REF as origin/<ref>, else origin/main).")
    parser.add_argument("--index-ref", default=DEFAULT_INDEX_REF, help=f"Ref holding {INDEX_FILE} (default: {DEFAULT_INDEX_REF}).")
    parser.add_argument("--charts-dir", default=DEFAULT_CHARTS_DIR, help=f"Directory holding the charts (default: {DEFAULT_CHARTS_DIR}).")
    args = parser.parse_args(argv)

    charts_dir = args.charts_dir.strip("/") or DEFAULT_CHARTS_DIR

    if args.base:
        base = args.base
    else:
        env_base = os.environ.get("GITHUB_BASE_REF", "").strip()
        base = f"origin/{env_base}" if env_base else DEFAULT_BASE

    try:
        published = load_published(args.index_ref)
    except LookupError as exc:
        return die(f"{exc}; the chart version check needs index.yaml from gh-pages")
    except ValueError as exc:
        return die(str(exc))

    merge = git("merge-base", base, "HEAD")
    if merge.returncode != 0:
        detail = merge.stderr.strip().splitlines()[-1] if merge.stderr.strip() else "git merge-base failed"
        return die(
            f"cannot compute the merge base of {base} and HEAD ({detail}); "
            "a shallow clone is the usual cause: git fetch --no-tags --unshallow origin"
        )
    merge_base = merge.stdout.strip()

    try:
        charts = changed_chart_dirs(charts_dir, merge_base)
    except RuntimeError as exc:
        return die(str(exc))

    if not charts:
        print(f"no chart changes under {charts_dir}/ against {base}")
        return 0

    failures = 0
    oks = 0
    for chart in charts:
        chart_path = f"{charts_dir}/{chart}/{CHART_FILE}"
        shown = git("show", f"HEAD:{chart_path}")
        if shown.returncode != 0:
            continue  # Deleted chart: nothing to release.
        try:
            data = parse_chart(shown.stdout)
        except (ValueError, yaml.YAMLError) as exc:
            print(f"error: {charts_dir}/{chart}: cannot parse {CHART_FILE}: {exc}")
            failures += 1
            continue

        errors = []
        if data.get("name") != chart:
            errors.append(
                f"{charts_dir}/{chart}: chart dir {chart} holds chart {data.get('name')!r}; "
                "the directory must be named after the chart"
            )
        version = data.get("version")
        if not isinstance(version, str) or not version.strip():
            errors.append(f"{charts_dir}/{chart}: version is missing or not a string")
        elif (str(data.get("name")), version) in published:
            message = (
                f"{charts_dir}/{chart}: version {version} is already published (index.yaml on gh-pages); "
                f"bump version in {charts_dir}/{chart}/{CHART_FILE}"
            )
            previous = base_version(chart_path, merge_base)
            if previous is not None and str(previous) == version:
                message += f" (the version did not change since {base})"
            errors.append(message)

        if errors:
            for message in errors:
                print(f"error: {message}")
            failures += 1
        else:
            print(f"ok {charts_dir}/{chart} {version}")
            oks += 1

    checked = oks + failures
    if checked == 0:
        print(f"no chart changes under {charts_dir}/ against {base}")
        return 0
    print(f"{checked} chart(s) changed against {base}: {oks} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
