# ANT Monitor

Асинхронный фоновый сервис на Python 3.11+ для мониторинга в реальном времени:
- **Binance USDⓈ-M Futures (`ANTUSDT`)**: `lastPrice`, `priceChangePercent`, `quoteVolume`, `markPrice`, `indexPrice`, `lastFundingRate`.
- **Nasdaq Spot (`NASDAQ:ANT`)**: котировки через `yfinance` (бесплатно, с распознаванием состояния `IPO Cross` / `$83.00`) и резервный fallback через Finnhub / Polygon.io.
- **Новости IPO (`Google News RSS`)**: фильтрация заголовков за последние 30 минут с дедупликацией по SHA-256 хэшу URL/заголовка.
- **Telegram-уведомления**:
  - Первый отчёт — сразу при старте (< 5 сек).
  - Плановая сводка — строго каждые **5 минут** (`300s`, без дрейфа таймера).
  - Экстренные алерты — отдельная проверка каждые **45 секунд**:
    - падение `markPrice` ниже `ALERT_LOW_THRESHOLD` (`$85.00`);
    - пробой `markPrice` выше `ALERT_HIGH_THRESHOLD` (`$110.00`);
    - фиксация **первого принта на Nasdaq** (отличие цены от `$83.00` или появление минутных свечей).

## Установка и запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --no-cache-dir -e ".[dev]"

cp .env.example .env
# Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env
```

### Проверка без отправки в Telegram (`--dry-run`)

```bash
python -m ant_monitor --once --dry-run
```

### Запуск в фоне через `tmux`

```bash
tmux new-session -d -s ant-monitor 'cd /path/to/ant-monitor && .venv/bin/python -m ant_monitor'
```

### Запуск в фоне через `systemd` (с автоперезапуском)

```bash
sudo cp deploy/ant-monitor.service /etc/systemd/system/ant-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now ant-monitor
sudo journalctl -u ant-monitor -f
```

### Облачный запуск на GitHub Actions (только с self-hosted non-US runner)

В репозитории есть workflow [`.github/workflows/monitor.yml`](.github/workflows/monitor.yml) (`workflow_dispatch`, а `schedule` закомментирован по умолчанию). Стандартные раннеры GitHub находятся в США, поэтому Binance Futures отдаёт им `HTTP 451`. Для запуска через Actions используйте self-hosted runner в ЕС/Азии с добавленными секретами:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Переменные окружения (`.env`)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Токен Telegram-бота (обязательно без `--dry-run`) |
| `TELEGRAM_CHAT_ID` | — | ID чата / канала Telegram |
| `ENTRY_PRICE` | `106.5` | Цена входа для отображения в риске |
| `LIQUIDATION_PRICE` | `77.0` | Цена ликвидации позиции |
| `ALERT_LOW_THRESHOLD` | `85.0` | Нижний порог экстренного алерта |
| `ALERT_HIGH_THRESHOLD` | `110.0` | Верхний порог экстренного алерта |
| `IPO_REFERENCE_PRICE` | `83.0` | Цена размещения IPO до первого принта |
| `POLL_INTERVAL_SECONDS` | `300` | Интервал планового отчёта (сек) |
| `ALERT_INTERVAL_SECONDS` | `45` | Интервал проверки экстренных триггеров (сек) |
| `HTTP_TIMEOUT_SECONDS` | `5.0` | Максимальный таймаут каждого HTTP-запроса (<= 5 сек) |
| `FINNHUB_API_KEY` | `""` | Опциональный резервный ключ Finnhub |
| `POLYGON_API_KEY` | `""` | Опциональный резервный ключ Polygon.io |
| `PROXY_URL` | `""` | Опциональный HTTP/HTTPS proxy для `httpx` |
| `LOG_FILE` | `monitor.log` | Файл логов с ротацией (5 МБ × 5 файлов) |

## Тесты

```bash
pytest
```
