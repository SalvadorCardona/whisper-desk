"""Names said in a style ("camel case user name"), before and after they are written in it.

    python3 bench/casing/measure.py              # on the written sentences
    python3 bench/casing/measure.py --audio      # through faster-whisper

Two figures: the names of the corpus written exactly as expected (userName,
created_at, MAX_RETRIES), and the error rate on words, where a name only counts
when its case and separators are right and other words are compared without
their case. --audio needs the whisper-desk venv (whisper-desk's own Python) and
the recordings next to this file; the models are those already downloaded.
"Before" is the text whisper-desk wrote until now, corrections, hesitations and
spoken punctuation included; "after" adds the developer syntax.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from whisper_desk import backtrack, casing, hesitations, punctuation  # noqa: E402


def corpus() -> list[dict[str, str]]:
    with (HERE / "corpus.tsv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def is_name(word: str) -> bool:
    return bool(re.search(r"\w[_-]\w|[a-z][A-Z]|^[A-Z][a-z]+[A-Z]", word))


def tokens(text: str) -> list[str]:
    return [w if is_name(w) else w.lower() for w in re.findall(r"[\w'’-]+", text)]


def names(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w'’-]+", text) if is_name(w)]


def distance(reference: list[str], hypothesis: list[str]) -> int:
    row = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        previous, row[0] = row[0], i
        for j, hyp in enumerate(hypothesis, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ref != hyp))
    return row[-1]


def error_rate(pairs: list[tuple[str, str]]) -> float:
    errors = sum(distance(tokens(ref), tokens(hyp)) for ref, hyp in pairs)
    return errors / max(1, sum(len(tokens(ref)) for ref, _ in pairs))


def names_found(pairs: list[tuple[str, str]]) -> tuple[int, int]:
    found = total = 0
    for expected, written in pairs:
        wanted = names(expected)
        total += len(wanted)
        found += sum(name in names(written) for name in wanted)
    return found, total


def today(text: str) -> str:
    return punctuation.apply(hesitations.apply(backtrack.apply(text)))


def transcripts(model: str, device: str) -> dict[str, str]:
    from faster_whisper import WhisperModel

    compute = "float16" if device == "cuda" else "int8"
    whisper = WhisperModel(model, device=device, compute_type=compute)
    out = {}
    for row in corpus():
        segments, _ = whisper.transcribe(
            str(HERE / "audio" / f"{row['id']}.opus"), language=row["lang"],
            beam_size=5, vad_filter=True, condition_on_previous_text=False,
        )
        out[row["id"]] = " ".join(s.text.strip() for s in segments).strip()
    return out


def report(label: str, raw: dict[str, str], verbose: bool) -> None:
    rows = corpus()
    groups = (
        ("names fr", lambda r: r["id"].startswith("fr")),
        ("names en", lambda r: r["id"].startswith("en")),
        ("controls", lambda r: r["id"].startswith("ctl")),
    )
    for group, keep in groups:
        chosen = [r for r in rows if keep(r)]
        before = [(r["expected"], today(raw[r["id"]])) for r in chosen]
        after = [(r["expected"], casing.apply(hyp)) for r, (_, hyp) in zip(chosen, before)]
        exact = sum(tokens(e) == tokens(h) for e, h in after)
        line = (f"{label:<28} {group:<9} errors {error_rate(before):6.1%} -> "
                f"{error_rate(after):6.1%}   exact {exact}/{len(chosen)}")
        if group != "controls":
            found_before, total = names_found(before)
            found_after, _ = names_found(after)
            line += f"   names {found_before}/{total} -> {found_after}/{total}"
        else:
            changed = sum(b != a for (_, b), (_, a) in zip(before, after))
            line += f"   changed {changed}/{len(chosen)}"
        print(line)
        if verbose:
            for row, (expected, fixed) in zip(chosen, after):
                if tokens(expected) != tokens(fixed):
                    print(f"    {row['id']}: {raw[row['id']]!r} -> {fixed!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--models", default="small:cpu,large-v3-turbo:cuda")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    report("written sentences", {r["id"]: r["spoken"] for r in corpus()}, args.verbose)
    if args.audio:
        for spec in args.models.split(","):
            model, device = spec.split(":")
            report(f"{model} ({device})", transcripts(model, device), args.verbose)


if __name__ == "__main__":
    main()
