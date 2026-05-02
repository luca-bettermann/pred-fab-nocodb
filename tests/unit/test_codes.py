"""Tests for row-code generators."""
from pred_fab_nocodb._codes import (
    make_dim_position_code,
    make_study_constant_code,
    make_value_code,
)


# ─── dim_positions ────────────────────────────────────────────────────


def test_dim_position_code_depth_zero():
    """Depth-0 (scope-free) position code."""
    assert make_dim_position_code("structural:nodes", 0, 0) == "structural:nodes.d0.0"


def test_dim_position_code_depth_two():
    """Depth-2 (per layer-node) position code."""
    assert make_dim_position_code("structural:nodes", 2, 42) == "structural:nodes.d2.42"


def test_dim_position_code_preserves_colon_in_domain():
    """Colon-namespaced domain is kept verbatim."""
    code = make_dim_position_code("structural:segments", 1, 5)
    assert code == "structural:segments.d1.5"


# ─── set_study_constants ──────────────────────────────────────────────


def test_study_constant_code():
    """`{study}/{constant}`."""
    assert (
        make_study_constant_code("ADVEI_2026", "conversion_ratio")
        == "ADVEI_2026/conversion_ratio"
    )


# ─── set_exp_* ────────────────────────────────────────────────────────


def test_value_code_static_no_dim():
    """Static value (no dim) → `{exp}/{code}`."""
    assert make_value_code("ADVEI_2026_001", "path_offset") == "ADVEI_2026_001/path_offset"


def test_value_code_with_dim():
    """Trajectory / per-position value → `{exp}/{code}/{dim}`."""
    code = make_value_code(
        exp_code="ADVEI_2026_001",
        value_code="filament_width",
        dim_code="structural:nodes.d2.0",
    )
    assert code == "ADVEI_2026_001/filament_width/structural:nodes.d2.0"


def test_value_code_explicit_none_dim():
    """`dim_code=None` is the same as omitting it — no trailing slash."""
    a = make_value_code("ADVEI_2026_001", "path_offset")
    b = make_value_code("ADVEI_2026_001", "path_offset", dim_code=None)
    assert a == b == "ADVEI_2026_001/path_offset"
