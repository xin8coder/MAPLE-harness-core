#!/usr/bin/env python3
"""Build a standalone source archive with a verified per-file manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

from check_release_contents import check_files


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(root):
    names = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root,
    ).decode().split('\0')
    return sorted({name for name in names if name and name != 'RELEASE_MANIFEST.json' and (root / name).is_file()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-manifest', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    paths = source_files(root)
    if any((root / name).is_symlink() for name in paths):
        raise SystemExit('Source releases may not contain symbolic links.')
    core_paths = [name for name in paths if name.startswith('vendor/liveopt-core/') and not name.endswith('/SOURCE_REVISION')]
    core_hash = hashlib.sha256(''.join(f'{name}\0{digest(root / name)}\n' for name in core_paths).encode()).hexdigest()
    if args.refresh_manifest:
        (root / 'vendor/liveopt-core/SOURCE_REVISION').write_text(f'Application core source snapshot\nSHA256: {core_hash}\n')
    check_files(root, paths)
    version = json.loads((root / 'desktop/package.json').read_text())['version']
    manifest = {
        'schema_version': 2,
        'source_revision': f'maple-harness-{version}',
        'upstream': {'package': '@deepseek-ai/dsh', 'version': '0.2.1-rc.2', 'commit': '687f282e8625c6b8d11ff58211a90524be2e4317'},
        'core_sha256': core_hash,
        'file_count': len(paths),
        'files': [{'path': name, 'sha256': digest(root / name), 'bytes': (root / name).stat().st_size} for name in paths],
    }
    manifest_path = root / 'RELEASE_MANIFEST.json'
    if args.refresh_manifest:
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    elif json.loads(manifest_path.read_text()) != manifest:
        raise SystemExit('Source manifest is out of date; refresh it before building a release.')
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        archive = args.output / f'MAPLE-Harness-{version}-source.tar.gz'
        with tarfile.open(archive, 'w:gz') as target:
            for name in paths + ['RELEASE_MANIFEST.json']:
                target.add(root / name, arcname=f'MAPLE-harness-core/{name}', recursive=False)
        zip_archive = args.output / f'MAPLE-Harness-{version}-source.zip'
        with zipfile.ZipFile(zip_archive, 'w', compression=zipfile.ZIP_DEFLATED) as target:
            for name in paths + ['RELEASE_MANIFEST.json']:
                target.write(root / name, arcname=f'MAPLE-harness-core/{name}')
        (args.output / 'SHA256SUMS').write_text(''.join(f'{digest(path)}  {path.name}\n' for path in [archive, zip_archive]))
        print(f'Built source ZIP and tar.gz: {len(paths) + 1} files, SHA-256 recorded in SHA256SUMS.')
    else:
        print(f'Verified {len(paths)} source files and the vendored core snapshot.')


if __name__ == '__main__':
    main()
