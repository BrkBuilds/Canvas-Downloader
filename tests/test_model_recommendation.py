"""Tests for the hardware-aware transcription-model recommendation.

Context: the recommendation used to exist in THREE contradicting places - a static
``"recommended": True`` on Small in MODEL_REGISTRY, a local
``"turbo" if gpu_ok else "small"`` in ui/panopto_page.py, and a hard-coded
"The 'Small' model is recommended for CPU" string in panopto/hardware.py. On a GPU
machine that rendered two "Recommended" badges at once, and Small transcribes
non-English lecture audio poorly enough that recommending it is bad advice.

panopto.models.recommend_model() is now the single source of truth.
"""

import pytest

from panopto.models import (
    MODEL_REGISTRY,
    get_model,
    recommend_model,
    recommendation_reason,
)


def gpu(vram_mb, name="NVIDIA GeForce RTX 4070"):
    return {"gpu_available": True, "gpu_vram_mb": vram_mb, "gpu_name": name}


def cpu(cores):
    return {"gpu_available": False, "cpu_cores": cores}


class TestNoStaticRecommendation:
    def test_registry_carries_no_recommended_flag(self):
        """A fixed flag is wrong on most hardware and duplicated the truth."""
        flagged = [m["id"] for m in MODEL_REGISTRY if m.get("recommended")]
        assert flagged == [], f"static recommendation(s) left in the registry: {flagged}"

    def test_no_note_claims_to_be_the_recommended_default(self):
        for m in MODEL_REGISTRY:
            assert "recommended default" not in m.get("note", "").lower(), m["id"]


class TestGpuRecommendations:
    @pytest.mark.parametrize("vram,expected", [
        (24576, "turbo"),   # RTX 4090
        (12288, "turbo"),   # RTX 4070 Ti
        (8192,  "turbo"),
        (4096,  "turbo"),   # exactly at the Turbo threshold
        (3072,  "medium"),  # not enough for Turbo
        (2048,  "small"),
        (1536,  "base"),
        (1024,  "tiny"),
    ])
    def test_vram_decides(self, vram, expected):
        assert recommend_model(gpu(vram)) == expected

    def test_unknown_vram_still_gets_the_gpu_default(self):
        """nvidia-smi not reporting VRAM must not silently demote to a CPU pick."""
        assert recommend_model({"gpu_available": True, "gpu_vram_mb": None}) == "turbo"

    def test_plain_large_v3_is_never_recommended(self):
        """Turbo is nearly as accurate and several times faster, so Large v3 has
        no machine where it is the better recommendation - it stays selectable."""
        for vram in (2048, 4096, 8192, 12288, 24576, 49152):
            assert recommend_model(gpu(vram)) != "large-v3"


class TestCpuRecommendations:
    @pytest.mark.parametrize("cores,expected", [
        (32, "turbo"),
        (16, "turbo"),
        (8,  "turbo"),   # exactly at the threshold
        (6,  "medium"),
        (4,  "small"),
        (2,  "small"),
        (1,  "base"),
    ])
    def test_core_count_decides(self, cores, expected):
        assert recommend_model(cpu(cores)) == expected

    def test_large_models_are_never_recommended_on_cpu(self):
        for cores in (1, 2, 4, 6, 8, 16, 64):
            assert recommend_model(cpu(cores)) != "large-v3"

    def test_unknown_core_count_assumes_a_modest_quad_core(self):
        assert recommend_model({"gpu_available": False, "cpu_cores": 0}) == "small"


class TestRobustness:
    @pytest.mark.parametrize("hw", [{}, None, {"gpu_available": False}])
    def test_never_raises_and_always_returns_a_real_model(self, hw):
        mid = recommend_model(hw) if hw is not None else recommend_model({})
        assert get_model(mid) is not None

    def test_a_broken_probe_still_yields_a_model(self):
        mid = recommend_model({"gpu_available": "yes-ish", "gpu_vram_mb": "lots"})
        assert get_model(mid) is not None

    def test_recommendation_is_deterministic(self):
        assert recommend_model(gpu(8192)) == recommend_model(gpu(8192))


class TestReason:
    def test_gpu_reason_names_the_card_and_vram(self):
        r = recommendation_reason(gpu(12288, "NVIDIA GeForce RTX 4070 Ti"))
        assert "Large v3 Turbo" in r
        assert "RTX 4070 Ti" in r
        assert "12 GB" in r

    def test_cpu_reason_names_the_cores_and_points_at_a_gpu(self):
        r = recommendation_reason(cpu(4))
        assert "4 cores" in r
        assert "GPU" in r

    def test_reason_mentions_the_model_it_recommends(self):
        for hw in (gpu(24576), gpu(3072), cpu(16), cpu(2)):
            label = get_model(recommend_model(hw))["label"]
            assert label in recommendation_reason(hw)

    def test_reason_is_a_single_sentence_ish(self):
        for hw in (gpu(8192), cpu(8)):
            assert recommendation_reason(hw).endswith('.')


class TestAgainstThisMachine:
    """Sanity-check the real probe on whatever machine runs the suite."""

    def test_live_probe_produces_a_valid_recommendation(self):
        mid = recommend_model()          # probes real hardware
        assert get_model(mid) is not None
        assert recommendation_reason().strip() != ""
