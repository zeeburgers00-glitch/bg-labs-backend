#!/usr/bin/env python3
"""voiceprint.py - read your own transcripts and measure how you actually talk.

    python3 voiceprint.py best-video.txt
    python3 voiceprint.py vid1.srt vid2.srt vid3.txt      # merge several, the more the better
    python3 voiceprint.py *.txt --json

Point it at the transcripts of your best videos (not your scripts - the words you actually said) and
it measures the things a voice.md should capture but that you cannot see about yourself: your mean
sentence length, your filler rate, the distinctive words you lean on, and the hype words to flag.
It does not write your voice.md - it gives yt-voice the measurements to write it from.

  SENTENCE LENGTH   short and punchy, or long and winding. A script that fights this is unreadable
                    out loud.
  FILLER RATE       how much "like / basically / literally / you know" you run - fine to keep some,
                    useful to know the baseline.
  SIGNATURE WORDS   content words you use far more than normal speech would. These are your tics.
                    Keep them; they are what makes a script sound like you and not like a blog.
  HYPE WORDS        "insane / crazy / game-changer" you already say - decide which stay and which
                    go in the banned list.

IT MEASURES, IT DOES NOT JUDGE. A long mean sentence is not worse than a short one. A high filler
rate is not a grade. This is a mirror, so the script a skill writes you is readable on the first
take instead of the fourth.
"""
import argparse, json, os, re, sys
from collections import Counter

STOP = set("""a an and are as at be been but by for from had has have he her his i if in is it its
of on or our she that the their them they this to was we were what when which who will with you your
yours me my mine us do does did not no yes so just can could would should now then there here all
about into over after before out up down off than too very can't dont don't im i'm it's thats
that's youre you're were we're they're he's she's""".split())
FILLER = {"like", "basically", "literally", "actually", "really", "just", "you know", "i mean",
          "sort of", "kind of", "um", "uh", "right", "okay", "so", "well", "stuff", "things"}
HYPE = {"insane", "crazy", "amazing", "incredible", "huge", "massive", "game-changer", "gamechanger",
        "mindblowing", "unbelievable", "epic", "ultimate", "revolutionary", "perfect", "literally"}

TS = re.compile(r"^\s*\d+\s*$|-->|\d{1,2}:\d{2}")


def read(path):
    lines = []
    for raw in open(path, encoding="utf-8", errors="replace").read().splitlines():
        if TS.search(raw) or not raw.strip():
            continue
        lines.append(raw.strip())
    return " ".join(lines)


def analyse(text):
    low = text.lower()
    tokens = re.findall(r"[a-z']+", low)
    n = len(tokens)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    slens = [len(re.findall(r"[a-z']+", s.lower())) for s in sentences] or [0]
    mean_sentence = sum(slens) / len(slens)

    filler_hits = 0
    for f in FILLER:
        filler_hits += len(re.findall(r"\b" + re.escape(f) + r"\b", low)) if " " in f else tokens.count(f)
    filler_rate = filler_hits / n * 100 if n else 0

    content = [t for t in tokens if t not in STOP and len(t) > 3]
    freq = Counter(content)
    # signature = frequent content words, normalised by how long they are (longer = more distinctive)
    signature = [w for w, _ in sorted(freq.items(), key=lambda kv: -(kv[1] * (1 + len(kv[0]) / 10)))[:15]]
    hype_present = sorted({t for t in tokens if t in HYPE})

    return {
        "words": n,
        "sentences": len(sentences),
        "mean_sentence_words": round(mean_sentence, 1),
        "filler_rate_pct": round(filler_rate, 2),
        "signature_words": signature,
        "hype_words_you_already_use": hype_present,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcripts", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    files, as_json = args.transcripts, args.json
    try:
        text = " ".join(read(f) for f in files)
    except OSError as exc:
        parser.error(str(exc))
    if not text.strip():
        parser.error("transcripts contain no spoken text")
    r = analyse(text)
    if as_json:
        print(json.dumps(r, indent=1))
        return
    print(f"\n  {len(files)} transcript(s)   {r['words']:,} words   {r['sentences']} sentences\n")
    print(f"    mean sentence     {r['mean_sentence_words']} words  "
          + ("short, punchy" if r['mean_sentence_words'] < 12 else
             "long, winding - write to it, do not fight it" if r['mean_sentence_words'] > 20 else "mid"))
    print(f"    filler rate       {r['filler_rate_pct']}%  of all words")
    print(f"    signature words   {', '.join(r['signature_words'][:12])}")
    print(f"    hype you use      {', '.join(r['hype_words_you_already_use']) or '(none - clean)'}")
    print("\n  hand these to yt-voice to write your chosen profile file in your actual voice.\n")


if __name__ == "__main__":
    main()
