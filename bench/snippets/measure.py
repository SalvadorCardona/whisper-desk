"""How many snippets reach the text, from the words said to the words typed.

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

from whisper_desk.snippets import Snippets  # noqa: E402


def corpus() -> list[dict[str, str]]:
    with (HERE / "corpus.tsv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def cues() -> dict[str, str]:
    with (HERE / "snippets.toml").open("rb") as handle:
        return tomllib.load(handle)["snippets"]


def table() -> Snippets:
    return Snippets(cues())


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


def contains(text: list[str], part: list[str]) -> bool:
    return any(text[i:i + len(part)] == part for i in range(len(text) - len(part) + 1))


def expanded(expected: str, typed: str, snippets: Snippets) -> bool:
    """Is every snippet the sentence should hold in what was typed?"""
    wanted = [words(text) for text in snippets.expansions.values()
              if contains(words(expected), words(text))]
    return all(contains(words(typed), part) for part in wanted)


def transcripts(model: str, device: str, hotwords: str | None) -> dict[str, str]:
    from faster_whisper import WhisperModel

    compute = "float16" if device == "cuda" else "int8"
    whisper = WhisperModel(model, device=device, compute_type=compute)
    out = {}
    for row in corpus():
        segments, _ = whisper.transcribe(
            str(HERE / "audio" / f"{row['id']}.opus"), language=row["lang"],
            beam_size=5, vad_filter=True, condition_on_previous_text=False,
            hotwords=hotwords,
        )
        out[row["id"]] = " ".join(s.text.strip() for s in segments).strip()
    return out


def report(label: str, raw: dict[str, str], verbose: bool) -> None:
    rows, snippets = corpus(), table()
    for group, keep in (("snippets", lambda r: not r["id"].startswith("ctl")),
                        ("controls", lambda r: r["id"].startswith("ctl"))):
        chosen = [r for r in rows if keep(r)]
        before = [(r["expected"], raw[r["id"]]) for r in chosen]
        after = [(r["expected"], snippets.apply(raw[r["id"]])) for r in chosen]
        exact = sum(words(e) == words(h) for e, h in after)
        if group == "snippets":
            hits = sum(expanded(e, h, snippets) for e, h in after)
            outcome = f"expanded {hits}/{len(chosen)}"
        else:
            # A control changed by the snippets is a snippet typed for nothing.
            false = sum(snippets.apply(raw[r["id"]]) != raw[r["id"]] for r in chosen)
            outcome = f"false triggers {false}/{len(chosen)}"
        print(f"{label:<28} {group:<10} WER {wer(before):6.1%} -> {wer(after):6.1%}"
              f"   exact {exact}/{len(chosen)}   {outcome}")
        if verbose:
            for row, (expected, typed) in zip(chosen, after):
                if words(expected) != words(typed):
                    print(f"    {row['id']}: {raw[row['id']]!r} -> {typed!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--models", default="small:cpu,large-v3-turbo:cuda")
    parser.add_argument("--hotwords", action="store_true",
                        help="push the cues into the decoder, as [model] vocabulary does")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    report("written sentences", {r["id"]: r["spoken"] for r in corpus()}, args.verbose)
    if args.audio:
        for spec in args.models.split(","):
            model, device = spec.split(":")
            hotwords = ", ".join(cues()) if args.hotwords else None
            label = f"{model} ({device}){' + cues' if hotwords else ''}"
            report(label, transcripts(model, device, hotwords), args.verbose)


if __name__ == "__main__":
    main()
