# Hermes Hub — UI Design System & Design Tokens

Этот документ регламентирует структуру дизайн-токенов, поведение UI-компонентов и правила верстки нативного Windows-приложения Hermes Hub.

---

## 1. Токены цветовой палитры (Color Tokens)

```python
# Базовые цвета
COLOR_PRIMARY       = "#0F1510"  # Глубокий темный фон окна
COLOR_DARK          = "#1A2A1F"  # Фон боковой панели и модальных окон
COLOR_SECONDARY     = "#2F4A36"  # Карточки и рабочие поверхности
COLOR_LIGHT          = "#F7F1E3"  # Основной цвет текста (Warm Ivory)
COLOR_ACCENT        = "#CDAA64"  # Фирменное античное золото

# Семантические токены поверхностей
TOKEN_BG            = "#0F1510"
TOKEN_BG_SIDEBAR    = "#142018"
TOKEN_SURFACE       = "#1D3123"
TOKEN_SURFACE_HOVER = "#274230"
TOKEN_SURFACE_ACTIVE= "#31543D"
TOKEN_BORDER        = "#2F4A36"
TOKEN_BORDER_SUBTLE = "#1F3526"
TOKEN_BORDER_ACCENT = "#CDAA64"

# Семантические токены текста
TOKEN_TEXT_PRIMARY   = "#F7F1E3"
TOKEN_TEXT_SECONDARY = "#C5BEAF"
TOKEN_TEXT_MUTED     = "#7D8F81"
TOKEN_TEXT_ON_ACCENT = "#0F1510"

# Акцентные токены
TOKEN_ACCENT         = "#CDAA64"
TOKEN_ACCENT_HOVER   = "#DCBE7D"
TOKEN_ACCENT_PRESSED = "#BA954E"
TOKEN_ACCENT_DIM     = "#3D3522"

# Статусные токены
TOKEN_SUCCESS        = "#2E7D32"  # Healthy
TOKEN_WARNING        = "#D97706"  # Quota Warning / Cooldown
TOKEN_ERROR          = "#DC2626"  # Dead / Error / Quota Exhausted
TOKEN_INFO           = "#2563EB"  # Info / Neutral
TOKEN_AUTH_REQUIRED  = "#D97706"  # Auth needed
TOKEN_DISABLED       = "#5A6B5D"  # Disabled
TOKEN_MAIN_BADGE     = "#CDAA64"  # Main profile
TOKEN_ORCH_BADGE     = "#E5C158"  # Orchestrator badge
```

---

## 2. Шкалы отступов, радиусов и размеров (Spacing & Layout Scales)

### 2.1. Отступы (Spacing Scale)
- `space_xs` = 4 px
- `space_sm` = 8 px
- `space_md` = 12 px
- `space_lg` = 16 px
- `space_xl` = 24 px
- `space_2xl` = 32 px

### 2.2. Радиусы скругления (Corner Radius Scale)
- `radius_sm` = 6 px (кнопки, бейджи, поля ввода)
- `radius_md` = 10 px (карточки, модальные фреймы)
- `radius_lg` = 14 px (главные панели, карточки метрик)
- `radius_full` = 999 px (круглые индикаторы, аватары)

### 2.3. Высоты элементов управления (Control Heights)
- `height_btn_sm` = 28 px
- `height_btn_md` = 36 px
- `height_btn_lg` = 44 px
- `height_nav_item` = 42 px
- `height_header` = 56 px
- `height_statusbar` = 28 px
- `width_sidebar` = 220 px

---

## 3. Библиотека компонентов (Component Specifications)

### 3.1. `HubButton`
Варианты:
1. **Primary**: Фон `TOKEN_ACCENT`, текст `TOKEN_TEXT_ON_ACCENT` (Bold), Hover: `TOKEN_ACCENT_HOVER`. Используется для главных действий («+ Добавить аккаунт», «Сохранить»).
2. **Secondary**: Фон `TOKEN_SURFACE`, рамка `TOKEN_BORDER`, текст `TOKEN_TEXT_PRIMARY`, Hover: `TOKEN_SURFACE_HOVER`. Используется для второстепенных действий («Тест», «Сделать основным»).
3. **Ghost**: Фон `transparent`, текст `TOKEN_TEXT_PRIMARY`, Hover: `TOKEN_SURFACE`. Используется для навигации и тулбаров.
4. **Danger**: Фон `#4A1E1E`, рамка `#7A2E2E`, текст `#FFB0B0`, Hover: `#6A2828`. Для необратимых действий («Удалить аккаунт», «Сброс»).

### 3.2. `HubCard`
- Фон: `TOKEN_SURFACE` (`#1D3123`)
- Рамка: 1 px `TOKEN_BORDER` (`#2F4A36`)
- Скругление: `radius_md` (10 px)
- Padding: 12–16 px
- Состояние hover: подсветка рамки или легкое осветление фона `TOKEN_SURFACE_HOVER`.

### 3.3. `HubStatusBadge`
- Компактный бейдж с цветной точкой-индикатором и подписью:
  - 🟢 Здоровый (`#2E7D32`)
  - 🟡 Quota Warning / Cooldown (`#D97706`)
  - 🔴 Ошибка / Quota Exhausted (`#DC2626`)
  - 🔑 Требуется вход (`#D97706`)
  - ⭐ MAIN (`#CDAA64`)

### 3.4. `HubMetricCard`
- Верх: маленькая иконка + заголовок метрики (`TOKEN_TEXT_MUTED`)
- Центр: крупное значение (24–28pt Bold, `TOKEN_TEXT_PRIMARY` или `TOKEN_ACCENT`)
- Низ: пояснительный статус или прогресс

### 3.5. `HubSidebar`
- Фиксированная ширина 220 px
- Верх: брендинг Hermes Hub (знак + название)
- Навигация: 9 разделов с line icons и золотым индикатором активного элемента:
  1. Главная (`dashboard`)
  2. Команда Hermes (`team`)
  3. Аккаунты (`accounts`)
  4. Провайдеры (`providers`)
  5. Маршрутизация (`routing`)
  6. Состояние системы (`health`)
  7. Журнал (`logs`)
  8. Настройки (`settings`)
  9. О программе (`about`)
- Низ: кнопка «🔄 Обновить данные»

### 3.6. `HubModal` & Диалоги
- Затемняющий фон
- Центральная карточка с акцентной рамкой `TOKEN_ACCENT` (1 px)
- Понятный человеческий язык для действий: «Добавить аккаунт», «Автоматическое распределение ролей», «Подтверждение действия».
