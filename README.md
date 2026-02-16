# Anki MCQ Importer - AI Batch Generator

An Anki add-on that batch-processes image folders with Google Gemini to generate high-yield multiple-choice cards, organized automatically into subdecks.

## Features

- Guided first-run setup wizard.
- Gemini API key validation and connection testing.
- Download/update note types from GitHub releases.
- Dynamic model selection (Flash / Pro variants).
- Robust image validation and import progress dialog.
- Context-aware generation using previous-page continuity.
- Error handling and post-import summary reporting.

## Repository contents

- `__init__.py` — Main add-on implementation loaded by Anki.
- `config.json` — Default configuration values.
- `manifest.json` — Add-on metadata used for packaging/distribution.
- `build.py` — Build script to create `.ankiaddon` packages.

## Build package

```bash
python build.py
```

On success, the script outputs:

- `anki_mcq_importer_ai_batch_generator_v<version>.ankiaddon`
- `RELEASE_NOTES_v<version>.md`

## Install in Anki (manual)

1. Build or download the `.ankiaddon` file.
2. In Anki: **Tools → Add-ons → Install from file...**
3. Select the `.ankiaddon` file.
4. Restart Anki.

## Configuration

Open from Anki menu:

**Tools → ⚡ Anki MCQ Importer - AI Batch Generator → ⚙ Settings**

Then set:

- Gemini API key
- model selection
- note type
- advanced import options

## Requirements

- Anki 2.1.45+
- Internet access
- Google Gemini API key

## Disclaimer

This project uses third-party APIs (Google Gemini). Usage limits, pricing, and terms are managed by the provider.
