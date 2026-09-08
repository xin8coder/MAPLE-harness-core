#!/usr/bin/env python3
"""Check anonymous source releases for manuscript files and identity metadata."""
from pathlib import Path
import argparse
import gzip
import re
import subprocess

SUFFIXES = {'.tex', '.bib', '.sty', '.bst', '.ppt', '.pptx', '.pdf', '.zip', '.tar', '.tgz', '.cff'}
PREFIXES = ('paper/', 'paper_outputs/', 'release_artifacts/', 'logs/', 'outputs/', 'anonymous-demo/', 'site/', 'docs/maple', 'docs/iclr')
PATTERNS = {
    'personal project URL': re.compile(rb'https?://(?:github\.com/[A-Za-z0-9_.-]+/MAPLE(?:[/.#?\-]|\b)|[A-Za-z0-9_.-]+\.github\.io/MAPLE(?:[/.#?\-]|\b))', re.I),
    'machine-specific home path': re.compile(rb'/(?:home|Users)/[A-Za-z0-9_.-]+/'),
}


def check_files(root, paths):
    failures = []
    for rel in paths:
        path = root / rel
        if Path(rel).suffix.lower() in SUFFIXES or rel.endswith('.tar.gz') or rel.startswith(PREFIXES):
            failures.append(f'excluded release material: {rel}')
        content = path.read_bytes()
        if path.suffix == '.gz':
            content = gzip.decompress(content)
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                failures.append(f'{label}: {rel}')
    license_lines = (root / 'LICENSE').read_text().splitlines()
    copyright_lines = [line for line in license_lines if line.startswith('Copyright ')]
    if copyright_lines != ['Copyright (c) 2026 Anonymous Authors']:
        failures.append('project license must retain anonymous attribution')
    if failures:
        raise SystemExit('\n'.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files-only', action='store_true', help='Check staged files before creating a commit.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(['git', 'ls-files', '--cached'], cwd=root, text=True).splitlines()
    check_files(root, paths)
    if not args.files_only:
        history = subprocess.check_output(['git', 'log', '--all', '--format=%an%x00%ae%x00%cn%x00%ce'], cwd=root, text=True)
        expected = ['Anonymous Authors', 'anonymous@example.invalid'] * 2
        for line in history.splitlines():
            if line.split('\0') != expected:
                raise SystemExit('Commit authors and committers must be anonymous.')
    print(f'Checked {len(paths)} files: anonymous source content verified.')


if __name__ == '__main__':
    main()
