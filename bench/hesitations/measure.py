"""Word error rate of the hesitations corpus, before and after they are left out.

    python3 bench/hesitations/measure.py              # on the written sentences
    python3 bench/hesitations/measure.py --audio      # through faster-whisper

--audio needs the whisper-desk venv (whisper-desk's own Python) and the
recordings next to this file; the models are those already downloaded.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from whisper_desk import hesitations  # noqa: E402


def corpus() -> list[dict[str, str]]:
    with (HERE / "corpus.tsv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def words(text: str) -> list[str]:
    return re.findall(r"[\w'’]+", text.lower())


def distance(reference: list[str], hypothesis: list[str]) -> int:
    row = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        previous, row[0] = row[0], i
        for j, hyp in enumerate(hypothesis, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ref != hyp))
    return row[-1]


def wer(pairs: list[tuple[str, str]]) -> float:
    errors = sum(distance(words(ref), words(hyp)) for ref, hyp in pairs)
    return errors / max(1, sum(len(words(ref)) for ref, _ in pairs))


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
    for group, keep in (("hesitations", lambda r: not r["id"].startswith("ctl")),
                        ("controls", lambda r: r["id"].startswith("ctl"))):
        chosen = [r for r in rows if keep(r)]
        before = [(r["expected"], raw[r["id"]]) for r in chosen]
        after = [(r["expected"], hesitations.apply(raw[r["id"]])) for r in chosen]
        exact = sum(words(e) == words(h) for e, h in after)
        print(f"{label:<28} {group:<12} WER {wer(before):6.1%} -> {wer(after):6.1%}"
              f"   exact {exact}/{len(chosen)}")
        if verbose:
            for row, (expected, fixed) in zip(chosen, after):
                if words(expected) != words(fixed):
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
