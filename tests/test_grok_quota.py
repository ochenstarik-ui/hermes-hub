"""Квота Grok читается у провайдера, а не показывается как «Н/Д».

Владелец спросил: «где закончились лимиты?» — и показал экран, где
еженедельный лимит SuperGrok израсходован на 14%. Но вызовы через Hub
падали с 402.

Разгадка: это ДВА РАЗНЫХ кошелька. Подписка SuperGrok покрывает чат
grok.com, а программный доступ списывается с кредитов API. Их у аккаунта
ноль — подтверждено биллинговым эндпоинтом.

Раньше _collect_grok_quota строила пустые корзины и никуда не ходила,
поэтому Hub показывал «Н/Д» и объяснить ничего не мог.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from antigravity_provider.router.quota_collector import AccountQuotaService


def _billing(prepaid: float, cap: float, used: float) -> MagicMock:
    payload = {
        "config": {
            "currentPeriod": {"start": "2026-08-19T00:00:00+00:00", "end": "2026-08-26T00:00:00+00:00"},
            "prepaidBalance": {"val": prepaid},
            "onDemandCap": {"val": cap},
            "onDemandUsed": {"val": used},
        }
    }
    resp = MagicMock()
    resp.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    return resp


def _auth() -> dict:
    return {"token": {"access_token": "tok"}}


def test_exhausted_account_explains_two_wallets():
    """Нулевой баланс объясняется, а не показывается прочерком."""
    with patch("antigravity_provider.router.quota_collector.urllib.request.urlopen",
               return_value=_billing(0, 0, 0)):
        snap = AccountQuotaService()._collect_grok_quota("grok-orch", _auth())

    assert snap.source == "provider_api"
    assert "SuperGrok" in (snap.unavailable_reason or ""), "не объяснено, откуда берётся доступ"
    assert all(b.status == "exhausted" for b in snap.buckets)


def test_zero_cap_does_not_fabricate_percent():
    """При нулевом лимите доля не определена — процент выдумывать нельзя."""
    with patch("antigravity_provider.router.quota_collector.urllib.request.urlopen",
               return_value=_billing(0, 0, 0)):
        snap = AccountQuotaService()._collect_grok_quota("grok-orch", _auth())

    on_demand = next(b for b in snap.buckets if b.id == "grok.on_demand")
    assert on_demand.remaining_percent is None
    assert on_demand.used_percent is None
    assert on_demand.limit_absolute == 0


def test_account_with_credits_reports_real_percent():
    """Когда лимит есть, доля считается по измеренным значениям."""
    with patch("antigravity_provider.router.quota_collector.urllib.request.urlopen",
               return_value=_billing(50, 200, 50)):
        snap = AccountQuotaService()._collect_grok_quota("grok-orch", _auth())

    on_demand = next(b for b in snap.buckets if b.id == "grok.on_demand")
    assert on_demand.used_percent == 25.0
    assert on_demand.remaining_percent == 75.0
    assert snap.unavailable_reason is None
