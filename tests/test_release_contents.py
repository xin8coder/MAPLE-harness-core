from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_contents', ROOT / 'scripts/check_release_contents.py')
release_contents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_contents)


def check_content(tmp_path, filename, content):
    (tmp_path / 'LICENSE').write_text('Copyright (c) 2026 Anonymous Authors\n')
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    release_contents.check_files(tmp_path, [filename])


@pytest.mark.parametrize('filename', sorted(release_contents.PUBLIC_LINK_DOCUMENTS))
def test_public_guides_allow_only_documented_product_urls(tmp_path, filename):
    host = 'https://' + 'github.com/'
    project = host + 'xin8coder/' + 'MAPLE-harness-core'
    site = 'https://' + 'xin8coder.github.io/' + 'MAPLE-harness/'
    check_content(tmp_path, filename, project + '/releases/latest\n' + site)


@pytest.mark.parametrize('filename', ['src/example.py', 'docs/operations.md'])
def test_product_url_exception_does_not_apply_to_other_files(tmp_path, filename):
    url = 'https://' + 'github.com/' + 'xin8coder/' + 'MAPLE-harness-core'
    with pytest.raises(SystemExit, match='personal project URL'):
        check_content(tmp_path, filename, url)


def test_public_guides_still_reject_other_project_urls(tmp_path):
    url = 'https://' + 'github.com/' + 'someone/' + 'MAPLE-research'
    with pytest.raises(SystemExit, match='personal project URL'):
        check_content(tmp_path, 'README.md', url)


def test_public_guides_still_reject_machine_paths(tmp_path):
    path = '/' + 'home/' + 'example/' + 'workspace'
    with pytest.raises(SystemExit, match='machine-specific home path'):
        check_content(tmp_path, 'README.md', path)


def test_private_deployment_files_remain_excluded(tmp_path):
    with pytest.raises(SystemExit, match='private deployment configuration'):
        check_content(tmp_path, 'provider.env', 'PRIVATE_CONFIG=example')
