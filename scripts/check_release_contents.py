#!/usr/bin/env python3
"""Keep private material out of source releases and preserve source attribution."""
from pathlib import Path
import argparse
import gzip
import re
import subprocess

SUFFIXES = {'.tex', '.bib', '.sty', '.bst', '.ppt', '.pptx', '.pdf', '.zip', '.tar', '.tgz', '.cff'}
PREFIXES = ('paper/', 'paper_outputs/', 'release_artifacts/', 'logs/', 'outputs/', 'anonymous-demo/', 'site/', 'docs/maple', 'docs/iclr')
PRIVATE_NAMES = {'.env', '.credentials.yaml', 'connection.json', 'provider.env', 'service.env',
                 'config.env', 'front.env', 'llm.env', 'cloudflare-token', 'public-url.txt',
                 'ngrok-authtoken', 'ngrok-url.txt', 'cloudflare-url.txt'}
PUBLIC_LINK_DOCUMENTS = {
    'README.md', 'README.zh-CN.md', 'docs/user-guide.md',
    'docs/user-guide.zh-CN.md', 'docs/releases/v0.2.0.md', 'docs/releases/v0.2.1.md',
    'docs/releases/v0.2.2.md',
    'docs/releases/v0.2.3.md',
    'docs/releases/v0.2.4.md',
}
# Published installation guides intentionally link to the application and demo.
PUBLIC_PRODUCT_URLS = re.compile(
    rb'https://(?:github\.com/xin8coder/MAPLE-harness-core|'
    rb'xin8coder\.github\.io/MAPLE-harness)(?=[/#?\s)"<>]|$)'
)
PATTERNS = {
    'provider API key': re.compile(rb'\bsk-[0-9a-fA-F]{32,}\b'),
    'GitHub access token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'Hugging Face access token': re.compile(rb'\bhf_[A-Za-z0-9]{30,}\b'),
    'private key': re.compile(rb'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
    'personal project URL': re.compile(rb'https?://(?:github\.com/[A-Za-z0-9_.-]+/MAPLE(?:[/.#?\-]|\b)|[A-Za-z0-9_.-]+\.github\.io/MAPLE(?:[/.#?\-]|\b))', re.I),
    'machine-specific home path': re.compile(rb'/(?:home|Users)/[A-Za-z0-9_.-]+/'),
}


def check_files(root, paths):
    failures = []
    for rel in paths:
        path = root / rel
        if (path.name in PRIVATE_NAMES or path.name.endswith(('.key', '.pem'))
                or 'secrets' in Path(rel).parts or 'dsh-home' in Path(rel).parts
                or path.name.startswith('.env.') and path.name != '.env.example'):
            failures.append(f'private deployment configuration: {rel}')
        if Path(rel).suffix.lower() in SUFFIXES or rel.endswith('.tar.gz') or rel.startswith(PREFIXES):
            failures.append(f'excluded release material: {rel}')
        content = path.read_bytes()
        if path.suffix == '.gz':
            content = gzip.decompress(content)
        for label, pattern in PATTERNS.items():
            checked = content
            if label == 'personal project URL' and rel in PUBLIC_LINK_DOCUMENTS:
                checked = PUBLIC_PRODUCT_URLS.sub(b'', content)
            if pattern.search(checked):
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
    paths = [path for path in subprocess.check_output(['git', 'ls-files', '--cached', '-z'], cwd=root).decode().split('\0') if path]
    check_files(root, paths)
    if not args.files_only:
        history = subprocess.check_output(['git', 'log', '--all', '--format=%an%x00%ae%x00%cn%x00%ce'], cwd=root, text=True)
        expected = ['Anonymous Authors', 'anonymous@example.invalid'] * 2
        for line in history.splitlines():
            if line.split('\0') != expected:
                raise SystemExit('Commit authors and committers must be anonymous.')
    print(f'Checked {len(paths)} files: release boundaries and attribution verified.')


if __name__ == '__main__':
    main()
