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
        (64, "small"),
        (32, "small"),
        (16, "small"),
        (10, "small"),   # Apple M4 - the machine that exposed the Turbo bug
        (8,  "small"),
        (6,  "small"),
        (4,  "small"),
        (2,  "small"),   # exactly at Small's threshold
        (1,  "base"),
    ])
    def test_core_count_decides(self, cores, expected):
        assert recommend_model(cpu(cores)) == expected

    def test_nothing_above_small_is_ever_recommended_on_cpu(self):
        """Turbo used to be recommended from 8 cores up, on the theory that its
        name describes its CPU speed. Measured on an Apple M4 (int8, beam 5, VAD,
        real lecture audio): small 6.2x realtime, turbo 3.3x, medium 2.5x. Turbo's
        4-layer decoder is what makes it fast, but on CPU the encoder dominates -
        and its encoder is large-v3's. A course that takes 50 minutes on tiny took
        an estimated 6.5 hours on Turbo."""
        for cores in (1, 2, 4, 6, 8, 10, 16, 32, 64, 128):
            assert recommend_model(cpu(cores)) in {"small", "base", "tiny"}

    def test_the_recommended_model_is_never_one_the_advisory_warns_about(self):
        """The defect this class exists to prevent, stated as the invariant that
        would have caught it: device_advisory() called medium too slow to use
        while recommend_model() returned turbo, which is 1.28x faster. The two
        live in different modules, so nothing forced them to agree.

        Scoped to 'warn'. A low-core machine legitimately gets an 'info' that
        transcription will be slow whatever it is handed - that is a fact about
        the machine, not a contradiction of the recommendation."""
        from panopto.hardware import device_advisory
        for cores in (1, 2, 4, 6, 8, 10, 16, 64):
            hw = cpu(cores)
            mid = recommend_model(hw)
            adv = device_advisory("cpu", mid, hw)
            assert adv is None or adv[0] != "warn", (
                f"{mid} is recommended on {cores} cores and warned about at once")

    def test_choosing_turbo_on_a_cpu_warns(self):
        """Not recommending Turbo is only half the fix - it stays selectable, so
        a user who picks it by hand must be told, exactly as they are for medium.
        Measured on an M4: turbo 3.3x realtime against medium's 2.5x, a 1.28x
        gap. Its NAME is the only thing that ever suggested otherwise."""
        from panopto.hardware import device_advisory
        for cores in (4, 8, 10, 16, 64):
            adv = device_advisory("cpu", "turbo", cpu(cores))
            assert adv is not None and adv[0] == "warn", f"{cores} cores: {adv}"

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

    def test_a_mac_is_not_told_a_gpu_would_help(self):
        """The engine has no GPU backend on macOS at all (hardware.py's
        cpu_only_mac branch), so no GPU a Mac user could buy would change the
        answer. Naming one sends them after a fix that does not exist."""
        r = recommendation_reason({"gpu_available": False, "cpu_cores": 10,
                                   "is_mac": True})
        assert "10 cores" in r
        assert "GPU" not in r

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
