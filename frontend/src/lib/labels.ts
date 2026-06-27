export const ROLE_COLOR: Record<string, string> = {
  narrator: "#9aa3b2",
  main: "#5b8cff",
  secondary: "#27c498",
  minor: "#9aa3b2",
  crowd: "#6b7280",
};

export const AGE_LABEL: Record<string, string> = {
  child: "Child",
  teen: "Teen",
  young_adult: "Young adult",
  adult: "Adult",
  elderly: "Elderly",
  unknown: "—",
};

export const GENDER_LABEL: Record<string, string> = {
  male: "Male",
  female: "Female",
  ambiguous: "Ambiguous",
  unknown: "—",
};

export const AGE_BANDS = ["child", "teen", "young_adult", "adult", "elderly", "unknown"];
export const GENDERS = ["male", "female", "ambiguous", "unknown"];
export const ROLES = ["narrator", "main", "secondary", "minor", "crowd"];

const NARRATOR_ID = "erzaehler";
const SPK_PALETTE = [
  "#5b8cff", "#f783ac", "#63e6be", "#ffa94d", "#b794f6",
  "#74c0fc", "#ffd43b", "#ff8787", "#69db7c", "#e599f7",
];

// Stable per-speaker colour (narrator = neutral grey), mirroring the old UI.
export function speakerColor(sid: string): string {
  if (sid === NARRATOR_ID) return "#9aa3b2";
  let h = 0;
  for (let i = 0; i < sid.length; i++) h = (h * 31 + sid.charCodeAt(i)) >>> 0;
  return SPK_PALETTE[h % SPK_PALETTE.length];
}

// Delivery chip colours: emotion=amber, style=purple, prosody=teal, nonverbal=pink.
export const DELIVERY_COLOR = {
  emotion: "#ffa94d",
  style: "#b794f6",
  prosody: "#63e6be",
  nonverbal: "#f783ac",
  sfx: "#f4db7d",
} as const;

// Higgs control vocabulary (mirrors app/schemas/voice.py).
export const EMOTIONS = [
  "elation", "amusement", "enthusiasm", "determination", "pride", "contentment",
  "affection", "relief", "contemplation", "confusion", "surprise", "awe",
  "longing", "anger", "fear", "disgust", "bitterness", "sadness", "shame",
  "helplessness",
];
export const STYLES = ["singing", "shouting", "whispering"];
