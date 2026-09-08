from __future__ import annotations

import json
from pathlib import Path


BUNDLE = Path(__file__).resolve().parents[1] / "dsh-bundle"


def test_bundle_manifest_and_patch_are_installable_shape():
    package = json.loads((BUNDLE / "package.json").read_text(encoding="utf-8"))
    assert package["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert package["exports"]["./client"] == "./client.js"
    assert package["exports"]["./package.json"] == "./package.json"
    assert package["dsh"]["client"]["platform"] == "web"
    assert "@deepseek-ai/dsh-client-ui-conversation" in package["dsh"]["client"]["inject"]
    assert "@deepseek-ai/dsh-client-ui-sidebar" in package["dsh"]["client"]["inject"]
    assert package["main"] == "index.js"
    assert "skills/liveopt/SKILL.md" in package["files"]
    assert "skills/liveopt-data/SKILL.md" in package["files"]
    assert "skills/liveopt-results/SKILL.md" in package["files"]
    assert "client.js" in package["files"]
    patch = (BUNDLE / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "@deepseek-ai/dsh-mcp-client" in patch
    assert "transport: stdio" in patch
    assert "liveopt-mcp" in patch
    assert "toolCallTimeoutMs: 3600000" in patch
    assert "DEEPSEEK_MODEL: 'deepseek-v4-flash'" in patch
    assert "LIVEOPT_MCP_DEFAULT_MODEL: 'deepseek-v4-flash'" in patch
    assert "deepseek-v4-pro" not in patch
    assert "id: ui-model-selection" in patch
    assert "id: ui-settings-models" in patch
    assert "id: ui-agent-preset" in patch
    assert "id: ui-permission" in patch
    assert "id: ui-plan" in patch
    assert "id: ui-brand-official" in patch
    assert "ui-brand-official\n  disabled: true" in patch


def test_skill_uses_persistent_start_update_protocol():
    skill = (BUNDLE / "skills" / "liveopt" / "SKILL.md").read_text(encoding="utf-8")
    assert "mcp__liveopt__liveopt_start" in skill
    assert "mcp__liveopt__liveopt_update" in skill
    assert "mcp__liveopt__liveopt_inspect" in skill
    assert "mcp__liveopt__liveopt_prepare_data" in skill
    assert "mcp__liveopt__liveopt_prepare_uploads" in skill
    assert "mcp__liveopt__liveopt_wait" in skill
    assert "mcp__liveopt__liveopt_override_slots" in skill
    assert "emit no assistant text" in skill
    assert "hidden objective" in skill
    assert "API keys" in skill
    assert "solver_preference" in skill
    assert "deepseek-v4-flash" in skill
    assert "Pro model" in skill


def test_bundle_registers_liveopt_progress_component():
    client = (BUNDLE / "client.js").read_text(encoding="utf-8")
    assert "tool.call.toolview" in client
    assert "mcp__liveopt__liveopt_inspect" in client
    assert "total_generations" in client
    assert "feasible_count" in client
    assert "archive_size" in client
    assert "mcp__liveopt__liveopt_wait" in client
    assert "mcp__liveopt__liveopt_prepare_data" in client
    assert "mcp__liveopt__liveopt_prepare_uploads" in client
    assert "mcp__liveopt__liveopt_export" in client
    assert "mcp__liveopt__liveopt_override_slots" in client
    assert "Final population and Pareto set" in client
    assert "Objective evolution" in client
    assert "Restart and reuse selected" in client
    assert "Reused solutions" in client
    assert "Solid: best" in client
    assert "Dashed: mean" in client
    assert "Band: population range" in client
    assert "/results/" in client
    assert "?turn=" in client
    assert "/liveopt-api/jobs/" in client
    assert "/liveopt-api/uploads?filename=" in client
    assert "conversation.input.left" in client
    assert "liveopt-document-upload" in client
    assert "sidebar.brand.mark" in client
    assert "sidebar.brand.name" in client
    assert "conversation.hero.brand.mark" in client
    assert "sidebar.footer.action" in client
    assert "About MAPLE Harness" in client
    assert "Built on the MIT-licensed DeepSeek Harness" in client
    assert "const observer = new MutationObserver(enforceTitle)" in client
    assert "replaceAll('DeepSeek Harness', 'MAPLE Harness')" in client
    assert "Memory-Augmented Planning with Language and Evolution" in client
    assert "/liveopt-api/brand/" in client
    assert "settings.section" in client
    assert "MAPLE Harness Settings" in client
    assert "conversation.view" in client
    assert "id: 'solutions'" in client
    assert "solution-sessions" in client
    assert "liveopt:conversation-session:" in client
    assert "inferConversationLiveOptSession" in client
    assert "snapshot.chat.legacy.nodes" in client
    assert "This conversation has no MAPLE solution history yet." in client
    assert "liveopt-session-select" not in client
    assert "ctx.get('theme')" in client
    assert "theme.setTheme('light')" in client
    assert "installFixedApplicationSurface" in client


def test_liveopt_brand_assets_are_packaged_source_assets():
    asset_dir = BUNDLE.parents[0] / "src" / "liveopt_dsh" / "assets"
    for size in (64, 256, 512):
        asset = asset_dir / f"liveopt-mark-{size}.png"
        assert asset.is_file()
        assert asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_data_and_result_skills_use_compact_artifact_protocol():
    data_skill = (BUNDLE / "skills" / "liveopt-data" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    result_skill = (BUNDLE / "skills" / "liveopt-results" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "prepared_data_id" in data_skill
    assert "Do not paste extracted content" in data_skill
    assert "PDF" in data_skill
    assert "XLSX" in data_skill
    assert "iteration_history.csv" in result_skill
    assert "final_population.csv" in result_skill
    assert "liveopt_results.zip" in result_skill
