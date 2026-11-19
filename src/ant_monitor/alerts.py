"""Metrics calculations and urgent alert evaluation logic."""

from __future__ import annotations

from ant_monitor.config import MonitorConfig
from ant_monitor.models import (
    AlertEvent,
    AlertKind,
    AlertTrackerState,
    MarketSnapshot,
    NasdaqTradingStatus,
)


def compute_spread_pct(numerator_price: float, reference_price: float) -> float | None:
    """Return relative percentage spread `(numerator - reference) / reference * 100`."""
    if reference_price <= 0:
        return None
    return ((numerator_price - reference_price) / reference_price) * 100.0


def compute_liquidation_buffer(
    mark_price: float,
    liquidation_price: float,
) -> tuple[float, float] | None:
    """Return `(drop_pct_to_liq, usd_distance)` matching `-(mark - liq)/mark*100`."""
    if mark_price <= 0 or liquidation_price <= 0:
        return None
    usd_diff = mark_price - liquidation_price
    drop_pct = -((usd_diff / mark_price) * 100.0)
    return drop_pct, usd_diff


def _can_emit(
    state: AlertTrackerState,
    kind: AlertKind,
    currently_active: bool,
    was_active: bool,
    now_mono: float,
    cooldown_seconds: int,
) -> bool:
    if not currently_active:
        return False
    if not was_active:
        return True
    last_sent = state.last_sent_at.get(kind)
    if last_sent is None:
        return True
    return (now_mono - last_sent) >= cooldown_seconds


def evaluate_urgent_alerts(
    snapshot: MarketSnapshot,
    config: MonitorConfig,
    state: AlertTrackerState,
    now_mono: float,
) -> list[AlertEvent]:
    """Evaluate price threshold breaches and Nasdaq first-print transitions."""
    events: list[AlertEvent] = []

    if snapshot.binance is not None:
        mark = snapshot.binance.mark_price

        is_low = mark < config.alert_low_threshold
        if _can_emit(
            state=state,
            kind=AlertKind.LOW_THRESHOLD,
            currently_active=is_low,
            was_active=state.in_low_zone,
            now_mono=now_mono,
            cooldown_seconds=config.alert_cooldown_seconds,
        ):
            buf = compute_liquidation_buffer(mark, config.liquidation_price)
            buf_text = (
                f" | Запас до ликв.: {buf[0]:.1f}% (${buf[1]:.2f})" if buf else ""
            )
            events.append(
                AlertEvent(
                    kind=AlertKind.LOW_THRESHOLD,
                    title=f"ОПАСНАЯ ЗОНА: Mark Price ниже ${config.alert_low_threshold:.2f}",
                    details=(
                        f"Mark Price: ${mark:.2f} | Ликвидация: ${config.liquidation_price:.2f}"
                        f"{buf_text}"
                    ),
                    snapshot=snapshot,
                )
            )
            state.last_sent_at[AlertKind.LOW_THRESHOLD] = now_mono
        state.in_low_zone = is_low

        is_high = mark > config.alert_high_threshold
        if _can_emit(
            state=state,
            kind=AlertKind.HIGH_THRESHOLD,
            currently_active=is_high,
            was_active=state.in_high_zone,
            now_mono=now_mono,
            cooldown_seconds=config.alert_cooldown_seconds,
        ):
            events.append(
                AlertEvent(
                    kind=AlertKind.HIGH_THRESHOLD,
                    title=f"ПРОБОЙ ВВЕРХ: Mark Price выше ${config.alert_high_threshold:.2f}",
                    details=(
                        f"Mark Price: ${mark:.2f} | Last: ${snapshot.binance.last_price:.2f} "
                        f"(24ч: {snapshot.binance.price_change_percent:+.1f}%)"
                    ),
                    snapshot=snapshot,
                )
            )
            state.last_sent_at[AlertKind.HIGH_THRESHOLD] = now_mono
        state.in_high_zone = is_high

    if snapshot.nasdaq is not None and not state.first_print_announced:
        spot = snapshot.nasdaq
        first_print = spot.status == NasdaqTradingStatus.OPEN and spot.price is not None
        if first_print:
            spread_note = ""
            if snapshot.binance is not None and spot.price is not None:
                spot_spread = compute_spread_pct(
                    snapshot.binance.mark_price, spot.price
                )
                if spot_spread is not None:
                    spread_note = f" | Спред Binance Mark к Nasdaq: {spot_spread:+.2f}%"
            events.append(
                AlertEvent(
                    kind=AlertKind.FIRST_NASDAQ_PRINT,
                    title="ПЕРВЫЙ ПРИНТ НА NASDAQ (IPO Cross открыт)",
                    details=(
                        f"Спот {spot.symbol}: ${spot.price:.2f} "
                        f"(IPO цена ${config.ipo_reference_price:.2f}, источник: {spot.source})"
                        f"{spread_note}"
                    ),
                    snapshot=snapshot,
                )
            )
            state.first_print_announced = True
            state.last_sent_at[AlertKind.FIRST_NASDAQ_PRINT] = now_mono

    return events
