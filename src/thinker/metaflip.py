#!/usr/bin/env python3
import json
from dataclasses import asdict, dataclass, is_dataclass
from decimal import Decimal
from enum import IntEnum
from typing import Any, ClassVar

# for 30 mins candlesticks
DAY_RANGE = 15
WEEK_RANGE = 5 * DAY_RANGE
MONTH_RANGE = 4 * WEEK_RANGE
QUARTER_RANGE = 3 * MONTH_RANGE

# minute candlesticks
FAST_CYCLE = MONTH_RANGE
FULL_CYCLE = QUARTER_RANGE


FIBONACCI = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233)


class DataclassEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if is_dataclass(o):
            return asdict(o)
        return super().default(o)


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
