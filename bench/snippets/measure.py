"""Snippets of the measure corpus: how many cues come out as their saved text.

    python3 bench/snippets/measure.py              # on the written sentences
    python3 bench/snippets/measure.py --audio      # through faster-whisper

--audio needs the whisper-desk venv (whisper-desk's own Python) and the
recordings next to this file; the models are those already downloaded.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from whisper_desk import snippets  # noqa: E402


def corpus() -> list[dict[str, str]]:
    with (HERE / "corpus.tsv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        row["expected"] = row["expected"].replace("\\n", "\n")
    return rows


def saved() -> dict[str, str]:
    with (HERE / "snippets.toml").open("rb") as handle:
        return tomllib.load(handle)


def words(text: str) -> list[str]:
    return re.findall(r"[\w'’@:/.-]+", text.lower().replace(". ", " ").rstrip("."))


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


def report(title: str, rows: list[dict[str, str]], heard: dict[str, str], table) -> None:
    print(f"## {title}")
    for label, group in (("cues", [r for r in rows if not r["id"].startswith("ctl")]),
                         ("controls", [r for r in rows if r["id"].startswith("ctl")])):
        before = [(r["expected"], heard[r["id"]]) for r in group]
        after = [(r["expected"], snippets.expand(heard[r["id"]], table)) for r in group]
        exact = sum(words(ref) == words(hyp) for ref, hyp in after)
        print(f"{label}: WER {wer(before):.1%} -> {wer(after):.1%}, "
              f"{exact}/{len(group)} exact")
        for row, (ref, hyp) in zip(group, after):
            if words(ref) != words(hyp):
                print(f"  {row['id']}: heard {heard[row['id']]!r} -> {hyp!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--model", default="small")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    rows, table = corpus(), saved()
    if args.audio:
        heard = transcripts(args.model, args.device)
        title = f"faster-whisper {args.model} ({args.device})"
    else:
        heard = {row["id"]: row["spoken"] for row in rows}
        title = "written sentences"
    report(title, rows, heard, table)


if __name__ == "__main__":
    main()
