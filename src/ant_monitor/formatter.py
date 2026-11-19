"""Telegram HTML message formatters for scheduled summaries and urgent alerts."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from ant_monitor.alerts import compute_liquidation_buffer, compute_spread_pct
from ant_monitor.config import MonitorConfig
from ant_monitor.models import AlertEvent, MarketSnapshot, NasdaqTradingStatus

MSK_TZ = ZoneInfo("Europe/Moscow")


def _format_msk_time(dt: datetime) -> str:
    return dt.astimezone(MSK_TZ).strftime("%H:%M МСК")


def _format_volume_usd(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.0f}"


def _format_nasdaq_status(status: NasdaqTradingStatus) -> str:
    if status == NasdaqTradingStatus.OPEN:
        return "Торги открыты"
    if status == NasdaqTradingStatus.WAITING_IPO_CROSS:
        return "Ожидание первого принта на Nasdaq (IPO Cross)"
    return "N/A"


def format_scheduled_report(snapshot: MarketSnapshot, config: MonitorConfig) -> str:
    """Format the 5-minute summary Telegram message with graceful N/A fallbacks."""
    time_label = _format_msk_time(snapshot.timestamp)
    lines: list[str] = [f"📊 <b>ANT Monitor</b> | {time_label}", ""]

    b = snapshot.binance
    lines.append(f"🔸 <b>Binance Futures ({html.escape(config.binance_symbol)}):</b>")
    if b is not None:
        index_spread = compute_spread_pct(b.mark_price, b.index_price)
        spread_str = f"{index_spread:+.2f}%" if index_spread is not None else "N/A"
        lines.extend(
            [
                f"• Last Price: <b>${b.last_price:.2f}</b> ({b.price_change_percent:+.1f}%)",
                f"• Mark Price: <b>${b.mark_price:.2f}</b> | Index: ${b.index_price:.2f}",
                f"• Спред к индексу: {spread_str}",
                f"• Объем 24ч: {_format_volume_usd(b.quote_volume)}",
            ]
        )
    else:
        lines.extend(
            [
                "• Last Price: N/A",
                "• Mark Price: N/A | Index: N/A",
                "• Спред к индексу: N/A",
                "• Объем 24ч: N/A",
            ]
        )

    lines.append("")
    n = snapshot.nasdaq
    lines.append(f"🏛 <b>Nasdaq Spot ({html.escape(config.nasdaq_symbol)}):</b>")
    if n is not None:
        status_str = _format_nasdaq_status(n.status)
        if n.price is not None:
            price_str = f"${n.price:.2f}"
            if n.status == NasdaqTradingStatus.WAITING_IPO_CROSS:
                price_str = f"${n.price:.2f} (ориентир IPO)"
        else:
            price_str = "N/A"
        lines.append(f"• Статус: {status_str}")
        lines.append(f"• Цена спота: {price_str}")
        if b is not None and n.price is not None:
            spot_spread = compute_spread_pct(b.mark_price, n.price)
            if spot_spread is not None:
                lines.append(f"• Спред Mark к Nasdaq: {spot_spread:+.2f}%")
    else:
        lines.extend(["• Статус: N/A", "• Цена спота: N/A"])

    lines.append("")
    lines.append(
        f"⚠️ <b>Риск-контроль позиции</b> (вход ~${config.entry_price:.1f} | "
        f"ликв. ${config.liquidation_price:.1f}):"
    )
    if b is not None:
        buf = compute_liquidation_buffer(b.mark_price, config.liquidation_price)
        if buf is None:
            lines.append("• Запас до ликвидации: N/A")
        elif buf[1] <= 0:
            lines.append(f"• Запас до ликвидации: КРИТИЧЕСКИЙ (${buf[1]:.2f})")
        else:
            lines.append(f"• Запас до ликвидации: <b>{buf[0]:.1f}%</b> (${buf[1]:.2f})")
    else:
        lines.append("• Запас до ликвидации: N/A")

    lines.append("")
    lines.append("📰 <b>Свежее за 5 мин:</b>")
    if snapshot.news:
        for item in snapshot.news:
            safe_title = html.escape(item.title)
            if item.link:
                safe_url = html.escape(item.link, quote=True)
                lines.append(f'• <a href="{safe_url}">{safe_title}</a>')
            else:
                lines.append(f"• {safe_title}")
    else:
        lines.append("• Новых заголовков нет")

    return "\n".join(lines)


def format_urgent_alert(event: AlertEvent) -> str:
    """Format an immediate threshold or Nasdaq IPO print alert."""
    time_label = _format_msk_time(event.snapshot.timestamp)
    lines = [
        f"🚨 <b>ANT ALERT</b> | {time_label}",
        f"<b>{html.escape(event.title)}</b>",
        html.escape(event.details),
    ]
    return "\n".join(lines)
