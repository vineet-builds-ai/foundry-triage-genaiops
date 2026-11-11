import pytest

from triage.manifest import load_manifest


def test_shipping_manifest_is_internally_consistent(shipping_manifest):
    assert shipping_manifest.version == shipping_manifest.prompt.version
    assert shipping_manifest.model_temperature == 0.0
    assert shipping_manifest.tools == []
    assert shipping_manifest.prompt.fallback is not None


def test_release_id_pins_the_prompt_bytes(shipping_manifest):
    assert shipping_manifest.prompt_sha256[:12] in shipping_manifest.release_id
    assert str(shipping_manifest.version) in shipping_manifest.release_id


def test_release_id_is_stable(repo_root):
    first = load_manifest(repo_root / "agent" / "agent.yaml")
    second = load_manifest(repo_root / "agent" / "agent.yaml")
    assert first.release_id == second.release_id


def test_the_two_versions_have_different_release_ids(
    shipping_manifest, regressed_manifest
):
    assert shipping_manifest.release_id != regressed_manifest.release_id


def test_missing_prompt_file_is_an_error(tmp_path):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text("name: x\nversion: 1\nprompt:\n  file: nope.md\n")
    with pytest.raises(FileNotFoundError):
        load_manifest(manifest)


def test_manifest_without_a_prompt_is_an_error(tmp_path):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text("name: x\nversion: 1\n")
    with pytest.raises(ValueError):
        load_manifest(manifest)
