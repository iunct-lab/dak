from dak_maintenance.semver import BumpLevel, classify_update, combine_bump


def test_patch_bump():
    assert classify_update("1.51.0", "1.51.3") is BumpLevel.PATCH


def test_minor_bump():
    assert classify_update("1.51.0", "1.52.0") is BumpLevel.MINOR


def test_major_bump():
    assert classify_update("1.51.0", "2.0.0") is BumpLevel.MAJOR


def test_no_change():
    assert classify_update("1.2.3", "1.2.3") is BumpLevel.NONE


def test_v_prefix_and_suffixes():
    assert classify_update("v1.2.3", "1.2.4") is BumpLevel.PATCH
    assert classify_update("1.2.3rc1", "1.2.3") is BumpLevel.NONE
    assert classify_update("1.2.3", "1.3.0+local") is BumpLevel.MINOR


def test_zero_major_classified_like_any_other_major():
    # 0.x は 1.x+ と同じ規則（major成分の変化のみ MAJOR）。実際の破壊的変更検知は
    # changelog ベースの risk assessor（risk.py）に委ねる。
    assert classify_update("0.27.0", "0.28.0") is BumpLevel.MINOR
    assert classify_update("0.27.0", "0.27.1") is BumpLevel.PATCH
    assert classify_update("0.27.0", "1.0.0") is BumpLevel.MAJOR


def test_double_zero_patch_is_patch():
    # 0.0.x はポリシー変更で挙動が最も変わったサブケース: 旧ルール（最初の非ゼロ
    # 成分の変化を1段階引き上げ）では 0.0.1→0.0.2 は MINOR だったが、現行の
    # 一律ルールでは PATCH。0.0.x→0.1.0 は MINOR になる。
    assert classify_update("0.0.1", "0.0.2") is BumpLevel.PATCH
    assert classify_update("0.0.1", "0.1.0") is BumpLevel.MINOR


def test_missing_components_default_zero():
    assert classify_update("1", "1.0.1") is BumpLevel.PATCH
    assert classify_update("1.2", "1.3") is BumpLevel.MINOR


def test_unparseable_is_unknown():
    assert classify_update("", "1.0.0") is BumpLevel.UNKNOWN
    assert classify_update("abc", "def") is BumpLevel.UNKNOWN


def test_downgrade_is_unknown():
    assert classify_update("2.0.0", "1.9.0") is BumpLevel.UNKNOWN


def test_combine_bump_picks_most_severe():
    assert combine_bump([BumpLevel.PATCH, BumpLevel.MINOR]) is BumpLevel.MINOR
    assert combine_bump([BumpLevel.MINOR, BumpLevel.MAJOR, BumpLevel.PATCH]) is BumpLevel.MAJOR
    assert combine_bump([BumpLevel.PATCH, BumpLevel.UNKNOWN]) is BumpLevel.UNKNOWN


def test_combine_bump_ignores_none_unless_only_entries():
    assert combine_bump([BumpLevel.NONE, BumpLevel.PATCH]) is BumpLevel.PATCH
    assert combine_bump([BumpLevel.NONE, BumpLevel.NONE]) is BumpLevel.NONE


def test_combine_bump_empty_is_none():
    assert combine_bump([]) is BumpLevel.NONE


def test_uv_image_zero_minor_is_major():
    # uv は 0.x の minor で破壊的変更を出す（0.13.0）。uv の画像だけ特例（#766）
    assert classify_update("0.12.24", "0.13.0", package="ghcr.io/astral-sh/uv") is BumpLevel.MAJOR


def test_uv_image_patch_is_patch():
    assert classify_update("0.13.0", "0.13.1", package="ghcr.io/astral-sh/uv") is BumpLevel.PATCH


def test_other_zero_minor_unchanged():
    assert classify_update("0.115.0", "0.116.0", package="fastapi") is BumpLevel.MINOR
