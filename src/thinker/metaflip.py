#!/usr/bin/env python3
import json
import sys
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


class ThinkEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if is_dataclass(o):
            data_obj = asdict(o)
            data_obj["_cls_name"] = type(o).__name__
            return data_obj
        elif isinstance(o, Decimal):
            return float(o)
        elif isinstance(o, datetime):
            return dict(iso_datetime=o.isoformat())
        return super().default(o)

    @staticmethod
    def object_hook(obj):
        if iso_tm := obj.get("iso_datetime"):
            return datetime.fromisoformat(iso_tm)
        elif classname := obj.pop("_cls_name", None):
            cls = getattr(sys.modules[__name__], classname)
            return cls(**obj)
        return obj


@dataclass
class RenkoState:
    high: Decimal
    low: Decimal
    abs_high: Decimal
    abs_low: Decimal
    last_index: datetime


@dataclass
class RenkoBrick:
    timestamp: int
    open: Decimal
    close: Decimal
    direction: str


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
