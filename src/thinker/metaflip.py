#!/usr/bin/env python3
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum
from typing import ClassVar

# minute candlesticks
FAST_CYCLE = 120
QUARTER_DAY_CYCLE = 360
HALF_DAY_CYCLE = 720

# for hourly candlesticks
DAILY_CYCLE = 24
WEEKLY_CYCLE = 7 * DAILY_CYCLE
FULL_CYCLE = 4 * WEEKLY_CYCLE


FIBONACCI = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233)


@dataclass
class CandleStick:
    AS_DTYPE: ClassVar[dict[str, str]] = dict(
        open="float",
        high="float",
        low="float",
        close="float",
        volume="float",
        trades="int",
        vw_price="float",
    )

    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int
    vw_price: Decimal


class MarketSignal(IntEnum):
    HOLD = 0
    BUY = 1
    SELL = 2
