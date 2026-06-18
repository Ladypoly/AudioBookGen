# Character & chapter extraction — two paths

Two pieces need LLM judgment: **character extraction** and **chapter line
planning** (speaker attribution + segmentation). Everything else (delivery from
verbs/adverbs/punctuation, SFX/ambience/music detection, front matter, title
announce, pauses, mastering, tagging) is deterministic code and works for any
book automatically.

## 1. Local path — gemma4 (default, in-app, offline)

The app runs this automatically (Characters tab → extract):

- **Characters:** gemma4 map-pass per chunk → code-side merge/canonicalize →
  deterministic descriptions. Now also captures a short spoiler-safe `context`
  per character ("the boy's father", "a waiter") which drives the description,
  portrait background and voice.
- **Chapters:** the deterministic `line_planner` (German quotes, attribution
  verbs, pronoun+gender resolution, sentence segmentation, delivery-from-verbs).

Good, fully local, no cost — but gemma hits a quality ceiling on big casts, and
the heuristic can swap two same-gender speakers attributed only by pronoun.

## 2. Quality path — Claude agents (console / Claude Code)

Higher quality (clean canonicalization, context, pronoun/same-gender speaker
resolution). Runs in the **console**, not the app (no API key needed).

**Chapters** (reusable workflow):

1. Detect chapters in the app (Chapters tab → Detect chapters).
2. In Claude Code, run the named workflow with the project dir + chapter ids:
   `Workflow({ name: 'script-chapters', args: { projectDir, chapterIds } })`
   Each agent reads the roster (`registry/characters.json`) and the chapter
   text, then writes `analysis/chapters/<id>.agent.json`.
3. Ingest into curated chapters:
   `python scripts/ingest_agent_chapters.py "<book.pdf>"`
   Curated chapters are marked `curated` and are never overwritten by the
   heuristic planner; chapters without an agent file fall back to it.

**Characters:** ask Claude Code to read the book and write
`registry/characters.json` (merged names, context, gender, voice hints,
portrait prompts). This is the same curation used for the first book.

## Mixing the two

The two paths are compatible per chapter: a `curated` chapter (Claude) is used
as-is; any other chapter uses the gemma/heuristic plan. So you can let the local
path do the bulk and run the Claude pass only on the chapters that need it.
