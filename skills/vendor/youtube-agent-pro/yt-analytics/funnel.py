#!/usr/bin/env python3
"""funnel.py - flag analytics worth investigating, without claiming a cause.

    python3 funnel.py --impressions 42000 --ctr 3.1 --avd 2:10 --length 9:40 --json
    python3 funnel.py stats.csv --json
    python3 funnel.py --format shorts --avd 28 --length 30 --views 1300 --json

Long-form bands (1,000 impressions, 4% CTR and 50% viewed) are illustrative
heuristics, not universal targets or evidence of causation. Compare similar
videos, ages and traffic sources. Shorts feed distribution is not an impressions
CTR funnel: use --format shorts and inspect engaged views, stayed-to-watch,
retention and traffic sources in Studio. Never substitute views for engaged views.
"""
import argparse
import csv
import json
import math
import re


def number(value):
    if value is None or str(value).strip() in ("", "-", "—", "N/A", "n/a"):
        return None
    result = float(str(value).strip().replace(",", "").removesuffix("%"))
    if not math.isfinite(result) or result < 0:
        raise ValueError("metrics must be finite, nonnegative numbers")
    return result


def dur(value):
    """Accept seconds, mm:ss or hh:mm:ss; preserve missing values."""
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    if ":" not in value:
        return number(value)
    parts = [number(part) for part in value.split(":")]
    if len(parts) not in (2, 3) or any(part is None for part in parts) or any(part >= 60 for part in parts[1:]):
        raise ValueError("duration must be seconds, mm:ss or hh:mm:ss")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def diagnose(impr, ctr, avd, length, views=None, video_format="long"):
    if ctr is not None and ctr > 100:
        raise ValueError("CTR must be between 0 and 100 percent")
    if length == 0:
        raise ValueError("video length must be positive")
    pct = avd / length * 100 if avd is not None and length is not None else None
    estimated = round(impr * ctr / 100) if impr is not None and ctr is not None else None
    out = {"format": video_format, "impressions": impr, "ctr": ctr,
           "avd_s": avd, "length_s": length,
           "avg_pct_viewed": round(pct, 1) if pct is not None else None,
           "views": views, "views_est": views if views is not None else estimated,
           "estimated_views_from_impressions": estimated,
           "warnings": ["Heuristic review priorities, not a causal diagnosis or a forecast."]}
    if views is None and estimated is not None:
        out["warnings"].append("Impressions × CTR estimates only views from counted impressions, not total video views.")
    missing = [name for name, val in (("impressions", impr), ("ctr", ctr), ("avd", avd), ("length", length)) if val is None]
    out["missing_metrics"] = missing
    if video_format == "shorts":
        out["missing_metrics"] = [name for name, val in (("avd", avd), ("length", length)) if val is None]
        out["context_required"] = ["engaged_views", "stayed_to_watch", "shorts_feed_distribution", "traffic_sources"]
        out.update(links=[], binding_constraint=None, status="shorts_requires_context",
                   verdict="Long-form CTR and retention bands are not applied to Shorts. Compare engaged views, stayed-to-watch, retention and traffic sources with similar Shorts.")
        return out
    links = []
    if impr is not None:
        links.append(("IMPRESSIONS", impr >= 1000, 1 - min(1, impr / 1000),
                      f"{impr:,.0f} counted impressions: compare video age and traffic sources before judging reach."))
    if ctr is not None:
        links.append(("CTR", ctr >= 4, max(0, min(1, (4 - ctr) / 4)),
                      f"{ctr:.1f}% CTR: compare like-for-like traffic sources; review the title and thumbnail with yt-package and yt-thumbnail."))
    if pct is not None:
        links.append(("RETENTION", pct >= 50, max(0, min(1, (50 - pct) / 50)),
                      f"{pct:.1f}% average viewed: compare similar video lengths and inspect the retention curve with yt-retention."))
    out["links"] = [{"name": name, "ok": ok, "note": note} for name, ok, _, note in links]
    broken = [link for link in links if not link[1]]
    out["binding_constraint"] = None
    if not links:
        out.update(status="insufficient_data", verdict="No usable funnel metrics supplied; no performance conclusion is possible.")
    elif broken:
        worst = max(broken, key=lambda link: link[2])
        out.update(status="review", binding_constraint=worst[0], verdict=worst[3])
    else:
        out.update(status="partial_data" if missing else "within_heuristic_bands",
                   verdict="Available metrics are within the illustrative bands; this does not prove the video is performing well.")
    return out


def from_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = {re.sub(r"\s+", " ", h.strip().lower()): h for h in (reader.fieldnames or [])}
        # Exact semantic aliases avoid treating AVD as the video's duration, or CTR
        # as impressions when 'Impressions click-through rate' precedes 'Impressions'.
        def pick(*names):
            return next((headers[name] for name in names if name in headers), None)
        cols = {
            "impr": pick("impressions"),
            "ctr": pick("impressions click-through rate (%)", "impressions click-through rate", "click-through rate (%)", "click-through rate", "ctr", "ctr (%)"),
            "avd": pick("average view duration", "average view duration (seconds)", "avg view duration", "avd"),
            "length": pick("duration", "duration (seconds)", "video duration", "video length", "length", "length (seconds)"),
            "views": pick("views"),
            "title": pick("video title", "title", "content", "video"),
        }
        for line, row in enumerate(reader, 2):
            def value(key):
                return row.get(cols[key]) if cols[key] else None
            try:
                yield (value("title") or f"row {line}", number(value("impr")), number(value("ctr")),
                       dur(value("avd")), dur(value("length")), number(value("views")))
            except ValueError as exc:
                raise ValueError(f"CSV row {line}: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?")
    parser.add_argument("--format", choices=("long", "shorts"), default="long")
    for name in ("impressions", "ctr", "avd", "length", "views"):
        parser.add_argument("--" + name)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.csv and all(getattr(args, name) is None for name in ("impressions", "ctr", "avd", "length", "views")):
        parser.error("provide a CSV or at least one metric")
    try:
        rows = list(from_csv(args.csv)) if args.csv else [(None, number(args.impressions), number(args.ctr), dur(args.avd), dur(args.length), number(args.views))]
        if not rows:
            parser.error("CSV contains no data rows")
        results = []
        for label, impr, ctr, avd, length, views in rows:
            result = diagnose(impr, ctr, avd, length, views, args.format)
            if label:
                result["label"] = label
            results.append(result)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=1, allow_nan=False))
        return
    for result in results:
        print("\n" + (result.get("label") or "Video") + ": " + result["verdict"])
        for link in result["links"]:
            print(f"  {link['name']}: {link['note']}")
        for warning in result["warnings"]:
            print("  Note: " + warning)


if __name__ == "__main__":
    main()
