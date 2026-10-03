"""SUT version strings (SPEC 10.3): poetry-dynamic-versioning format, local labels, image versions, validation."""

from __future__ import annotations

import pytest

from otterdog_e2e.sut.version import (
    bump_version,
    compute_version,
    image_version,
    parse_tag,
    public_version,
    serialize_pep440,
    validate_version,
    version_key,
)

SHA = "d0d3b0832d8e21a9da86e0ef967859d2634af894"
HASH = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f809"


@pytest.mark.parametrize(
    ("tag", "distance", "expected"),
    [
        ("v1.6.1", 0, "1.6.1"),  # on a tag: the tag's version, no local label
        ("v1.6.1", 19, "1.7.0.dev19+e2e.gd0d3b08"),  # PR #792 head (verified with poetry dynamic-versioning show)
        ("v1.6.1", 15, "1.7.0.dev15+e2e.gd0d3b08"),  # main 9bdeb75 builds 1.7.0.dev15
        ("v1.6.0", 3, "1.7.0.dev3+e2e.gd0d3b08"),
        ("v1.9.4", 1, "1.10.0.dev1+e2e.gd0d3b08"),  # the minor bump resets the patch part
        ("v2.0", 2, "2.1.dev2+e2e.gd0d3b08"),
        ("v1.0.0rc1", 0, "1.0.0rc1"),
        ("v1.0.0-beta.2", 4, "1.1.0b2.dev4+e2e.gd0d3b08"),
        ("v1.0.0alpha", 0, "1.0.0a0"),
    ],
)
def test_compute_version_matches_otterdog_format(tag: str, distance: int, expected: str) -> None:
    """distance 0 -> serialize(base); otherwise serialize(bump_version(base, 1), dev=distance) + local label."""
    assert compute_version(tag, distance, SHA) == expected


def test_compute_version_dirty_label() -> None:
    """Dirty builds carry the first 8 hex digits of the overlay hash, also on a tagged commit."""
    assert compute_version("v1.6.1", 19, SHA, dirty_hash=HASH) == "1.7.0.dev19+e2e.gd0d3b08.dirty.1a2b3c4d"
    assert compute_version("v1.6.1", 0, SHA, dirty_hash=HASH) == "1.6.1+e2e.gd0d3b08.dirty.1a2b3c4d"
    assert compute_version("v1.6.1", 2, SHA.upper()) == "1.7.0.dev2+e2e.gd0d3b08"


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        (("1.6.1", 1, SHA), {}),  # not v-prefixed: dunamai's default pattern requires the "v"
        (("release-1", 1, SHA), {}),
        (("v1.6.1", -1, SHA), {}),
        (("v1.6.1", 1, "xyz"), {}),
        (("v1.6.1", 1, SHA), {"dirty_hash": "not-hex"}),
        (("v1", 3, SHA), {}),  # no minor part to bump
    ],
)
def test_compute_version_rejects_bad_input(args: tuple[str, int, str], kwargs: dict[str, str]) -> None:
    """Malformed tags, distances, shas and hashes raise ValueError."""
    with pytest.raises(ValueError):
        compute_version(*args, **kwargs)


def test_dunamai_helpers() -> None:
    """bump_version and serialize_pep440 behave like dunamai's."""
    assert bump_version("1.6.1") == "1.7.0"
    assert bump_version("1.6.1", 0) == "2.0.0"
    assert bump_version("1.6.1.4") == "1.7.0.0"
    assert serialize_pep440("1.7.0", "rc", None, dev=3) == "1.7.0rc0.dev3"
    assert serialize_pep440("1.7.0", "preview", 2) == "1.7.0rc2"
    assert parse_tag("v1.6.1") == ("1.6.1", None, None)
    assert parse_tag("v1.0.0rc1") == ("1.0.0", "rc", 1)
    with pytest.raises(ValueError):
        serialize_pep440("1.7.0", "weird", 1)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.7.0.dev19+e2e.gd0d3b08.dirty.1a2b3c4d", "1.7.0.dev19+e2e.gd0d3b08.dirty"),
        ("1.6.1+e2e.gd0d3b08.dirty.1a2b3c4d", "1.6.1+e2e.gd0d3b08.dirty"),
        ("1.7.0.dev19+e2e.gd0d3b08", "1.7.0.dev19+e2e.gd0d3b08"),
        ("1.6.1", "1.6.1"),
    ],
)
def test_image_version_is_hash_free(version: str, expected: str) -> None:
    """F12: the docker build-arg drops the dirty hash so successive edits reuse the dependency layers."""
    assert image_version(version) == expected


def test_public_version() -> None:
    """The local part is dropped."""
    assert public_version("1.7.0.dev19+e2e.gd0d3b08.dirty.1a2b3c4d") == "1.7.0.dev19"
    assert public_version("1.6.1") == "1.6.1"


@pytest.mark.parametrize("version", ["1.6.1", "1.7.0.dev19+e2e.gd0d3b08", "1.4.0", "2.0.0rc1", "1.4.1.dev2"])
def test_validate_version_accepts_supported(version: str) -> None:
    """Versions >= 1.4.0 pass."""
    validate_version(version)


@pytest.mark.parametrize(
    ("version", "message"),
    [
        ("0.0.0", "placeholder"),
        ("0.0.0.dev0", "placeholder"),
        ("0.1.0.dev1", "placeholder"),
        ("0.1.0.dev12+e2e.gabcdef0", "placeholder"),
        ("1.3.4", "older"),
        ("1.4.0.dev3", "older"),  # a dev release of 1.4.0 predates 1.4.0
        ("1.4.0rc1", "older"),
        ("not-a-version", "PEP 440"),
    ],
)
def test_validate_version_rejects(version: str, message: str) -> None:
    """Placeholders (missing build-arg, plugin or history) and old versions are refused."""
    with pytest.raises(ValueError, match=message):
        validate_version(version)


def test_validate_version_custom_minimum_still_rejects_placeholders() -> None:
    """A lower minimum never lets placeholder versions through."""
    validate_version("1.0.0", minimum="0.0.1")
    with pytest.raises(ValueError, match="placeholder"):
        validate_version("0.1.0.dev3", minimum="0.0.1")


def test_version_key_orders_like_pep440() -> None:
    """dev < pre < final < post, trailing zeros are insignificant."""
    ordered = ["1.4.0.dev1", "1.4.0a1", "1.4.0b2", "1.4.0rc1", "1.4.0", "1.4.0.post1", "1.4.1.dev0", "1.5"]
    assert sorted(ordered, key=version_key) == ordered
    assert version_key("1.4") == version_key("1.4.0")


def test_predates_compares_public_versions() -> None:
    """predates: PEP 440 order without local parts; None when a side is missing or not a version."""
    from otterdog_e2e.sut.version import predates

    assert predates("1.6.1", "1.7.0.dev15") is True
    assert predates("1.7.0.dev15+e2e.g9bdeb75", "1.7.0.dev15") is False
    assert predates("1.7.0.dev19+e2e.gd0d3b08.dirty", "1.7.0.dev15") is False
    assert predates("1.7.0.dev14+e2e.gb5f7bb1", "1.7.0.dev15") is True
    assert predates(None, "1.7.0") is None and predates("1.6.1", None) is None
    assert predates("1.6.1", "pr-792") is None and predates("not-a-version", "1.6.1") is None
