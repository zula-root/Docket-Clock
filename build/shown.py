#!/usr/bin/env python3
"""List every sentence the Docket Clock shows.

Reads data/HH.json and writes build/shown.txt: each minute's sentence and its
citation, in clock order, so that anyone can read all of them in one sitting.

usage: python3 build/shown.py

Run it after curate.py, so the list always matches the clock.
"""
import json, os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lines = ["Every sentence the Docket Clock shows, in clock order. One per minute.", ""]
for hour in range(24):
    with open(os.path.join(root, "data", "%02d.json" % hour), encoding="utf-8") as f:
        minutes = json.load(f)
    for minute in sorted(minutes):
        for x in minutes[minute]:
            where = " ".join(p for p in (x.get("ct"), x.get("y")) if p)
            lines += ["%s  %s" % (minute, x["q"]), "       %s, %s (%s)" % (x["c"], x["cite"], where), ""]
with open(os.path.join(root, "build", "shown.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("build/shown.txt: %d sentences" % ((len(lines) - 2) // 3))
