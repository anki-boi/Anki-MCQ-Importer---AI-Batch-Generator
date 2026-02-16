# Anki MCQ Importer - AI Batch Generator (v3.2.0)

An Anki add-on that batch-processes folders of study images with Google Gemini and generates high-yield MCQ cards into organized subdecks.

## What’s new in v3.2 (Fixed Edition)

- API key validation now saves correctly and no longer repeatedly re-prompts.
- Progress dialog can be closed with the window **X** button.
- Note type flow uses manual installation guidance (download link only).
- Updated Gemini defaults to Gemini 3 preview models.

## Features

- Guided first-run setup and settings dialog.
- Gemini API key format checks and live connection tests.
- Dynamic model discovery from Gemini API (`generateContent` capable models).
- Batch import workflow with progress tracking and summary reporting.
- Image validation with supported formats and max file-size checks.
- Context-aware generation support for page-to-page continuity.

## Default configuration

Current defaults in this repository:

- Model: `gemini-3-flash-preview`
- Batch size: `10`
- API validation on startup: `false`
- Note type repo: `anki-boi/True-Anki-MCQ-Note-Template`
- Note type download URL: `https://github.com/anki-boi/True-Anki-MCQ-Note-Template/releases/latest`

## Repository contents

- `__init__.py` — Main add-on implementation loaded by Anki.
- `config.json` — Default add-on configuration.
- `manifest.json` — Add-on package metadata.
- `build.py` — Build script to create `.ankiaddon` packages.

## Build package

```bash
python build.py
```

On success, the build script generates:

- `anki_mcq_importer_ai_batch_generator_v<version>.ankiaddon`
- `RELEASE_NOTES_v<version>.md`

## Install in Anki (manual)

1. Build or download the `.ankiaddon` file.
2. In Anki, open **Tools → Add-ons → Install from file...**
3. Select the `.ankiaddon` file.
4. Restart Anki.

## Configuration

Open settings from Anki:

**Tools → ⚡ Anki MCQ Importer - AI Batch Generator → ⚙ Settings**

Then set:

- Gemini API key
- Gemini model
- Note type
- Advanced import options

## Requirements

- Anki 2.1.45+
- Internet access
- Google Gemini API key

## Disclaimer

This project uses a third-party API (Google Gemini). Usage limits, pricing, and terms are managed by Google.
