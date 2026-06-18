"""Ingest Claude-agent chapter plans into curated chapters (the quality path).

Run after the `script-chapters` workflow has written <id>.agent.json files:

    python scripts/ingest_agent_chapters.py "<book.pdf>"

For every analysis/chapters/<id>.agent.json it builds a curated chapter
(speaker ids validated against the registry, delivery from emotion/style),
marks it `curated`, and refreshes the index. Falls back to the heuristic
planner for any chapter without an agent file.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import chapter_service, project_service  # noqa: E402


def main(pdf: str) -> None:
    proj = project_service.open_project(pdf)
    chars = project_service.load_characters(proj)
    valid = {c.character_id for c in chars} | {"erzaehler"}
    cdir = proj.analysis_dir / "chapters"

    ingested, skipped = 0, 0
    for info in chapter_service.load_index(proj):
        cid = info["chapter_id"]
        af = cdir / f"{cid}.agent.json"
        if not af.exists():
            skipped += 1
            continue
        try:
            agent_lines = json.loads(af.read_text(encoding="utf-8"))
        except Exception as err:  # noqa: BLE001
            print(f"  ! {cid}: bad JSON ({err})")
            continue
        ch = chapter_service.ingest_agent_plan(proj, cid, agent_lines, valid)
        if ch is None:
            continue
        ingested += 1
        spk = Counter(l.speaker_id for l in ch.lines if l.type.value == "dialogue")
        print(f"  {cid}: {len(ch.lines)} lines, dialogue speakers {dict(spk.most_common(5))}")

    print(f"Ingested {ingested} curated chapters ({skipped} without an agent file "
          "use the heuristic planner).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
