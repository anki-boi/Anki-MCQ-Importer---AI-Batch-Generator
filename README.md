# Anki MCQ Importer - AI Batch Generator (v4.0.0)

An Anki add-on that batch-processes folders of study images with Google Gemini and creates high-yield cards into organized subdecks.

Version 4 introduces a **Prompt Profiles** system so you can generate different card formats from the same import pipeline:

- **MCQ** cards (Question / Multiple Choice / Correct Answers / Extra)
- **Cloze** cards (Text / Extra)
- **Basic** cards (Front / Back / Extra)

---

## What’s new in v4.0

### Prompt Profiles (major)
- Added profile-based generation with three built-in profiles: **MCQ**, **Cloze**, and **Basic**.
- Each profile has its own tuned prompt and parser format.
- You can edit prompt text directly in Settings.
- You can duplicate and customize profiles for your own workflows.
- Custom profiles can be deleted; built-in defaults are protected.
- Added reset options for restoring one built-in prompt or all profile defaults.

### Per-profile field mapping
- Field mapping is now tied to the selected profile.
- Logical slots (e.g., Question, Choices, Answer, Text, Extra) are mapped to your Anki note type fields.
- This supports note types with non-standard field names and mixed naming conventions.

### Import/runtime pipeline improvements
- Parser dispatch now uses the active profile format (`mcq`, `cloze`, `basic`).
- Imports show the active profile and selected note type before execution.
- Model selection supports current Gemini families and API-discovered `generateContent` models.

### Updated defaults
- Default model updated to `gemini-2.5-flash-preview-05-20`.
- Default auto-open media remains enabled (`true`).
- Startup API validation remains optional (`false`).

---

## Core features

- Guided first-run setup and settings dialog.
- Gemini API key format checks and live connection tests.
- Dynamic model discovery from Gemini API (`generateContent` capable models).
- Batch import workflow with progress tracking and summary reporting.
- Image validation with supported formats and max file-size checks.
- Context-aware generation support for page-to-page continuity.
- Automatic subdeck creation from parsed subtopics.
- Profile-specific prompt editing and field mapping.

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

## Default configuration

The packaged defaults are:

- `model`: `gemini-2.5-flash-preview-05-20`
- `note_type_id`: `null` (select in settings)
- `active_profile`: `MCQ`
- `auto_open_media`: `true`
- `batch_size`: `10`
- `validate_api_on_startup`: `false`

On upgrade from older versions, missing profile data is auto-migrated in runtime config.

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
