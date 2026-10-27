#!/usr/bin/env python3
"""ideascore.py - score a video idea before you spend a week shooting it.

    python3 ideascore.py ideas.txt             # one idea per line, ranked
    python3 ideascore.py --idea "one line"     # score a single idea
    python3 ideascore.py ideas.txt --json      # machine-readable

An idea is scored on four axes, each 0-100, and a verdict that is 60% the mean and 40% the weakest
axis. The weakest-link weighting is the same choice hookscore.py makes: an idea that is searchable,
specific and broad but has no stake is an idea nobody clicks, and averaging hides the dead axis.

  SEARCH      does it answer a query a real person types? question words, a concrete noun, intent.
  SPECIFIC    a number, a name, a timeframe - or an adjective doing the work a fact should.
  REACH       is the audience bigger than you? "for react devs" is narrow, "for anyone" is nobody.
  DURABLE     evergreen earns views for years; a dated take earns them for a week. Neither is wrong,
              but you should know which one you just greenlit.

WHAT THIS IS NOT. It does not know your niche, your competition, or whether the idea has been done.
It reads the words of the idea, not the market. A high score means the idea is well-shaped; it is
not a demand forecast. Pair it with yt-viral, which reads what is actually working.
"""
import argparse, json, os, re, sys

QUESTION = re.compile(r"\b(how|why|what|which|when|where|should|can|is|are|do|does|will)\b", re.I)
INTENT = re.compile(r"\b(guide|tutorial|review|vs|versus|best|fix|stop|avoid|build|make|setup|"
                    r"explained|mistakes|beginners?|without|using|in \d+)\b", re.I)
VAGUE = {"amazing","incredible","insane","crazy","huge","massive","ultimate","best","powerful",
         "secret","revolutionary","epic","perfect","everything","stuff","things","content"}
NUMBER = re.compile(r"\b(\d[\d,.]*\s?(%|k|m|x|hrs?|hours?|mins?|minutes?|days?|weeks?|months?|years?|dollars?|\$)?)\b", re.I)
TIMELY = re.compile(r"\b(202\d|today|this week|this month|right now|new|latest|just|update|"
                    r"breaking|announced|released|beta|v\d)\b", re.I)
EVERGREEN = re.compile(r"\b(how to|guide|explained|beginners?|basics|fundamentals|101|complete|"
                       r"ever|always|principles?|mistakes)\b", re.I)
NARROW = re.compile(r"\bfor (react|vue|rust|haskell|niche|enterprise|senior|advanced)\b", re.I)
TOO_BROAD = re.compile(r"\bfor (everyone|anyone|all|people)\b", re.I)


def words(t):
    return re.findall(r"[a-z0-9'$%]+", t.lower())


def search(t):
    s = 20
    if QUESTION.search(t):
        s += 26
    s += min(30, 15 * len(INTENT.findall(t)))
    # a bare topic with no verb is a title, not a query
    if not re.search(r"\b(how|why|what|guide|review|vs|fix|build|make|stop)\b", t, re.I):
        s -= 12
    return max(0, min(100, s))


def specific(t):
    w = words(t)
    if not w:
        return 0
    nums = len(NUMBER.findall(t))
    vague = sum(1 for x in w if x in VAGUE)
    proper = sum(1 for x in t.split()[1:] if x[:1].isupper() and len(x) > 2)
    return max(0, min(100, 32 + nums * 20 + proper * 8 - vague * 18))


def reach(t):
    s = 55
    if TOO_BROAD.search(t):
        s -= 30                       # "for everyone" addresses nobody
    if NARROW.search(t):
        s -= 10                       # narrow is fine, just capped
    if re.search(r"\bfor \w+", t, re.I):
        s += 15                       # names an audience at all
    return max(0, min(100, s))


def durable(t):
    ever = len(EVERGREEN.findall(t))
    timely = len(TIMELY.findall(t))
    return max(0, min(100, 50 + ever * 16 - timely * 20))


AXES = [("SEARCH", search), ("SPECIFIC", specific), ("REACH", reach), ("DURABLE", durable)]
FIX = {
    "SEARCH": "frame it as the question someone types - start with how/why/what",
    "SPECIFIC": "put a number, a name or a timeframe in it",
    "REACH": "name one audience, not 'everyone' and not a sub-niche of a sub-niche",
    "DURABLE": "if it is a timely take, say so - it will earn for a week, not a year",
}


def score(t):
    parts = {n: fn(t) for n, fn in AXES}
    vals = list(parts.values())
    verdict = round(0.6 * (sum(vals) / len(vals)) + 0.4 * min(vals))
    life = "timely" if durable(t) < 45 else "evergreen" if durable(t) > 62 else "mixed"
    return parts, verdict, life


def band(v):
    return "STRONG" if v >= 70 else "WORKABLE" if v >= 52 else "WEAK"


def report(t, parts, verdict, life):
    print(f"\n  {t.strip()}")
    print(f"  {'-' * min(72, max(20, len(t.strip())))}")
    for k, v in parts.items():
        print(f"    {k:<10} {v:3d}  {'#' * (v // 5)}")
    print(f"    {'VERDICT':<10} {verdict:3d}  {band(verdict)}   ({life})")
    low = min(parts, key=parts.get)
    print(f"    weakest    {low} - {FIX[low]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?")
    parser.add_argument("--idea")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    as_json = args.json
    if (args.file is None) == (args.idea is None):
        parser.error("provide a text file or --idea, not both")
    try:
        lines = [args.idea] if args.idea is not None else open(args.file, encoding="utf-8").read().splitlines()
    except OSError as exc:
        parser.error(str(exc))
    lines = [line for line in lines if line.strip()]
    if not lines:
        parser.error("provide at least one nonempty idea")
    out = []
    for t in lines:
        parts, verdict, life = score(t)
        out.append({"idea": t.strip(), "axes": parts, "verdict": verdict,
                    "band": band(verdict), "life": life})
    out.sort(key=lambda r: -r["verdict"])
    if as_json:
        print(json.dumps(out, indent=1))
        return
    for r in out:
        report(r["idea"], r["axes"], r["verdict"], r["life"])
    if len(out) > 1:
        print(f"\n  pick: {out[0]['idea'].strip()}  ({out[0]['verdict']}, {out[0]['band']})\n")


if __name__ == "__main__":
    main()
