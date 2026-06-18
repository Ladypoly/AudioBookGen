export const meta = {
  name: 'script-chapters',
  description: 'Agent-author audio-drama line plans for a book (one agent per chapter)',
  whenToUse: 'The Claude quality path for chapter line planning. Pass args {projectDir, chapterIds}. Each agent reads the roster + chapter text from the project and writes <id>.agent.json. Ingest afterwards with scripts/ingest_agent_chapters.py.',
  phases: [{ title: 'Script chapters', detail: 'one Claude agent per chapter writes <id>.agent.json' }],
}

// args: { projectDir: string, chapterIds: string[] } — falls back to this book.
const DIR = (args && args.projectDir) ||
  String.raw`C:\Tools\AI_Code_Projects\AudioBookGen\projects\hamilton-peter-f-der-dieb-der-zeit-das-zweite-leben-des-jeff-baker`
let ids = (args && args.chapterIds) || []
if (ids.length === 0) {
  for (let n = 1; n <= 59; n++) ids.push('ch' + String(n).padStart(2, '0'))
}

const RULES = `CLASSIFY each piece, in reading order, covering the ENTIRE chapter (skip/summarize/paraphrase NOTHING; keep wording verbatim, only newline/whitespace cleanup):
- NARRATION -> speaker "erzaehler".
- DIALOGUE (spoken aloud, inside German quotes) -> the character_id of who SPEAKS.
- Attribution clauses (", sagte er", ", erkundigte sich Sue") are NARRATION, not part of the spoken line.
- EMPHASIS quotes (a German quote used to emphasise a noun phrase, not speech) -> fold into the surrounding narration, without the quote marks.

SPEAKER ATTRIBUTION (be smarter than a regex): resolve pronouns ("sagte er/sie") from context; distinguish two same-gender speakers by who is actually talking; a character merely named as the LISTENER is not the speaker; a speaker not in the roster -> "erzaehler".

SEGMENTATION: each line = ONE coherent unit; keep whole sentences; merge consecutive SHORT sentences of the SAME speaker (~150-280 chars); split a sentence longer than ~320 chars at a comma/semicolon/dash (never mid-word); collapse hard-wrapped newlines and double spaces to single spaces; keep original wording/punctuation otherwise.

DELIVERY (optional, only when the prose clearly implies it, else ""): emotion in {elation, amusement, enthusiasm, determination, pride, contentment, affection, relief, contemplation, confusion, surprise, awe, longing, anger, fear, disgust, bitterness, sadness, shame, helplessness}; style in {shouting, whispering}. e.g. "schrie"->anger+shouting; "fluesterte"->whispering; "lachte"->amusement; "seufzte"->sadness.

SFX (optional, NARRATION lines only) — BE CONSERVATIVE: add a sound only where it genuinely makes sense and adds to the scene. Do NOT force sfx; the large majority of lines have NONE (sfx: []). Quality over quantity — a sparse, well-placed handful per chapter beats constant noise. Only when the prose describes a concrete, clearly audible sound event (a door, glass, footsteps, an engine, rain, a crowd, a phone, a gunshot, pouring a drink, etc.) add a "sfx" array with ONE tailored cue describing THAT specific sound in vivid English, matching the detail in the text (material, force, space). Each cue: {"prompt": "<English sound description>", "placement": "over" | "gap", "length_s": <1-5>}. Use "gap" for a sharp one-shot that should land in a pause (door slam, glass break, gunshot), "over" for a textural sound under the narration (rain, crowd, fire). Skip vague, implied, metaphorical or purely emotional "sounds".`

function promptFor(cid) {
  return `You are scripting one chapter of a German novel into an ordered audio-drama line plan. Output is DATA (a JSON file), not prose for a human.

STEP 1 — Read the cast roster from \`${DIR}\\registry\\characters.json\` (use each entry's character_id, display_name, aliases, gender_guess). The narrator's id is "erzaehler".
STEP 2 — Read the chapter prose from \`${DIR}\\analysis\\chapters\\${cid}.json\` (its \`text\` field; German, hard-wrapped newlines = spaces). If missing/empty, write [] to the output and stop.
STEP 3 — Produce the full ordered line plan for the whole chapter.

${RULES}

Use ONLY character_id values from the roster (or "erzaehler") for dialogue speakers.

STEP 4 — Write the result to \`${DIR}\\analysis\\chapters\\${cid}.agent.json\` as a UTF-8 JSON array; each item:
{"type": "narration" | "dialogue", "speaker": "<character_id or erzaehler>", "text": "<clean German text>", "emotion": "", "style": "", "sfx": []}
(sfx is usually [] — include a cue only on a narration line with a real, concrete sound event.)

Reply with ONLY a one-line summary: total lines, dialogue count, distinct speaker_ids used.`
}

phase('Script chapters')
log(`Scripting ${ids.length} chapters…`)
const results = await parallel(ids.map((cid) => () =>
  agent(promptFor(cid), { label: `script:${cid}`, phase: 'Script chapters', agentType: 'general-purpose' })
))
return { scripted: results.filter(Boolean).length, total: ids.length }
