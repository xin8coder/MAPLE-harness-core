from __future__ import annotations

from pathlib import Path

from liveopt_dsh.config import ServiceConfig


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_default_runtime_state_is_outside_research_checkout(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("LIVEOPT_MCP_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    config = ServiceConfig.from_env()
    assert config.state_dir == tmp_path / ".local/share/liveopt-dsh/state"


def test_installer_builds_from_disposable_snapshots():
    installer = (PLUGIN_ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    assert 'mktemp -d "${TMPDIR:-/tmp}/liveopt-dsh-install.' in installer
    assert 'cp -R "$CORE_ROOT/evo2" "$CORE_ROOT/demo"' in installer
    assert '"$PLUGIN_ROOT/vendor/liveopt-core"' in installer
    assert 'LIVEOPT_CORE_ROOT' in installer
    assert 'pip install "$CORE_ROOT" "$PLUGIN_ROOT"' not in installer
    assert "pip install --force-reinstall --no-deps" in installer
    assert 'plugin --profile "$PROFILE" add "$INSTALL_ROOT/dsh-bundle"' in installer
    assert 'cat >"$BIN_DIR/liveopt-web-api"' in installer


def test_local_bootstrap_is_user_scoped_and_pinned():
    bootstrap = (PLUGIN_ROOT / "scripts/bootstrap_local.sh").read_text(
        encoding="utf-8"
    )
    assert 'NODE_VERSION="${LIVEOPT_NODE_VERSION:-24.19.0}"' in bootstrap
    assert 'DSH_VERSION="${LIVEOPT_DSH_VERSION:-0.1.0-rc.8}"' in bootstrap
    assert "$HOME/.local/share/liveopt-dsh" in bootstrap
    assert "--allow-build=node-pty" in bootstrap
    assert "--allow-build=protobufjs" in bootstrap
    assert "dsh-subprocess-local,@google" not in bootstrap
    assert 'ln -sfn "$NODE_ROOT/bin/pnpm" "$BIN_DIR/pnpm"' in bootstrap
    assert 'if [[ -L "$BIN_DIR/dsh" || -e "$BIN_DIR/dsh" ]]' in bootstrap
    assert 'exec "$NODE_ROOT/bin/node" "$DSH_ENTRY"' in bootstrap
    assert "sudo" not in bootstrap


def test_local_start_keeps_runtime_state_outside_checkout():
    start = (PLUGIN_ROOT / "scripts/start_local.sh").read_text(encoding="utf-8")
    assert 'LIVEOPT_MCP_STATE_DIR:-$LOCAL_ROOT/state' in start
    assert 'NODE_USE_ENV_PROXY:-1' in start
    assert '--trusted-host "$LIVEOPT_DSH_TRUSTED_HOST"' in start
    assert "liveopt-web-api" in start
    assert "DEEPSEEK_API_KEY=" not in start
    assert "KIMI_API_KEY=" not in start


def test_intranet_deployment_keeps_dsh_on_loopback_and_private_network():
    start = (PLUGIN_ROOT / "scripts/start_intranet.sh").read_text(encoding="utf-8")
    caddyfile = (PLUGIN_ROOT / "intranet/Caddyfile").read_text(encoding="utf-8")
    assert "LIVEOPT_DSH_HOST=127.0.0.1" in start
    assert 'LIVEOPT_DSH_TRUSTED_HOST="${LIVEOPT_INTRANET_BIND}:${INTRANET_PORT}"' in start
    assert "Refusing non-private intranet bind address" in start
    assert "basic_auth" not in caddyfile
    assert "tls internal" in caddyfile
    assert "reverse_proxy 127.0.0.1" in caddyfile
    assert "handle_path /liveopt-api/*" in caddyfile


def test_container_public_workspace_is_read_only():
    compose = (PLUGIN_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${LIVEOPT_WORKSPACE:-../..}:/workspace:ro" in compose


def test_runtime_adapter_does_not_reference_paper_artifact_paths():
    forbidden = ("paper/", "scripts/experiments/", "release_artifacts/")
    for path in sorted((PLUGIN_ROOT / "src/liveopt_dsh").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} references research artifact path {token}"
