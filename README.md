# Anki MCQ Importer - AI Batch Generator (v4.2.0)

An Anki add-on that batch-processes folders of study images with Google Gemini and creates high-yield cards into organized subdecks.

Version 4.2 expands profile flexibility while keeping prompts in runtime config (so edits survive add-on updates) and supports three built-in card formats:

- **MCQ** cards (Question / Multiple Choice / Correct Answers / Extra)
- **Cloze Deletion** cards (Text / Extra)
- **Basic** cards (Front / Back / Extra)

---

## What’s new in v4.2

### Config-based prompt persistence
- Built-in prompts are seeded once into config and preserved afterward.
- Prompt edits are no longer overwritten when updating the add-on.
- Missing built-in prompts/profiles are auto-backfilled non-destructively.

### Profile workflow improvements
- Added **New Blank Profile** flow with a format selector (**MCQ**, **Cloze**, or **Basic**).
- Duplicate profile workflow remains available for “copy and tweak”.
- Built-in profiles are protected from deletion and can be reset to factory prompt text.

### Multiple profiles for each prompt format
- You can now create and maintain **multiple prompt profiles per format** (MCQ, Cloze, and Basic).
- This allows separate profile variants (e.g., exam-style vs. concise-review) without overwriting your defaults.
- Active profile selection and per-profile field mapping are preserved per profile.

### Card-format support (including requested update)
- **Basic note types are supported** via the Basic profile and per-profile field mapping.
- **Cloze deletions are supported** via the Cloze profile parser and `{{c1::...}}` syntax guidance.
- Parser dispatch uses the active profile format (`mcq`, `cloze`, `basic`) at runtime.

---

## Core features

- Guided first-run setup and settings dialog.
- Gemini API key format checks and live connection tests.
- Dynamic model discovery from Gemini API (`generateContent`-capable models).
- Batch import workflow with progress tracking and summary reporting.
- Image validation with supported formats and max file-size checks.
- Context-aware generation support for page-to-page continuity.
- Automatic subdeck creation from parsed subtopics.
- Profile-specific prompt editing and per-profile field mapping.

---

## Prompt profile formats

### 1) MCQ profile
Expected output columns:

`Subtopic | Question | Multiple Choice | Correct Answers | Extra`

### 2) Cloze profile
Expected output columns:

`Subtopic | Text | Extra`

### 3) Basic profile
Expected output columns:

`Subtopic | Front | Back | Extra`

> Notes:
> - `Subtopic` is used for target subdeck naming.
> - `Extra` is used for rationale/mnemonics/additional context.
> - For multiline cell content, prompts use HTML `<br>` line breaks.

---

## Settings overview

Open settings in Anki:

**Tools → ⚡ Anki MCQ Importer - AI Batch Generator → ⚙ Settings**

You can configure:

- Gemini API key
- Gemini model (manual or refreshed from API)
- Active prompt profile
- Profile prompt text
- Per-profile field mapping
- Note type used for import
- Batch size
- Auto-open media folder after import
- Validate API key/model on startup

---

## Default packaged configuration

- `model`: `gemini-2.5-flash-preview-05-20`
- `active_profile`: `MCQ`
- `profiles`: `MCQ`, `Cloze`, `Basic` with default field maps
- `show_welcome`: `true`
- `auto_open_media`: `true`
- `batch_size`: `10`
- `validate_api_on_startup`: `false`

On startup, built-in prompts are seeded into config if missing.

---

## Repository contents

- `__init__.py` — Main add-on implementation loaded by Anki.
- `config.json` — Packaged default config for fresh installs.
- `manifest.json` — Add-on metadata and packaged default config.
- `build.py` — Build script to create `.ankiaddon` packages.
- `README.md` — Project documentation.

---

## Build package

```bash
python build.py
```

On success, the build script generates:

- `anki_mcq_importer_ai_batch_generator_v<version>.ankiaddon`
- `RELEASE_NOTES_v<version>.md`

---

## Install in Anki (manual)

1. Build or download the `.ankiaddon` file.
2. In Anki, open **Tools → Add-ons → Install from file...**
3. Select the `.ankiaddon` file.
4. Restart Anki.

---

## Requirements

- Anki 2.1.45+
- Internet access
- Google Gemini API key

---

## Disclaimer

This project uses a third-party API (Google Gemini). Usage limits, pricing, and terms are managed by Google.
