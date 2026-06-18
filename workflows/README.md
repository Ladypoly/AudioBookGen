# ComfyUI workflow templates

The app fills `{placeholder}` tokens in these ComfyUI **API-format** graph JSON
files and submits them via the ComfyUI HTTP API (`comfy_service.run_workflow`).

## How to create one

1. Build the graph in ComfyUI (e.g. an Ideogram 4 / Z-Image Turbo portrait graph).
2. Enable **dev mode** in ComfyUI settings → **Save (API Format)**.
3. Save the exported JSON here under the expected file name.
4. Replace the literal input values with `{placeholders}` (see below).

## portrait_ideogram.json  (API format — REQUIRED)

Must be the **Save (API Format)** export (flat `{node_id: {class_type, inputs}}`).
A UI export (with `nodes`/`links`/`subgraphs`) is rejected with a clear error.

Used by `portrait_service.generate_portrait`. Placeholders, mapped to the
current Ideogram-4 graph:

| placeholder         | node (this graph)            | filled with                          |
|---------------------|------------------------------|--------------------------------------|
| `{positive_prompt}` | `98:24` CLIPTextEncode `text`| serialized Ideogram-4 JSON caption   |
| `{seed}`            | `98:18` RandomNoise `noise_seed` | deterministic int per character_id |
| `{filename_prefix}` | `158` SaveImage `filename_prefix`| `character_id`                    |

Notes specific to this graph:
- **No negative-text node** — negatives come from `ConditioningZeroOut` +
  `DualModelGuider` (the `ideogram4_unconditional` model). `PortraitStyle.
  negative_prompt` is unused here.
- **Resolution is fixed** by `ResolutionSelector` (37) = "3:4 (Portrait
  Standard)". No width/height placeholder.
- `{positive_prompt}` is the already-engine-formatted JSON caption, so
  **Magic Prompt stays OFF** (PLAN Appendix A.2).

If node ids change after a re-export, update the three node keys above (and the
patch is just `inputs.text` / `inputs.noise_seed` / `inputs.filename_prefix`).
Until a valid API file exists the portrait button reports a clear error;
extraction + cards work without it.
