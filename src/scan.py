#!/usr/bin/env python3
import os
import json
from dataclasses import asdict
from pathlib import Path

from thinker import PinkyTracker
from alpaca_client import Bar


def digest_sample(filepath: Path):
    print(f"========================= {filepath} ===")
    symbol, _ = filepath.stem.split("-", maxsplit=1)
    tracer = PinkyTracker(symbol=symbol, wix=5)

    with open(filepath) as datafile:
        raw_data = json.loads(datafile.read())

    bars = [Bar.from_json(data) for data in raw_data]

    tracer.feed(map(asdict, bars))
    df = tracer.analyze()

    renko_df, size = tracer.compute_renko_data(df)
    events = tracer.run_mariashi_strategy(renko_df)

    charts_path = os.getenv("OUTPUTS_PATH", "charts")
    tracer.save_renko_chart(renko_df, events, size, path=charts_path, suffix="1h")


def main():
    data_folder = Path(os.getenv("PRIVATE_CACHE"))
    for datafile in data_folder.glob("*.json"):
        digest_sample(datafile)

    print("done")


if __name__ == "__main__":
    main()
