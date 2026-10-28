#!/usr/bin/env python3
"""ratecard.py - illustrative sponsorship arithmetic from your view assumptions.

    python3 ratecard.py --views 12000 --niche tech
    python3 ratecard.py --views 12000 --niche finance --placement integrated --json

Sponsorship is priced on a CPM - a price per thousand views - that varies by niche because a
thousand finance viewers are worth more to an advertiser than a thousand gaming viewers. This takes
your realistic per-video views (use the median of your last 10, NOT your best) and a niche, and
returns a low/mid/high band plus the three placement tiers advertisers actually buy.

  niches:     finance, b2b, tech, education, health, marketing, general, lifestyle, gaming, entertainment
  placements: integrated (60-90s mid-roll, the default), dedicated (whole video), mention (shout-out)

THESE ARE ILLUSTRATIVE USD ASSUMPTIONS, NOT VERIFIED MARKET RATES. Real deals vary
with geography, format, usage rights, exclusivity and audience fit. The built-in
CPMs are not sourced or current quotes and are not calibrated for Shorts.
Set negotiation boundaries using actual costs and comparable offers.
"""
import argparse, json, math, sys

# Legacy illustrative USD CPM assumptions; not verified market benchmarks.
CPM = {
    "finance":       (25, 45, 70),
    "b2b":           (25, 40, 65),
    "tech":          (18, 30, 50),
    "education":     (15, 25, 40),
    "health":        (18, 30, 45),
    "marketing":     (20, 35, 55),
    "general":       (12, 20, 30),
    "lifestyle":     (10, 18, 28),
    "gaming":        (8, 14, 22),
    "entertainment": (6, 12, 20),
}
PLACEMENT = {
    "mention":    0.4,
    "integrated": 1.0,
    "dedicated":  2.2,
}


def card(views, niche, placement):
    niche = niche.lower()
    placement = placement.lower()
    if niche not in CPM or placement not in PLACEMENT:
        raise ValueError("unknown niche or placement")
    base = CPM[niche]
    mult = PLACEMENT.get(placement, 1.0)
    low, mid, high = (round(views / 1000 * c * mult) for c in base)
    return {"views": views, "niche": niche, "placement": placement,
            "low": low, "mid": mid, "high": high, "currency": "USD",
            "assumption": "Illustrative unverified CPM bands; not a quote or a Shorts benchmark."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--views", type=float, required=True)
    parser.add_argument("--niche", choices=CPM, default="general")
    parser.add_argument("--placement", choices=[*PLACEMENT, "all"], default="integrated")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    views, niche, placement, as_json = args.views, args.niche, args.placement, args.json
    if not math.isfinite(views) or views < 0:
        parser.error("--views must be a finite nonnegative number")

    if placement == "all":
        rows = [card(views, niche, p) for p in ("mention", "integrated", "dedicated")]
    else:
        rows = [card(views, niche, placement)]

    if as_json:
        print(json.dumps(rows if len(rows) > 1 else rows[0], indent=1))
        return

    print(f"\n  {int(views):,} views/video   niche: {rows[0]['niche']}\n")
    for r in rows:
        print(f"    {r['placement']:<12} ${r['low']:>6,}  -  ${r['mid']:>6,}  -  ${r['high']:>6,}")
    print("\n    Illustrative USD assumptions only; not verified market rates or a Shorts benchmark.")
    print("    Compare actual offers, production costs, usage rights and audience fit.\n")


if __name__ == "__main__":
    main()
