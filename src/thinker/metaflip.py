#!/usr/bin/env python3
import json
from collections import namedtuple
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import IntEnum
from typing import Any, ClassVar

FIBONACCI = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233)
# for 30 mins candlesticks
DAY_RANGE = 15
WEEK_RANGE = 5 * DAY_RANGE
MONTH_RANGE = 4 * WEEK_RANGE
QUARTER_RANGE = 3 * MONTH_RANGE


RenkoBrick = namedtuple("RenkoBrick", ["timestamp", "open", "close", "direction"])


class ThinkEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if is_dataclass(o):
            return asdict(o)
        elif isinstance(o, Decimal):
            return float(o)
        elif isinstance(o, datetime):
            return dict(iso_datetime=o.isoformat())
        return super().default(o)

    @staticmethod
    def object_hook(obj):
        if iso_tm := obj.get("iso_datetime"):
            return datetime.fromisoformat(iso_tm)
        return obj


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
