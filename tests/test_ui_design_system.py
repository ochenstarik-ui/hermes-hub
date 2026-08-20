"""Regression checks for the Hermes Hub UI design-system foundation."""
from __future__ import annotations

import inspect
import typing

import pytest

pytest.importorskip("customtkinter")

from antigravity_provider.router.ui import components
from antigravity_provider.router.ui.theme import Theme


@pytest.mark.unit
def test_required_component_library_is_available() -> None:
    required = {
        "HubCard",
        "SectionHeader",
        "StatusBadge",
        "PlanBadge",
        "ProviderBadge",
        "QuotaBar",
        "QuotaBucketWidget",
        "AccountCardWidget",
        "AgentCardWidget",
        "RouteTargetWidget",
        "EmptyState",
        "SearchField",
        "FilterButton",
        "ActionButton",
        "IconButton",
        "ConfirmDialog",
        "Toast",
    }
    assert required <= set(vars(components))


@pytest.mark.unit
def test_brand_gold_is_not_used_as_healthy_status() -> None:
    assert Theme.COLOR_BRAND == Theme.ACCENT
    assert Theme.COLOR_POSITIVE == Theme.STATUS_HEALTHY
    assert Theme.COLOR_POSITIVE != Theme.COLOR_BRAND
    assert components._semantic_color("healthy") == Theme.COLOR_POSITIVE
    assert components._semantic_color("reserve") == Theme.COLOR_CAUTION
    assert components._semantic_color("error") == Theme.COLOR_NEGATIVE
    assert components._semantic_color("unknown") == Theme.COLOR_NEUTRAL


@pytest.mark.unit
def test_layout_and_typography_tokens_are_centralized() -> None:
    assert Theme.PAGE_PAD_X in {Theme.SPACE_MD, Theme.SPACE_LG, Theme.SPACE_XL}
    assert Theme.CARD_PAD_X in {Theme.SPACE_SM, Theme.SPACE_MD, Theme.SPACE_LG}
    assert Theme.HEIGHT_INPUT == Theme.HEIGHT_BTN_MD - 2
    assert Theme.font_title() == Theme.font_title_page()
    assert Theme.font_title_page()[1] > Theme.font_heading()[1] > Theme.font_body()[1]


@pytest.mark.unit
def test_quota_bucket_has_stable_key_and_in_place_update_api() -> None:
    signature = inspect.signature(components.QuotaBucketWidget.__init__)
    assert "bucket_key" in signature.parameters
    assert callable(getattr(components.QuotaBucketWidget, "update_bucket"))


@pytest.mark.unit
def test_unknown_quota_is_supported_explicitly() -> None:
    signature = inspect.signature(components.QuotaBar.set_value)
    annotation = signature.parameters["value"].annotation
    # inspect resolves the real typing object here (components.py does not use
    # `from __future__ import annotations`), so compare types, not source text.
    assert type(None) in typing.get_args(annotation), (
        "QuotaBar.set_value must accept None so an unknown quota can be rendered "
        f"as such instead of a fabricated number; got {annotation!r}"
    )


@pytest.mark.unit
def test_long_identity_is_ellipsized_without_losing_source_value() -> None:
    identity = "very.long.account.identity.for.daily.operations@example.enterprise"
    shortened = components.ellipsize_text(identity, 28)
    assert len(shortened) == 28
    assert shortened.endswith("…")
    assert identity.startswith(shortened[:-1])
