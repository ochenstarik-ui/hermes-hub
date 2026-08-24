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


def _billing(prepaid: float, cap: float, used: float, credit_pct=None, products=None) -> MagicMock:
    config = {
        "currentPeriod": {"start": "2026-08-19T00:00:00+00:00", "end": "2026-08-26T00:00:00+00:00"},
        "prepaidBalance": {"val": prepaid},
        "onDemandCap": {"val": cap},
        "onDemandUsed": {"val": used},
    }
    if credit_pct is not None:
        config["creditUsagePercent"] = credit_pct
    if products:
        config["productUsage"] = products
    payload = {"config": config}
    resp = MagicMock()
    resp.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    return resp


def _auth() -> dict:
    return {"token": {"access_token": "tok"}}


def test_account_without_subscription_or_credits_says_so():
    """Ни подписки, ни кредитов — честная причина, а не пустые корзины.

    Прежняя версия рисовала две корзины с нулями и утверждала, что подписка
    SuperGrok «не пополняет кредиты». Это оказалось неверно: проверка на
    живом аккаунте GROK PRO показала, что подписка даёт доступ и вызовы
    проходят без покупки кредитов.
    """
    with patch("antigravity_provider.router.quota_collector.urllib.request.urlopen",
               return_value=_billing(0, 0, 0)):
        snap = AccountQuotaService()._collect_grok_quota("grok-orch", _auth())

    assert snap.source == "provider_api"
    assert snap.buckets == []
    assert "не вернул" in (snap.unavailable_reason or "")


def test_zero_cap_does_not_fabricate_percent():
    """При нулевом лимите корзина кредитов не создаётся вовсе.

    Доля от нуля не определена, и показывать «0%» было бы выдумкой.
    """
    with patch("antigravity_provider.router.quota_collector.urllib.request.urlopen",
               return_value=_billing(0, 0, 0, credit_pct=5.0)):
        snap = AccountQuotaService()._collect_grok_quota("grok-orch", _auth())

    assert not any(b.id == "grok.on_demand" for b in snap.buckets)


def test_account_with_credits_reports_real_percent():
    """Когда лимит есть, доля считается по измеренным значениям."""
    with patch("antigravity_provider.router.quota_collector.urllib.request.urlopen",
               return_value=_billing(50, 200, 50)):
        snap = AccountQuotaService()._collect_grok_quota("grok-orch", _auth())

    on_demand = next(b for b in snap.buckets if b.id == "grok.on_demand")
    assert on_demand.used_percent == 25.0
    assert on_demand.remaining_percent == 75.0
    assert snap.unavailable_reason is None


def test_subscription_usage_is_reported():
    """Расход подписки — то самое число, что владелец видит на grok.com.

    Раньше читались только баланс и лимит трат, у подписчика оба нулевые,
    и квота показывалась как «Н/Д» при живой подписке.
    """
    products = [
        {"product": "GrokChat", "usagePercent": 13.0},
        {"product": "GrokBuild", "usagePercent": 1.0},
    ]
    with patch("antigravity_provider.router.quota_collector.urllib.request.urlopen",
               return_value=_billing(0, 0, 0, credit_pct=14.0, products=products)):
        snap = AccountQuotaService()._collect_grok_quota("grok-orch", _auth())

    weekly = next(b for b in snap.buckets if b.id == "grok.subscription.weekly")
    assert weekly.used_percent == 14.0
    assert weekly.remaining_percent == 86.0
    assert snap.unavailable_reason is None

    names = {b.display_name for b in snap.buckets}
    assert {"GrokChat", "GrokBuild"} <= names, "разбивка по продуктам потеряна"


def test_zero_credits_not_shown_for_subscriber():
    """Нулевые кредиты у подписчика — норма, пустых корзин рисовать не надо."""
    with patch("antigravity_provider.router.quota_collector.urllib.request.urlopen",
               return_value=_billing(0, 0, 0, credit_pct=14.0)):
        snap = AccountQuotaService()._collect_grok_quota("grok-orch", _auth())

    assert not any(b.id == "grok.on_demand" for b in snap.buckets)
