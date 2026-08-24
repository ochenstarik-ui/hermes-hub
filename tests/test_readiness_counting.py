"""Роль на резерве считается работающей.

Дефект со скриншота владельца: заголовок «Ролей в строю: 0/6», а ниже
шесть предупреждений вида «роль работает через резервный аккаунт». Пять
ролей исправно отвечали, а интерфейс сообщал, что не работает ни одна.

roles_ready считал только роли со здоровым ОСНОВНЫМ профилем. Роль,
обслуживаемая резервом, попадала в degraded, но не в ready. Это ошибка в
худшую сторону: пользователь видит отказ там, где всё работает.
"""

from __future__ import annotations

from antigravity_provider.router.unified_health import _plural_roles


def test_role_on_fallback_counts_as_ready():
    """Роль, у которой жив резерв, обязана попадать в «в строю»."""
    import inspect

    from antigravity_provider.router import unified_health

    src = inspect.getsource(unified_health.UnifiedHealthService.get_system_readiness)
    marker = "if has_working_fallback:"
    assert marker in src
    tail = src.split(marker, 1)[1].split("else:", 1)[0]
    assert "roles_ready += 1" in tail, (
        "роль на резерве снова не засчитывается как работающая"
    )
    assert "degraded_roles += 1" in tail, (
        "признак деградации потерян — состояние должно оставаться отличимым"
    )


def test_plural_roles_agrees_with_number():
    """«Есть 1 ролей» — так по-русски не пишут."""
    assert _plural_roles(1) == "1 роль"
    assert _plural_roles(2) == "2 роли"
    assert _plural_roles(4) == "4 роли"
    assert _plural_roles(5) == "5 ролей"
    assert _plural_roles(11) == "11 ролей"
    assert _plural_roles(21) == "21 роль"
    assert _plural_roles(112) == "112 ролей"
