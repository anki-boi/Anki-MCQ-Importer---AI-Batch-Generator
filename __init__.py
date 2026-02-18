# True Anki MCQ Importer - AI Batch Generator (v4.1 - Config-Based Prompts)
# Changes from v4.0:
# - Prompts now live exclusively in config.json (survive addon updates)
# - migrate_prompts_to_config() seeds config on first run, never overwrites after
# - "New Blank Profile" button with format selector for fully custom prompts
# - Duplicate still works for "copy & tweak" workflow
# - _SEED_* strings in Python are only used once at first run, then ignored

import os
import json
import urllib.request
import urllib.error
import base64
import re
import traceback
from typing import Optional, List, Tuple, Dict
import copy

from aqt import mw
from aqt.utils import showInfo, showWarning, askUser, tooltip, getText
from aqt.qt import *
from anki.notes import Note

# ============================================================================
# CONSTANTS
# ============================================================================

ADDON_NAME = "Anki MCQ Importer - AI Batch Generator"
VERSION = "4.1.0"
DEFAULT_GITHUB_REPO = "anki-boi/True-Anki-MCQ-Note-Template"
NOTE_TYPE_DOWNLOAD_URL = "https://github.com/anki-boi/True-Anki-MCQ-Note-Template/releases/latest"
SUPPORTED_IMAGE_FORMATS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
MAX_FILE_SIZE_MB = 20
GEMINI_MODELS = [
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-pro-preview-06-05",
    "gemini-2.0-flash",
    "gemini-2.0-pro",
]

# Logical field slot identifiers (never exposed as Anki field names directly)
SLOT_QUESTION = "question"   # MCQ: Question stem  | Basic: Front
SLOT_CHOICES  = "choices"    # MCQ only: all options
SLOT_ANSWER   = "answer"     # MCQ: Correct Answers | Basic: Back
SLOT_TEXT     = "text"       # Cloze: sentence with {{c1::}} syntax
SLOT_EXTRA    = "extra"      # All: rationale / mnemonics / image tag

# Slot metadata for the field-mapping UI, keyed by format string
SLOT_META = {
    "mcq": [
        (SLOT_QUESTION, "Question",        "The stem / question text"),
        (SLOT_CHOICES,  "Multiple Choice", "All answer options (separated by <br>)"),
        (SLOT_ANSWER,   "Correct Answers", "Correct option(s) (separated by <br>)"),
        (SLOT_EXTRA,    "Extra / Notes",   "Rationale, mnemonics, image tag"),
    ],
    "cloze": [
        (SLOT_TEXT,  "Text",          "Sentence with {{c1::}} cloze deletions"),
        (SLOT_EXTRA, "Extra / Notes", "Rationale, mnemonics, image tag"),
    ],
    "basic": [
        (SLOT_QUESTION, "Front",         "The question / cue side"),
        (SLOT_ANSWER,   "Back",          "The complete answer"),
        (SLOT_EXTRA,    "Extra / Notes", "Rationale, mnemonics, image tag"),
    ],
}

# ============================================================================
# SEED PROMPT TEXT
# Used ONCE to populate config.json on first run (or when a profile is missing
# its prompt). After that, config.json is the sole source of truth and these
# strings are never consulted again. Updating them in a future addon version
# will NOT overwrite anything the user has edited.
# ============================================================================

_SEED_MCQ_PROMPT = """***

### ** PROMPT FOR CSV CREATION**

**Objective:**
Create a targeted yet comprehensive set of multiple-choice questions (MCQs) covering the most high-yield aspects of the provided text. The goal is to achieve maximum coverage with minimum redundancy. Prioritize depth, uniqueness, and comprehension, while ensuring questions are challenging and well-formatted.

**Key Instructions:**

**1. Coverage & Priority:**
- Generate questions based on the following priority hierarchy:
    1.  Classification
    2.  Specific Drug/Substance Names
    3.  Mechanism of Action (MoA)
    4.  Therapeutic Uses
    5.  Adverse Effects
    6.  Common Names / Nicknames
    7.  Constituents
- Create questions about other unique, testable facts found in the text, even if they don't fit the categories above.
- Crucially, keep the question set lean. For reciprocal facts (e.g., 'What is the application of Method X?' vs. 'What is the method for Application Y?'), always prioritize the version that asks for the specific detail (the application, substance, or description) when given the broader category (the method or class). For example, prefer asking "Vitamins assayed by Fluorometry include:" over asking "The method used to assay Vitamins B1 and B2 is:". The goal is to test the recall of specific details associated with a known category.
- True or false questions are strictly forbidden.
- The best version of a redundant question is one that asks for the name of a specific species.
- Ignore exercises and sample problems in the source text.

**2. Distractor Quality & Choice Parity (CRITICAL):**
- **Contextual Relevance:** Incorrect options (distractors) MUST be contextually relevant. They should be from the same general category as the correct answer to test for nuanced understanding (e.g., a question about a specific antibiotic should use other antibiotics as distractors).
- **Structural & Length Parity:** All options in the `Multiple Choice` column should be of **similar length and grammatical structure**. Avoid making the correct answer noticeably longer or more detailed than the distractors.
- **Avoid Parenthetical Giveaways:** If a correct answer requires a clarification in parentheses (e.g., `Drug X (Class Y)`), add plausible, contextually relevant clarifications in the same format to the distractors as well. EXTREMELY EXTREMELY IMPORTANT OR ELSE CUTE KITTENS WILL DIE.
- **The goal is to make the correct answer indistinguishable from the distractors based on formatting or length alone.**

**3. Question & Answer Phrasing:**
- Avoid phrases like "According to the text," "from the provided text," etc.
- Avoid ambiguous pronouns such as "this," "that," or "it."
- Be concise in the question column unless more detail is needed to avoid ambiguity.
- Do not use "What," "Which," "Where," "How," or "Why." Follow the example statement-like formatting.
- In the `Question` and `Extra` columns, never refer to images or the text itself.
- **Mnemonic Isolation:** Strictly isolate mnemonics to the `Extra` column. The `Question`, `Multiple Choice`, and `Correct Answers` columns must **not** contain any hints, wordplay, or direct phrasing from the mnemonic.

**4. AI Knowledge & Corrections:**
- Stay within the provided text for creating questions and answers, but you are encouraged to use your broader knowledge to enrich the `Extra` column.
- Add a `Rationale:` to the `Extra` column whenever possible to provide context.
- If you identify a factual error in the source text, create the question using the corrected information. In the `Extra` column, add a note detailing the correction (e.g., `Note: Source text stated [incorrect fact], which has been corrected to [correct fact].`).

**5. Formatting & Structure:**
- Use pipes `|` as separators for the CSV columns.
- Skip the `Question|Multiple Choice|Correct Answers|Extra` headers.
- Use HTML line breaks `<br>` to separate items in the `Multiple Choice` and `Correct Answers` columns. **This is the only HTML tag permitted in these two columns.**
- The number of multiple choice options should always be greater than the number of correct answers. Create at the very least 6 choices.
- HTML tags like `<b>`, `<i>`, and `<u>` are **only permitted** in the `Question` and `Extra` columns. Use them to emphasize key words in the `Question` column and for formatting in the `Extra` column. Avoid overlapping HTML tags.
- Image tags / references (if provided) are to be added to the end of their respective cards at the bottom of the Extra Column

**6. Example (Reflecting All Final Rules):**

```
Subtopic Name | Question|Multiple Choice|Correct Answers|Extra
Anti-Diabetes|Classes of drugs for <b>diabetes mellitus</b>:|Insulin secretagogues<br>Biguanides<br>Thiazolidinediones<br>Alpha-glucosidase inhibitors<br>Incretin-based drugs<br>SGLT2 Inhibitors<br>Amylin Analogues<br>Alkaloids<br>Carbamates|Insulin secretagogues<br>Biguanides<br>Thiazolidinediones<br>Alpha-glucosidase inhibitors<br>Incretin-based drugs<br>SGLT2 Inhibitors<br>Amylin Analogues|Rationale: Except for insulin injections, which are the primary treatment for Type 1 DM but also used in Type 2, the other listed oral hypoglycemic agents are used for Type 2 DM.<br><br>Mnemonic: <b>I</b>n <b>B</b>right <b>T</b>imes, <b>A</b>ll <b>I</b>ndividuals <b>S</b>hine <b>A</b>gain.
Anti-Diabetes|Mechanism of action of <b>Insulin Secretagogues</b>:|Blockade of ATP-sensitive K+ channels<br>Activation of AMP-activated protein kinase<br>Agonism of PPAR-γ receptors<br>Inhibition of alpha-glucosidase enzymes<br>Stimulation of glucagon-like peptide-1<br>Inhibition of sodium-glucose cotransporter 2|Blockade of ATP-sensitive K+ channels|Rationale: Blocking ATP-sensitive K+ channels leads to membrane depolarization, which opens voltage-gated Ca2+ channels. The subsequent influx of calcium triggers the exocytosis of insulin-containing granules from the β-cells.<br><br>Mnemonic: <i>Secret</i>-<b>B</b>K+ blockers
Anti-Diabetes|Biguanide drug largely withdrawn from the market due to a high risk of fatal <b>lactic acidosis</b>:|Phenformin<br>Metformin<br>Buformin<br>Empagliflozin<br>Acarbose<br>Pioglitazone|Phenformin|Rationale: Phenformin carries a significantly higher risk of causing lactic acidosis compared to metformin because of its chemical structure, which leads to greater inhibition of mitochondrial respiration.
Tannins|Plant sources rich in <b>tannins</b>:|Psidium guajava (Guava)<br>Hamamelis virginiana (Witch Hazel)<br>Quercus infectoria (Oak galls)<br>Syzygium cumini (Java plum)<br>Ginkgo biloba (Ginkgo)<br>Panax ginseng (Ginseng)|Psidium guajava (Guava)<br>Hamamelis virginiana (Witch Hazel)<br>Quercus infectoria (Oak galls)<br>Syzygium cumini (Java plum)|Rationale: The listed plants are notable for their high tannin content. Distractors like Ginkgo and Ginseng are known for other active compounds (ginkgolides, ginsenosides).
Sesame oil|The primary antioxidant lignan constituents of <b>Sesamum indicum</b>:|Sesamol<br>Sesamolin<br>Gossypol<br>Ricin<br>Theobromine<br>Anethole|Sesamol<br>Sesamolin|Rationale: Sesamol and sesamolin are powerful antioxidants in sesame oil. The distractors are toxic or primary constituents of other plants: Gossypol (cottonseed), Ricin (castor bean), Theobromine (cacao), and Anethole (anise).
Zoonotic Diseases|Causative organisms of <b>Rat-bite fever</b>:|Streptobacillus moniliformis<br>Spirillum minus<br>Leptospira interrogans<br>Yersinia pestis<br>Francisella tularensis<br>Borrelia burgdorferi|Streptobacillus moniliformis<br>Spirillum minus|Rationale: Rat-bite fever is a zoonotic disease caused by two different bacteria. The distractors are also causative agents of zoonotic diseases: Leptospirosis (<i>Leptospira</i>), Plague (<i>Yersinia</i>), Tularemia (<i>Francisella</i>), and Lyme disease (<i>Borrelia</i>).
```
"""

_SEED_CLOZE_PROMPT = """***

### ** PROMPT FOR CLOZE DELETION CARD CREATION**

**Objective:**
Create a targeted yet comprehensive set of cloze deletion cards covering the most high-yield aspects of the provided text. The goal is maximum coverage with minimum redundancy. Each card must test a single, specific, retrievable fact using Anki's {{c1::answer}} cloze syntax.

**Key Instructions:**

**1. Coverage & Priority:**
- Generate cards based on the following priority hierarchy:
    1.  Classification
    2.  Specific Drug/Substance Names
    3.  Mechanism of Action (MoA)
    4.  Therapeutic Uses
    5.  Adverse Effects
    6.  Common Names / Nicknames
    7.  Constituents
- Create cards about other unique, testable facts found in the text, even if they don't fit the categories above.
- Keep the card set lean. For reciprocal facts, prioritize the version that blanks the specific detail (name, mechanism, classification) rather than the broader category.
- Ignore exercises and sample problems in the source text.

**2. Cloze Syntax Rules (CRITICAL):**
- Use standard Anki cloze syntax: {{c1::answer}} for single blanks.
- Use numbered groups for related blanks on the same card: {{c1::first}} and {{c2::second}} — each cloze number tests independently.
- When multiple items belong to the same enumeration (e.g., a list of drug classes), use the SAME cloze number for all of them so they are tested together: {{c1::Drug A}}, {{c1::Drug B}}, {{c1::Drug C}}.
- Never put a hint inside the cloze unless it is essential for disambiguation: {{c1::answer::hint}} — use sparingly.
- A single card should not contain more than 3 distinct cloze deletions (c1, c2, c3 max).

**3. Text Phrasing:**
- Write the sentence in the Text column as a clean, factual statement — not a question.
- Avoid phrases like "According to the text," "from the provided text," etc.
- Avoid ambiguous pronouns such as "this," "that," or "it." Name the subject explicitly.
- The cloze text must make complete grammatical sense both with and without the blanks revealed.
- Use <b>, <i>, <u> HTML tags to emphasize non-blanked key terms in the Text column. Do NOT bold or italicize the cloze-deleted text itself.
- Image tags / references (if provided) are to be added at the bottom of the Extra column.

**4. AI Knowledge & Corrections:**
- Stay within the provided text for creating cards, but use broader knowledge to enrich the Extra column.
- Add a `Rationale:` to the Extra column whenever possible to provide context, mechanism, or clinical significance.
- If you identify a factual error in the source text, create the card using the corrected information. In the Extra column, note the correction (e.g., `Note: Source text stated [incorrect fact], which has been corrected to [correct fact].`).

**5. Formatting & Structure:**
- Use pipes `|` as separators.
- Output format per line: Subtopic|Text|Extra
- Skip the header row.
- Use HTML line breaks `<br>` for multi-line content within a column.
- Mnemonics go ONLY in the Extra column — never in the Text column.

**6. Examples:**

```
Anti-Diabetes|The biguanide drug withdrawn from the market due to a high risk of fatal <b>lactic acidosis</b> is {{c1::Phenformin}}.|Rationale: Phenformin carries a significantly higher risk of lactic acidosis than metformin due to its structure causing greater inhibition of mitochondrial respiration.<br><br>Note: Metformin, the remaining biguanide, has a much lower risk and remains first-line therapy.
Anti-Diabetes|<b>Insulin secretagogues</b> lower blood glucose by blocking {{c1::ATP-sensitive K+ channels}}, causing membrane {{c2::depolarization}} and subsequent insulin release.|Rationale: K+ channel blockade triggers Ca2+ influx via voltage-gated channels, which drives exocytosis of insulin granules from pancreatic β-cells.
Anti-Diabetes|Classes of drugs used for <b>diabetes mellitus</b> include {{c1::Biguanides}}, {{c1::Thiazolidinediones}}, {{c1::Alpha-glucosidase inhibitors}}, {{c1::SGLT2 Inhibitors}}, and {{c1::Amylin Analogues}}.|Rationale: These represent the major oral/injectable hypoglycemic drug classes beyond insulin.<br><br>Mnemonic: <b>I</b>n <b>B</b>right <b>T</b>imes, <b>A</b>ll <b>I</b>ndividuals <b>S</b>hine <b>A</b>gain.
Tannins|Plant sources notably rich in <b>tannins</b> include {{c1::Psidium guajava}} (Guava), {{c1::Hamamelis virginiana}} (Witch Hazel), {{c1::Quercus infectoria}} (Oak galls), and {{c1::Syzygium cumini}} (Java plum).|Rationale: These plants are exploited commercially for their astringent, antidiarrheal, and wound-healing properties derived from their high tannin content.
Sesame oil|The primary <b>antioxidant lignan</b> constituents of Sesamum indicum are {{c1::Sesamol}} and {{c1::Sesamolin}}.|Rationale: These lignans contribute significantly to the exceptional oxidative stability of sesame oil and have demonstrated free radical scavenging activity in vitro.
Zoonotic Diseases|<b>Rat-bite fever</b> is caused by either {{c1::Streptobacillus moniliformis}} or {{c1::Spirillum minus}}, depending on the geographic region.|Rationale: S. moniliformis predominates in North America (Haverhill fever), while S. minus is more common in Asia (Sodoku). Both are transmitted via rat bites or scratches.
```
"""

_SEED_BASIC_PROMPT = """***

### ** PROMPT FOR BASIC (FRONT/BACK) CARD CREATION**

**Objective:**
Create a targeted yet comprehensive set of Basic flashcards covering the most high-yield aspects of the provided text. Each card has a Front (the question or cue) and a Back (the Answer followed by the Rationale). The goal is maximum coverage with minimum redundancy.

**Key Instructions:**

**1. Coverage & Priority:**
- Generate cards based on the following priority hierarchy:
    1.  Classification
    2.  Specific Drug/Substance Names
    3.  Mechanism of Action (MoA)
    4.  Therapeutic Uses
    5.  Adverse Effects
    6.  Common Names / Nicknames
    7.  Constituents
- Create cards about other unique, testable facts found in the text, even if they don't fit the categories above.
- Keep the card set lean. For reciprocal facts, prioritize the version that cues with the broader category and answers with the specific detail.
- Ignore exercises and sample problems in the source text.

**2. Front (Question/Cue) Phrasing (CRITICAL):**
- Write the Front as a concise statement-cue or an incomplete sentence — not a full question with "What," "Which," "Where," "How," or "Why."
- Avoid phrases like "According to the text," "from the provided text," etc.
- Avoid ambiguous pronouns such as "this," "that," or "it." Name the subject explicitly.
- Use <b>, <i>, <u> HTML tags to emphasize the key tested concept on the Front.
- The Front must be specific enough that only one correct answer exists — avoid vague cues.
- Mnemonics must NEVER appear on the Front.

**3. Back (Answer & Rationale) Phrasing:**
- **Structure:** The Back must strictly follow this format: **[Direct Answer]** + `<br><br>` + **[Rationale]**.
- **The Direct Answer:**
    - Must come FIRST.
    - Must be the concise, minimal correct answer (no paragraph).
    - Use <b> to highlight key terms.
    - For lists, use <br> to separate items.
- **The Rationale:**
    - Must come SECOND (after the break).
    - Label it clearly with `Rationale:`.
    - Provide context, mechanism, or clinical significance here.
- Avoid restating the Front verbatim in the Back.

**4. AI Knowledge & Corrections:**
- Stay within the provided text for the *Direct Answer*, but use broader knowledge to enrich the *Rationale*.
- If you identify a factual error in the source text, provide the corrected fact in the Answer and explain the correction in the Rationale.
- Mnemonics should NOT go in the Rationale; put them in the **Extra** column.

**5. Formatting & Structure:**
- Use pipes `|` as separators.
- Output format per line: Subtopic|Front|Back|Extra
- Skip the header row.
- Use HTML line breaks `<br>` for multi-line content within a column.
- **Extra Column:** Use this column ONLY for Mnemonics and Images. If none exist, leave it empty.

**6. Examples:**

```
Anti-Diabetes|Classes of drugs for <b>diabetes mellitus</b>:|<b>Insulin secretagogues</b><br><b>Biguanides</b><br><b>Thiazolidinediones</b><br><b>Alpha-glucosidase inhibitors</b><br><b>Incretin-based drugs</b><br><b>SGLT2 Inhibitors</b><br><b>Amylin Analogues</b><br><br>Rationale: These are the major pharmacological classes used for Type 2 DM management. Insulin itself is primary therapy for Type 1 DM.|Mnemonic: <b>I</b>n <b>B</b>right <b>T</b>imes, <b>A</b>ll <b>I</b>ndividuals <b>S</b>hine <b>A</b>gain.
Anti-Diabetes|Mechanism of action of <b>Insulin Secretagogues</b>:|Blockade of <b>ATP-sensitive K+ channels</b> → membrane depolarization → Ca2+ influx → insulin exocytosis<br><br>Rationale: This cascade in pancreatic β-cells is the target of sulfonylureas and meglitinides. Depolarization opens voltage-gated Ca2+ channels, and the resulting Ca2+ surge triggers granule release.|
Anti-Diabetes|Biguanide withdrawn due to fatal <b>lactic acidosis</b> risk:|<b>Phenformin</b><br><br>Rationale: Phenformin's chemical structure causes greater mitochondrial respiratory chain inhibition than metformin, leading to dangerous lactate accumulation. Withdrawn in the 1970s–80s in most countries.|
Tannins|Plant sources rich in <b>tannins</b>:|<b>Psidium guajava</b> (Guava)<br><b>Hamamelis virginiana</b> (Witch Hazel)<br><b>Quercus infectoria</b> (Oak galls)<br><b>Syzygium cumini</b> (Java plum)<br><br>Rationale: These plants are exploited for astringent, antidiarrheal, and wound-healing properties. High tannin content gives them commercial and medicinal value.|
Sesame oil|Primary antioxidant lignan constituents of <b>Sesamum indicum</b>:|<b>Sesamol</b><br><b>Sesamolin</b><br><br>Rationale: These lignans give sesame oil its exceptional oxidative stability. Both have demonstrated free radical scavenging activity.|
Zoonotic Diseases|Causative organisms of <b>Rat-bite fever</b>:|<b>Streptobacillus moniliformis</b> (North America / Haverhill fever)<br><b>Spirillum minus</b> (Asia / Sodoku)<br><br>Rationale: Both are transmitted via rat bites or scratches. Geographic distribution guides diagnosis when culture is pending.|
```
"""

# Shown in the prompt box when a brand-new blank profile is created.
# Gives users the output format spec without locking in any style.
_BLANK_PROMPT_SCAFFOLDS = {
    "mcq": (
        "# Custom MCQ Prompt\n"
        "# Output format per line: Subtopic|Question|Multiple Choice|Correct Answers|Extra\n"
        "# - Use | as column separator\n"
        "# - Use <br> to separate multiple choice options and correct answers\n"
        "# - HTML (<b>, <i>, <u>) allowed in Question and Extra columns only\n"
        "# - Subtopic becomes the Anki subdeck name\n"
        "#\n"
        "# Write your prompt instructions below:\n\n"
    ),
    "cloze": (
        "# Custom Cloze Prompt\n"
        "# Output format per line: Subtopic|Text|Extra\n"
        "# - Use | as column separator\n"
        "# - Text column must contain {{c1::answer}} cloze syntax\n"
        "# - Use <br> for multi-line content within columns\n"
        "# - Subtopic becomes the Anki subdeck name\n"
        "#\n"
        "# Write your prompt instructions below:\n\n"
    ),
    "basic": (
        "# Custom Basic Prompt\n"
        "# Output format per line: Subtopic|Front|Back|Extra\n"
        "# - Use | as column separator\n"
        "# - Use <br> for multi-line content within columns\n"
        "# - Subtopic becomes the Anki subdeck name\n"
        "#\n"
        "# Write your prompt instructions below:\n\n"
    ),
}

# ============================================================================
# DEFAULT PROFILE SCHEMA  (no prompt text — prompts live in config)
# ============================================================================

_DEFAULT_PROFILE_SCHEMA = {
    "MCQ": {
        "display_name": "Multiple Choice (MCQ)",
        "format": "mcq",
        "field_map": {
            SLOT_QUESTION: "Question",
            SLOT_CHOICES:  "Multiple Choice",
            SLOT_ANSWER:   "Correct Answers",
            SLOT_EXTRA:    "Extra",
        },
    },
    "Cloze": {
        "display_name": "Cloze Deletion",
        "format": "cloze",
        "field_map": {
            SLOT_TEXT:  "Text",
            SLOT_EXTRA: "Extra",
        },
    },
    "Basic": {
        "display_name": "Basic (Front / Back)",
        "format": "basic",
        "field_map": {
            SLOT_QUESTION: "Front",
            SLOT_ANSWER:   "Back",
            SLOT_EXTRA:    "Extra",
        },
    },
}

# Keys whose prompts can be factory-reset; also protected from deletion
BUILTIN_PROFILE_KEYS = set(_DEFAULT_PROFILE_SCHEMA.keys())

# Seed prompts indexed by built-in key
_SEED_PROMPTS = {
    "MCQ":   _SEED_MCQ_PROMPT,
    "Cloze": _SEED_CLOZE_PROMPT,
    "Basic": _SEED_BASIC_PROMPT,
}


# ============================================================================
# CONFIG MIGRATION / SEEDING
# ============================================================================

def get_default_config() -> Dict:
    """Build a brand-new default config with prompts already seeded."""
    profiles = {}
    for key, schema in _DEFAULT_PROFILE_SCHEMA.items():
        p = copy.deepcopy(schema)
        p["prompt"] = _SEED_PROMPTS[key]
        profiles[key] = p
    return {
        "api_key": "",
        "model": "gemini-2.5-flash-preview-05-20",
        "active_profile": "MCQ",
        "profiles": profiles,
        "show_welcome": True,
        "auto_open_media": True,
        "batch_size": 10,
        "validate_api_on_startup": False,
    }


def migrate_prompts_to_config(config: Dict) -> Tuple[Dict, bool]:
    """
    Non-destructive migration: ensure every built-in profile has a prompt.

    Rules (strictly enforced):
      - If a profile already has a non-empty "prompt" key → leave it alone.
        The user may have edited it; we NEVER overwrite.
      - If a profile is missing "prompt" or it is empty → seed from _SEED_PROMPTS.
      - If a built-in profile key is absent from config entirely → create it.
      - Custom profiles are untouched in every case.

    Returns (config, changed_flag).
    """
    changed = False

    if "profiles" not in config:
        config["profiles"] = {}
        changed = True

    for key, schema in _DEFAULT_PROFILE_SCHEMA.items():
        if key not in config["profiles"]:
            p = copy.deepcopy(schema)
            p["prompt"] = _SEED_PROMPTS[key]
            config["profiles"][key] = p
            changed = True
        else:
            existing = config["profiles"][key]
            # Backfill any missing structural keys (non-destructive)
            for field, value in schema.items():
                if field not in existing:
                    existing[field] = copy.deepcopy(value)
                    changed = True
            # Seed prompt only when absent or blank
            if not existing.get("prompt", "").strip():
                existing["prompt"] = _SEED_PROMPTS[key]
                changed = True

    if "active_profile" not in config:
        config["active_profile"] = "MCQ"
        changed = True

    return config, changed


# ============================================================================
# LOAD / INITIALISE CONFIG
# ============================================================================

CONFIG = mw.addonManager.getConfig(__name__)
if CONFIG is None:
    CONFIG = get_default_config()
    mw.addonManager.writeConfig(__name__, CONFIG)
else:
    CONFIG, _dirty = migrate_prompts_to_config(CONFIG)
    if _dirty:
        mw.addonManager.writeConfig(__name__, CONFIG)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def log_error(context: str, error: Exception) -> str:
    msg = f"[{ADDON_NAME}] {context}\nError: {error}\n{traceback.format_exc()}"
    print(msg)
    return msg


def validate_api_key(api_key: str) -> Tuple[bool, str]:
    if not api_key or not api_key.strip():
        return False, "API key cannot be empty"
    if not api_key.startswith("AIzaSy"):
        return False, "Invalid API key format. Gemini API keys start with 'AIzaSy'"
    if len(api_key) < 30:
        return False, "API key appears too short. Please verify your key."
    return True, "API key format looks valid"


def test_api_connection(api_key: str, model: str) -> Tuple[bool, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({"contents": [{"parts": [{"text": "Hello"}]}]}).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read().decode())
        return (True, "API connection successful") if "candidates" in result else (False, "Unexpected API response")
    except urllib.error.HTTPError as e:
        rb = e.read().decode("utf-8", errors="ignore")
        msgs = {400: f"Invalid API key or model (HTTP 400)\n{rb}",
                403: "API key auth failed (HTTP 403). Check your key.",
                429: "Rate limit exceeded (HTTP 429). Try again later."}
        return False, msgs.get(e.code, f"HTTP Error {e.code}: {rb}")
    except urllib.error.URLError as e:
        return False, f"Network error: {e}. Check internet connection."
    except Exception as e:
        return False, f"Connection test failed: {e}"


def list_generate_models(api_key: str) -> Tuple[bool, List[str], str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    models, next_url = [], url
    try:
        while next_url:
            with urllib.request.urlopen(urllib.request.Request(next_url), timeout=10) as r:
                payload = json.loads(r.read().decode())
            for m in payload.get("models", []):
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                clean = m.get("name", "").replace("models/", "")
                if clean.startswith("gemini"):
                    models.append(clean)
            token = payload.get("nextPageToken")
            next_url = f"{url}&pageToken={token}" if token else None
        models = list(dict.fromkeys(models))
        if not models:
            return False, [], "No Gemini generateContent models returned by API."
        return True, models, f"Found {len(models)} Gemini model(s)."
    except urllib.error.HTTPError as e:
        rb = e.read().decode("utf-8", errors="ignore")
        return False, [], f"Failed to list models (HTTP {e.code}): {rb}"
    except urllib.error.URLError as e:
        return False, [], f"Network error listing models: {e}"
    except Exception as e:
        return False, [], f"Failed to list models: {e}"


def choose_model_from_list(api_key: str, preferred: Optional[str] = None) -> Tuple[bool, Optional[str], str, List[str]]:
    ok, models, msg = list_generate_models(api_key)
    if not ok:
        return False, None, msg, []
    if preferred and preferred in models:
        return True, preferred, msg, models
    for c in ["gemini-2.5-flash-preview-05-20", "gemini-2.5-pro-preview-06-05", "gemini-2.0-flash"]:
        if c in models:
            return True, c, msg, models
    return True, models[0], msg, models


def validate_image_file(path: str) -> Tuple[bool, str]:
    if not os.path.exists(path):    return False, f"File not found: {path}"
    if not os.path.isfile(path):    return False, f"Not a file: {path}"
    try:
        mb = os.path.getsize(path) / (1024 * 1024)
        if mb > MAX_FILE_SIZE_MB:   return False, f"Too large ({mb:.1f} MB). Max: {MAX_FILE_SIZE_MB} MB"
    except Exception as e:          return False, f"Cannot read size: {e}"
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_IMAGE_FORMATS:
        return False, f"Unsupported: {ext}. Supported: {', '.join(SUPPORTED_IMAGE_FORMATS)}"
    return True, "OK"


def sanitize_deck_name(name: str) -> str:
    parts = name.split("::")
    clean = [re.sub(r'[\\/*?"<>|]', "", p).strip() for p in parts]
    return "::".join(p for p in clean if p) or "Imported"


def get_active_profile() -> Dict:
    key = CONFIG.get("active_profile", "MCQ")
    profiles = CONFIG.get("profiles", {})
    return profiles.get(key) or next(iter(profiles.values()), {})


# ============================================================================
# GEMINI API
# ============================================================================

def encode_image_base64(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        log_error(f"encode_image: {path}", e)
        return None


def get_gemini_response(api_key: str, model: str, current_path: str,
                        prev_path: Optional[str] = None,
                        prompt: Optional[str] = None) -> Tuple[bool, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    if prompt is None:
        prompt = get_active_profile().get("prompt", _SEED_MCQ_PROMPT)

    cur_b64 = encode_image_base64(current_path)
    if not cur_b64:
        return False, f"Failed to encode image: {current_path}"

    parts: List[Dict] = [{"text": prompt}]
    if prev_path:
        pb64 = encode_image_base64(prev_path)
        if pb64:
            parts += [{"text": "--- CONTEXT ONLY (Previous Page) ---"},
                      {"inline_data": {"mime_type": "image/jpeg", "data": pb64}}]
    parts += [{"text": "--- TARGET IMAGE (Generate Cards) ---"},
              {"inline_data": {"mime_type": "image/jpeg", "data": cur_b64}}]

    data = json.dumps({"contents": [{"parts": parts}]}).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            result = json.loads(r.read().decode())
        if not result.get("candidates"):
            return False, "No response candidates from API"
        candidate = result["candidates"][0]
        if candidate.get("finishReason") == "SAFETY":
            return False, "Content filtered by safety settings"
        text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
        return (True, text) if text else (False, "Empty response from API")
    except urllib.error.HTTPError as e:
        rb = e.read().decode("utf-8", errors="ignore")
        msgs = {400: f"Bad request (400): {rb}", 403: "API key invalid or unauthorized (403)",
                429: "Rate limit exceeded (429). Wait and retry.", 500: "Gemini server error (500). Retry."}
        return False, msgs.get(e.code, f"HTTP Error {e.code}: {rb}")
    except urllib.error.URLError as e:
        return False, f"Network error: {e}"
    except Exception as e:
        log_error("get_gemini_response", e)
        return False, str(e)


# ============================================================================
# CARD PARSERS
# ============================================================================

def _split_pipe(line: str, minimum: int) -> Optional[List[str]]:
    parts = line.split("|")
    return [p.strip() for p in parts] if len(parts) >= minimum else None


def parse_mcq_response(text: str) -> List[Dict]:
    cards = []
    for i, raw in enumerate(text.strip().split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        p = _split_pipe(line, 5)
        if not p:
            print(f"MCQ parser warning: line {i} has <5 parts, skipping"); continue
        if not p[1] or not p[2]:
            continue
        cards.append({"subtopic": p[0], SLOT_QUESTION: p[1],
                       SLOT_CHOICES: p[2], SLOT_ANSWER: p[3], SLOT_EXTRA: p[4]})
    return cards


def parse_cloze_response(text: str) -> List[Dict]:
    cards = []
    for i, raw in enumerate(text.strip().split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        p = _split_pipe(line, 2)
        if not p:
            print(f"Cloze parser warning: line {i} has <2 parts, skipping"); continue
        body = p[1] if len(p) > 1 else ""
        if not body or "{{c" not in body:
            print(f"Cloze parser warning: line {i} missing cloze syntax, skipping"); continue
        cards.append({"subtopic": p[0], SLOT_TEXT: body, SLOT_EXTRA: p[2] if len(p) > 2 else ""})
    return cards


def parse_basic_response(text: str) -> List[Dict]:
    cards = []
    for i, raw in enumerate(text.strip().split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        p = _split_pipe(line, 3)
        if not p:
            print(f"Basic parser warning: line {i} has <3 parts, skipping"); continue
        if not p[1] or not p[2]:
            continue
        cards.append({"subtopic": p[0], SLOT_QUESTION: p[1],
                       SLOT_ANSWER: p[2], SLOT_EXTRA: p[3] if len(p) > 3 else ""})
    return cards


def parse_response(text: str, fmt: str) -> List[Dict]:
    return {"mcq": parse_mcq_response, "cloze": parse_cloze_response,
            "basic": parse_basic_response}.get(fmt, parse_mcq_response)(text)


# ============================================================================
# NEW BLANK PROFILE DIALOG
# ============================================================================

class NewProfileDialog(QDialog):
    """Collect name + format for a brand-new user-written profile."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Custom Profile")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<h3>Create a New Profile</h3>"))
        layout.addWidget(QLabel(
            "<p>Give your profile a name and choose the card format it will produce.<br>"
            "The prompt box will start with a format guide — replace it with your own instructions.</p>"
            "<p><i>Tip: to tweak an existing built-in prompt, use <b>➕ Duplicate</b> instead.</i></p>"
        ))

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Low-Yield MCQ, Vocabulary, Step 1 Cloze…")
        self.name_edit.textChanged.connect(self._validate)
        form.addRow("<b>Profile Name:</b>", self.name_edit)

        self.fmt_combo = QComboBox()
        self.fmt_combo.addItem("Multiple Choice (MCQ)",  "mcq")
        self.fmt_combo.addItem("Cloze Deletion",         "cloze")
        self.fmt_combo.addItem("Basic (Front / Back)",   "basic")
        form.addRow("<b>Card Format:</b>", self.fmt_combo)
        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        self.ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setEnabled(False)
        layout.addWidget(btns)

    def _validate(self):
        self.ok_btn.setEnabled(bool(self.name_edit.text().strip()))

    def values(self) -> Tuple[str, str]:
        return self.name_edit.text().strip(), self.fmt_combo.currentData()


# ============================================================================
# WELCOME WIZARD
# ============================================================================

class WelcomeWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {ADDON_NAME}!")
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"""
        <h2>Welcome to {ADDON_NAME} v{VERSION}!</h2>
        <p>Quick setup in 2 steps:</p>
        <ol>
          <li><b>Get your Gemini API Key</b> (free from Google)</li>
          <li><b>Download and install the Note Type</b> (MCQ cards only)</li>
        </ol>"""))

        layout.addWidget(QLabel("<hr>"))
        layout.addWidget(QLabel("<h3>Step 1: Gemini API Key</h3>"))
        help_lbl = QLabel(
            '<p>1. Visit <a href="https://aistudio.google.com/app/apikey">Google AI Studio</a><br>'
            '2. Sign in and click "Create API Key"<br>'
            '3. Paste the key below</p>'
            '<p><i>Free tier includes generous usage limits.</i></p>'
        )
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setWordWrap(True)
        layout.addWidget(help_lbl)

        self.api_input = QLineEdit()
        self.api_input.setPlaceholderText("AIzaSy…")
        self.api_input.textChanged.connect(lambda: self.finish_btn.setEnabled(bool(self.api_input.text().strip())))
        layout.addWidget(self.api_input)

        self.api_status = QLabel("")
        self.api_status.setWordWrap(True)
        layout.addWidget(self.api_status)

        test_btn = QPushButton("Test API Connection")
        test_btn.clicked.connect(self._test_api)
        layout.addWidget(test_btn)

        layout.addWidget(QLabel("<hr>"))
        layout.addWidget(QLabel("<h3>Step 2: Note Type (MCQ only)</h3>"))
        nt_lbl = QLabel(
            "<p><b>Only needed for MCQ cards.</b> Basic and Cloze use Anki's built-in types.</p>"
            "<p>1. Click below → download the .apkg file<br>"
            "2. In Anki: File → Import → select file<br>"
            "3. Click \"I've Installed It\" below</p>"
        )
        nt_lbl.setWordWrap(True)
        layout.addWidget(nt_lbl)

        open_btn = QPushButton("🌐 Open Note Type Download Page")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(NOTE_TYPE_DOWNLOAD_URL)))
        layout.addWidget(open_btn)

        confirm_btn = QPushButton("✓ I've Installed the Note Type")
        confirm_btn.clicked.connect(self._confirm_nt)
        layout.addWidget(confirm_btn)

        self.nt_status = QLabel("Status: Not installed yet (optional for Basic/Cloze)")
        self.nt_status.setWordWrap(True)
        layout.addWidget(self.nt_status)

        layout.addWidget(QLabel("<hr>"))
        row = QHBoxLayout()
        self.finish_btn = QPushButton("✓ Finish Setup")
        self.finish_btn.clicked.connect(self._finish)
        self.finish_btn.setEnabled(False)
        row.addWidget(self.finish_btn)
        skip_btn = QPushButton("Skip (Configure Later)")
        skip_btn.clicked.connect(self._skip)
        row.addWidget(skip_btn)
        layout.addLayout(row)

    def _test_api(self):
        key = self.api_input.text().strip()
        v, msg = validate_api_key(key)
        if not v:
            self.api_status.setText(f"<span style='color:red'>❌ {msg}</span>"); return
        self.api_status.setText("Testing…")
        QApplication.processEvents()
        ok, model, msg, _ = choose_model_from_list(key)
        if not ok or not model:
            self.api_status.setText(f"<span style='color:red'>❌ {msg}</span>"); return
        ok, msg = test_api_connection(key, model)
        color, icon = ("green", "✓") if ok else ("red", "❌")
        self.api_status.setText(f"<span style='color:{color}'>{icon} {msg}</span>")

    def _confirm_nt(self):
        mcq = [m for m in mw.col.models.all() if "Multiple Choice" in m["name"] or "MCQ" in m["name"]]
        if mcq:
            self.nt_status.setText(f"<span style='color:green'>✓ Found: {mcq[0]['name']}</span>")
        elif askUser("No MCQ note type detected. Mark as installed anyway?"):
            self.nt_status.setText("<span style='color:orange'>⚠ Marked installed (none detected)</span>")

    def _finish(self):
        CONFIG["api_key"] = self.api_input.text().strip()
        CONFIG["show_welcome"] = False
        for m in mw.col.models.all():
            if "Multiple Choice" in m["name"] or "MCQ" in m["name"]:
                CONFIG["note_type_id"] = m["id"]; break
        mw.addonManager.writeConfig(__name__, CONFIG)
        self.accept()
        showInfo(f"Setup complete!\n\nUse ⚡ MCQ Importer → Import Images… to get started.")

    def _skip(self):
        CONFIG["show_welcome"] = False
        mw.addonManager.writeConfig(__name__, CONFIG)
        self.reject()


# ============================================================================
# FIELD MAPPING WIDGET
# ============================================================================

class FieldMappingWidget(QGroupBox):
    def __init__(self, fmt: str, field_map: Dict[str, str], anki_fields: List[str], parent=None):
        super().__init__("Field Mapping", parent)
        self.combos: Dict[str, QComboBox] = {}
        layout = QFormLayout(self)
        slots = SLOT_META.get(fmt, [])
        if not slots:
            layout.addRow(QLabel("No field mapping needed for this format.")); return

        # Track claimed indices so fuzzy fallback avoids already-mapped fields
        claimed: set = set()

        for slot_key, slot_label, slot_desc in slots:
            combo = QComboBox()
            combo.addItems(anki_fields)
            current = field_map.get(slot_key, "")
            idx = combo.findText(current)
            if idx >= 0:
                # Exact match from saved config — always trust it
                combo.setCurrentIndex(idx)
                claimed.add(idx)
            elif anki_fields:
                # Fuzzy: search all words in the label (skip tiny words)
                kws = [w for w in re.split(r"[\s/()]+", slot_label.lower()) if len(w) > 2]
                matched = -1
                # Prefer unclaimed fields first
                for i, f in enumerate(anki_fields):
                    if i not in claimed and any(kw in f.lower() for kw in kws):
                        matched = i; break
                # Allow claimed fields if still nothing matched
                if matched < 0:
                    for i, f in enumerate(anki_fields):
                        if any(kw in f.lower() for kw in kws):
                            matched = i; break
                # Only apply if a keyword actually matched — never silently pick index 0
                if matched >= 0:
                    combo.setCurrentIndex(matched)
                    claimed.add(matched)
            lbl = QLabel(f"<b>{slot_label}</b><br><small>{slot_desc}</small>")
            lbl.setWordWrap(True)
            layout.addRow(lbl, combo)
            self.combos[slot_key] = combo

    def get_mapping(self) -> Dict[str, str]:
        return {s: c.currentText() for s, c in self.combos.items()}

    def update_anki_fields(self, anki_fields: List[str]):
        for slot, combo in self.combos.items():
            cur = combo.currentText()
            combo.clear(); combo.addItems(anki_fields)
            idx = combo.findText(cur)
            if idx >= 0: combo.setCurrentIndex(idx)


# ============================================================================
# SETTINGS DIALOG
# ============================================================================

class GeminiSettings(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{ADDON_NAME} Settings")
        self.setMinimumWidth(760)
        self.setMinimumHeight(730)

        self._profiles: Dict = copy.deepcopy(CONFIG.get("profiles", {}))
        self._active_key: str = CONFIG.get("active_profile", "MCQ")
        self._fmap_widget: Optional[FieldMappingWidget] = None

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── Tab 1: API ────────────────────────────────────────────────────
        api_tab = QWidget(); al = QVBoxLayout(api_tab)
        tabs.addTab(api_tab, "API Settings")

        al.addWidget(QLabel("<h3>Gemini API Configuration</h3>"))
        lnk = QLabel('<p>Get your free key at <a href="https://aistudio.google.com/app/apikey">Google AI Studio</a>.</p>')
        lnk.setOpenExternalLinks(True); lnk.setWordWrap(True)
        al.addWidget(lnk)
        al.addWidget(QLabel("<b>API Key:</b>"))
        self.api_input = QLineEdit(CONFIG.get("api_key", ""))
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_input.setPlaceholderText("AIzaSy…")
        al.addWidget(self.api_input)
        show_btn = QPushButton("👁 Show/Hide Key")
        show_btn.clicked.connect(self._toggle_key_vis)
        al.addWidget(show_btn)
        self.api_status_lbl = QLabel(""); self.api_status_lbl.setWordWrap(True)
        al.addWidget(self.api_status_lbl)
        test_btn = QPushButton("Test API Connection")
        test_btn.clicked.connect(self._test_api)
        al.addWidget(test_btn)
        al.addWidget(QLabel("<hr>"))
        al.addWidget(QLabel("<b>Gemini Model:</b>"))
        al.addWidget(QLabel("<i>Flash = faster/cheaper · Pro = more capable</i>"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(GEMINI_MODELS)
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText(CONFIG.get("model", "gemini-2.5-flash-preview-05-20"))
        al.addWidget(self.model_combo)
        ref_btn = QPushButton("🔄 Refresh Available Models")
        ref_btn.clicked.connect(self._refresh_models)
        al.addWidget(ref_btn)
        al.addStretch()

        # ── Tab 2: Prompt Profiles ────────────────────────────────────────
        pt = QWidget(); pl = QVBoxLayout(pt)
        tabs.addTab(pt, "Prompt Profiles")

        pl.addWidget(QLabel("<h3>Prompt Profiles</h3>"))
        pl.addWidget(QLabel(
            "<p>Each profile has its own prompt sent to Gemini. "
            "The <b>active profile</b> is used on every import run. "
            "Prompts are saved in your Anki config file and <b>survive addon updates</b> — "
            "your edits are never overwritten. "
            "Use <b>↩ Reset</b> to restore a built-in default prompt.</p>"
        ))

        # Selector row
        sr = QHBoxLayout()
        sr.addWidget(QLabel("<b>Profile:</b>"))
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        sr.addWidget(self.profile_combo, 1)

        star_btn = QPushButton("⭐ Set as Active")
        star_btn.setToolTip("Use this profile for the next import")
        star_btn.clicked.connect(self._set_active)
        sr.addWidget(star_btn)

        dup_btn = QPushButton("➕ Duplicate")
        dup_btn.setToolTip("Copy this profile — great for tweaking a built-in")
        dup_btn.clicked.connect(self._duplicate)
        sr.addWidget(dup_btn)

        new_btn = QPushButton("✏ New Blank")
        new_btn.setToolTip("Create a profile with your own prompt from scratch")
        new_btn.clicked.connect(self._new_blank)
        sr.addWidget(new_btn)

        del_btn = QPushButton("🗑 Delete")
        del_btn.setToolTip("Delete selected profile (built-ins are protected)")
        del_btn.clicked.connect(self._delete)
        sr.addWidget(del_btn)

        pl.addLayout(sr)

        self.active_ind = QLabel(""); self.active_ind.setWordWrap(True)
        pl.addWidget(self.active_ind)

        nr = QHBoxLayout()
        nr.addWidget(QLabel("<b>Display Name:</b>"))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_name_changed)
        nr.addWidget(self.name_edit)
        pl.addLayout(nr)

        fr = QHBoxLayout()
        fr.addWidget(QLabel("<b>Card Format:</b>"))
        self.fmt_lbl = QLabel("")
        fr.addWidget(self.fmt_lbl, 1)
        pl.addLayout(fr)

        pl.addWidget(QLabel(
            "<b>Prompt Text</b> — edit freely. Sent directly to Gemini. "
            "Stored in your config; <i>never</i> overwritten by addon updates."
        ))
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMinimumHeight(280)
        self.prompt_edit.setFont(QFont("Courier New", 9))
        self.prompt_edit.textChanged.connect(self._on_prompt_changed)
        pl.addWidget(self.prompt_edit)

        br = QHBoxLayout()
        reset_btn = QPushButton("↩ Reset to Built-in Default")
        reset_btn.setToolTip("Restore factory prompt (built-in profiles only)")
        reset_btn.clicked.connect(self._reset_prompt)
        br.addWidget(reset_btn)
        br.addStretch()
        self.char_lbl = QLabel("")
        br.addWidget(self.char_lbl)
        pl.addLayout(br)

        # ── Tab 3: Note Type & Field Mapping ─────────────────────────────
        nt = QWidget(); nl = QVBoxLayout(nt)
        tabs.addTab(nt, "Note Type & Fields")

        nl.addWidget(QLabel("<h3>Note Type & Field Mapping</h3>"))
        nl.addWidget(QLabel(
            "<p>Select the Anki note type for the <b>active profile</b>, then map each logical slot "
            "to the correct field in that note type. Handles any field naming convention.</p>"
        ))
        nl.addWidget(QLabel(
            f'<p><b>Need the MCQ note type?</b> '
            f'<a href="{NOTE_TYPE_DOWNLOAD_URL}">Download here</a></p>'
        ))
        dl_btn = QPushButton("🌐 Open Note Type Download Page")
        dl_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(NOTE_TYPE_DOWNLOAD_URL)))
        nl.addWidget(dl_btn)
        nl.addWidget(QLabel("<hr>"))

        ntr = QHBoxLayout()
        ntr.addWidget(QLabel("<b>Note Type:</b>"))
        self.nt_combo = QComboBox()
        self.nt_combo.currentIndexChanged.connect(self._on_nt_changed)
        ntr.addWidget(self.nt_combo, 1)
        ref_nt = QPushButton("🔄 Refresh")
        ref_nt.clicked.connect(lambda: self._refresh_note_types())
        ntr.addWidget(ref_nt)
        fld_btn = QPushButton("View All Fields")
        fld_btn.clicked.connect(self._show_fields)
        ntr.addWidget(fld_btn)
        nl.addLayout(ntr)

        self.fmap_container = QVBoxLayout()
        nl.addLayout(self.fmap_container)
        nl.addStretch()

        # ── Tab 4: Advanced ───────────────────────────────────────────────
        av_tab = QWidget(); av = QVBoxLayout(av_tab)
        tabs.addTab(av_tab, "Advanced")

        av.addWidget(QLabel("<h3>Advanced Options</h3>"))
        self.auto_open_cb = QCheckBox("Automatically open media folder after import")
        self.auto_open_cb.setChecked(CONFIG.get("auto_open_media", True))
        av.addWidget(self.auto_open_cb)
        av.addWidget(QLabel("<br><b>Batch Processing:</b>"))
        batch_r = QHBoxLayout()
        batch_r.addWidget(QLabel("Batch size:"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 50)
        self.batch_spin.setValue(CONFIG.get("batch_size", 10))
        batch_r.addWidget(self.batch_spin); batch_r.addStretch()
        av.addLayout(batch_r)
        av.addWidget(QLabel("<hr>"))
        self.startup_cb = QCheckBox("Validate API connection on Anki startup (slower startup)")
        self.startup_cb.setChecked(CONFIG.get("validate_api_on_startup", False))
        av.addWidget(self.startup_cb)
        av.addWidget(QLabel("<hr>"))
        ra_btn = QPushButton("Reset ALL Built-in Profile Prompts to Factory Defaults")
        ra_btn.setToolTip("Only resets MCQ, Cloze, Basic prompts. Custom profiles untouched.")
        ra_btn.clicked.connect(self._reset_all_prompts)
        av.addWidget(ra_btn)
        av.addStretch()

        # Bottom save/cancel
        bot = QHBoxLayout()
        save_btn = QPushButton("💾 Save Settings")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        bot.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bot.addWidget(cancel_btn)
        layout.addLayout(bot)

        self._refresh_note_types(silent=True)
        self._refresh_profile_combo()

    # ── profile helpers ───────────────────────────────────────────────────

    def _refresh_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for key, p in self._profiles.items():
            label = p.get("display_name", key)
            if key == self._active_key: label = f"⭐ {label}"
            self.profile_combo.addItem(label, key)
        idx = self.profile_combo.findData(self._active_key)
        self.profile_combo.setCurrentIndex(max(idx, 0))
        self.profile_combo.blockSignals(False)
        self._on_profile_changed(self.profile_combo.currentIndex())

    def _cur_key(self) -> str:
        return self.profile_combo.currentData() or list(self._profiles.keys())[0]

    def _on_profile_changed(self, _i: int):
        key = self._cur_key()
        p   = self._profiles.get(key, {})

        self.name_edit.blockSignals(True)
        self.name_edit.setText(p.get("display_name", key))
        self.name_edit.blockSignals(False)

        fmt = p.get("format", "mcq")
        labels = {"mcq": "Multiple Choice (MCQ)", "cloze": "Cloze Deletion", "basic": "Basic (Front/Back)"}
        self.fmt_lbl.setText(f"<i>{labels.get(fmt, fmt)}</i>")

        self.prompt_edit.blockSignals(True)
        self.prompt_edit.setPlainText(p.get("prompt", ""))
        self.prompt_edit.blockSignals(False)
        self._update_chars()

        if key == self._active_key:
            self.active_ind.setText("<span style='color:green'>⭐ This is the <b>active profile</b> — used on next import.</span>")
        else:
            self.active_ind.setText("<span style='color:gray'>Not active. Click ⭐ Set as Active to use on import.</span>")

        self._rebuild_fmap(p)

    def _on_name_changed(self, text: str):
        key = self._cur_key()
        if key in self._profiles:
            self._profiles[key]["display_name"] = text
            label = text if key != self._active_key else f"⭐ {text}"
            self.profile_combo.setItemText(self.profile_combo.currentIndex(), label)

    def _on_prompt_changed(self):
        key = self._cur_key()
        if key in self._profiles:
            self._profiles[key]["prompt"] = self.prompt_edit.toPlainText()
        self._update_chars()

    def _update_chars(self):
        self.char_lbl.setText(f"<small>{len(self.prompt_edit.toPlainText()):,} chars</small>")

    def _set_active(self):
        key = self._cur_key()
        self._active_key = key
        self._refresh_profile_combo()
        tooltip(f"Active profile: {self._profiles[key].get('display_name', key)}", period=2000)

    def _duplicate(self):
        key = self._cur_key()
        p   = copy.deepcopy(self._profiles[key])
        base = p.get("display_name", key) + " (Copy)"
        new_key = base; n = 1
        while new_key in self._profiles:
            new_key = f"{base} {n}"; n += 1
        p["display_name"] = base
        self._profiles[new_key] = p
        self._refresh_profile_combo()
        idx = self.profile_combo.findData(new_key)
        if idx >= 0: self.profile_combo.setCurrentIndex(idx)
        tooltip(f"Duplicated as '{base}'", period=2000)

    def _new_blank(self):
        dlg = NewProfileDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        display, fmt = dlg.values()
        new_key = display; n = 1
        while new_key in self._profiles:
            new_key = f"{display} {n}"; n += 1

        # Pick field map from a matching built-in schema
        schema = next((s for s in _DEFAULT_PROFILE_SCHEMA.values() if s["format"] == fmt),
                      _DEFAULT_PROFILE_SCHEMA["MCQ"])
        self._profiles[new_key] = {
            "display_name": display,
            "format":       fmt,
            "prompt":       _BLANK_PROMPT_SCAFFOLDS.get(fmt, ""),
            "field_map":    copy.deepcopy(schema["field_map"]),
        }
        self._refresh_profile_combo()
        idx = self.profile_combo.findData(new_key)
        if idx >= 0: self.profile_combo.setCurrentIndex(idx)
        tooltip(f"Created '{display}'. Write your prompt in the text box.", period=3000)

    def _delete(self):
        key = self._cur_key()
        if key in BUILTIN_PROFILE_KEYS:
            showWarning("Cannot delete the built-in MCQ, Cloze, or Basic profiles.\n\n"
                        "You can freely edit their prompts, or duplicate them to create custom versions.")
            return
        name = self._profiles[key].get("display_name", key)
        if not askUser(f"Delete profile '{name}'?\n\nThis cannot be undone."):
            return
        del self._profiles[key]
        if self._active_key == key: self._active_key = "MCQ"
        self._refresh_profile_combo()

    def _reset_prompt(self):
        key  = self._cur_key()
        seed = _SEED_PROMPTS.get(key)
        if not seed:
            showWarning("Only the three built-in profiles (MCQ, Cloze, Basic) have factory defaults.\n\n"
                        "Custom profiles don't have a default to reset to.")
            return
        if not askUser("Reset this prompt to the factory default?\n\nYour current edits will be lost."):
            return
        self._profiles[key]["prompt"] = seed
        self.prompt_edit.blockSignals(True)
        self.prompt_edit.setPlainText(seed)
        self.prompt_edit.blockSignals(False)
        self._update_chars()
        tooltip("Prompt reset to factory default.", period=2000)

    # ── note type helpers ─────────────────────────────────────────────────

    def _refresh_note_types(self, silent: bool = False):
        self.nt_combo.blockSignals(True)
        self.nt_combo.clear()
        for m in mw.col.models.all():
            self.nt_combo.addItem(m["name"], m["id"])
        saved = CONFIG.get("note_type_id")
        if saved:
            idx = self.nt_combo.findData(saved)
            if idx >= 0: self.nt_combo.setCurrentIndex(idx)
        self.nt_combo.blockSignals(False)
        if not silent: self._on_nt_changed(self.nt_combo.currentIndex())

    def _on_nt_changed(self, _i: int):
        if self._fmap_widget:
            self._fmap_widget.update_anki_fields(self._anki_fields())

    def _anki_fields(self) -> List[str]:
        nt_id = self.nt_combo.currentData()
        if not nt_id: return []
        m = mw.col.models.get(nt_id)
        return [f["name"] for f in m["flds"]] if m else []

    def _rebuild_fmap(self, profile: Dict):
        if self._fmap_widget:
            self.fmap_container.removeWidget(self._fmap_widget)
            self._fmap_widget.deleteLater()
            self._fmap_widget = None
        w = FieldMappingWidget(profile.get("format", "mcq"),
                               profile.get("field_map", {}),
                               self._anki_fields())
        self.fmap_container.addWidget(w)
        self._fmap_widget = w

    def _show_fields(self):
        nt_id = self.nt_combo.currentData()
        if not nt_id: showWarning("Select a note type first."); return
        m = mw.col.models.get(nt_id)
        if not m: showWarning("Note type not found."); return
        fields = "\n".join(f"{i+1}. {f['name']}" for i, f in enumerate(m["flds"]))
        showInfo(f"Fields in '{m['name']}':\n\n{fields}")

    # ── API helpers ───────────────────────────────────────────────────────

    def _toggle_key_vis(self):
        mode = (QLineEdit.EchoMode.Normal if self.api_input.echoMode() == QLineEdit.EchoMode.Password
                else QLineEdit.EchoMode.Password)
        self.api_input.setEchoMode(mode)

    def _test_api(self):
        key   = self.api_input.text().strip()
        model = self.model_combo.currentText().strip()
        if not key:
            self.api_status_lbl.setText("<span style='color:red'>Enter an API key first</span>"); return
        v, msg = validate_api_key(key)
        if not v:
            self.api_status_lbl.setText(f"<span style='color:red'>❌ {msg}</span>"); return
        self.api_status_lbl.setText("Testing…")
        QApplication.processEvents()
        ok, sel, lmsg, _ = choose_model_from_list(key, model)
        if not ok or not sel:
            self.api_status_lbl.setText(f"<span style='color:red'>❌ {lmsg}</span>"); return
        if sel != model: self.model_combo.setCurrentText(sel)
        ok, msg = test_api_connection(key, sel)
        c, i = ("green", "✓") if ok else ("red", "❌")
        self.api_status_lbl.setText(f"<span style='color:{c}'>{i} {msg}</span>")
        if ok: tooltip(f"Connection successful! {lmsg}", period=3000)

    def _refresh_models(self):
        key = self.api_input.text().strip()
        if not key:
            self.api_status_lbl.setText("<span style='color:red'>Enter API key first.</span>"); return
        self.api_status_lbl.setText("Refreshing…")
        QApplication.processEvents()
        ok, models, msg = list_generate_models(key)
        if not ok:
            self.api_status_lbl.setText(f"<span style='color:red'>❌ {msg}</span>"); return
        cur = self.model_combo.currentText().strip()
        self.model_combo.clear(); self.model_combo.addItems(models); self.model_combo.setEditable(True)
        self.model_combo.setCurrentText(cur if cur in models else models[0])
        self.api_status_lbl.setText(f"<span style='color:green'>✓ {msg}</span>")

    def _reset_all_prompts(self):
        if not askUser("Reset all three built-in prompts (MCQ, Cloze, Basic) to factory defaults?\n\n"
                       "Custom profiles are untouched. API key and note type are preserved."):
            return
        for key, seed in _SEED_PROMPTS.items():
            if key in self._profiles:
                self._profiles[key]["prompt"] = seed
        cur = self._cur_key()
        if cur in BUILTIN_PROFILE_KEYS:
            self.prompt_edit.blockSignals(True)
            self.prompt_edit.setPlainText(self._profiles[cur]["prompt"])
            self.prompt_edit.blockSignals(False)
            self._update_chars()
        tooltip("Built-in prompts reset to factory defaults.", period=2000)

    # ── save ──────────────────────────────────────────────────────────────

    def _save(self):
        key = self.api_input.text().strip()
        if key:
            v, msg = validate_api_key(key)
            if not v: showWarning(f"Invalid API key:\n\n{msg}"); return

        nt_id = self.nt_combo.currentData()
        if not nt_id:
            if not askUser("No note type selected. Continue anyway?"):
                return

        # Flush current field mapping into its profile
        pk = self._cur_key()
        if self._fmap_widget and pk in self._profiles:
            self._profiles[pk]["field_map"] = self._fmap_widget.get_mapping()

        CONFIG["api_key"]               = key
        CONFIG["model"]                 = self.model_combo.currentText().strip()
        CONFIG["note_type_id"]          = nt_id
        CONFIG["active_profile"]        = self._active_key
        CONFIG["profiles"]              = self._profiles
        CONFIG["auto_open_media"]       = self.auto_open_cb.isChecked()
        CONFIG["batch_size"]            = self.batch_spin.value()
        CONFIG["validate_api_on_startup"] = self.startup_cb.isChecked()

        mw.addonManager.writeConfig(__name__, CONFIG)
        self.accept()
        tooltip("Settings saved!", period=2000)


# ============================================================================
# PROGRESS DIALOG
# ============================================================================

class ImportProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Progress")
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowCloseButtonHint)
        layout = QVBoxLayout(self)
        self.status_lbl = QLabel("Initializing…"); self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)
        self.progress_bar = QProgressBar(); layout.addWidget(self.progress_bar)
        self.detail_box = QTextEdit(); self.detail_box.setReadOnly(True)
        self.detail_box.setMaximumHeight(150); layout.addWidget(self.detail_box)
        self.cancel_btn = QPushButton("Cancel Import")
        self.cancel_btn.clicked.connect(self._cancel)
        layout.addWidget(self.cancel_btn)
        self.cancelled = False; self.complete = False

    def update_progress(self, cur: int, total: int, status: str):
        self.progress_bar.setMaximum(total); self.progress_bar.setValue(cur)
        self.status_lbl.setText(f"{status} ({cur}/{total})")
        QApplication.processEvents()

    def add_detail(self, msg: str):
        self.detail_box.append(msg); QApplication.processEvents()

    def is_cancelled(self): return self.cancelled

    def mark_complete(self):
        self.complete = True; self.cancel_btn.setText("Close")
        self.status_lbl.setText("Import Complete!")

    def _cancel(self):
        if self.complete:
            self.accept()
        elif askUser("Cancel import?\n\nAlready imported cards will be kept."):
            self.cancelled = True; self.cancel_btn.setEnabled(False)
            self.status_lbl.setText("Cancelling…")

    def closeEvent(self, e):
        if self.complete: e.accept()
        elif askUser("Cancel import?\n\nAlready imported cards will be kept."):
            self.cancelled = True; self.cancel_btn.setEnabled(False)
            self.status_lbl.setText("Cancelling…"); e.accept()
        else: e.ignore()


# ============================================================================
# MAIN IMPORT WORKFLOW
# ============================================================================

def run_importer():
    api_key    = CONFIG.get("api_key", "").strip()
    model_name = CONFIG.get("model", "gemini-2.5-flash-preview-05-20").strip()

    if not api_key:
        showWarning("API Key not configured.\n\nPlease set it in Settings.")
        open_settings(); return

    v, msg = validate_api_key(api_key)
    if not v:
        showWarning(f"Invalid API key:\n\n{msg}"); open_settings(); return

    ok, resolved, mmsg, _ = choose_model_from_list(api_key, model_name)
    if not ok or not resolved:
        showWarning(f"Could not resolve a Gemini model:\n\n{mmsg}"); return
    model_name = resolved

    # Active profile
    profiles    = CONFIG.get("profiles", {})
    profile_key = CONFIG.get("active_profile", "MCQ")
    profile     = profiles.get(profile_key) or next(iter(profiles.values()), {})
    fmt         = profile.get("format", "mcq")
    prompt      = profile.get("prompt", _SEED_MCQ_PROMPT)
    field_map   = profile.get("field_map", {})
    display     = profile.get("display_name", profile_key)

    # Note type
    nt_id = CONFIG.get("note_type_id")
    if not nt_id:
        showWarning("Note Type not selected.\n\nGo to Settings → Note Type & Fields.")
        open_settings(); return
    anki_model = mw.col.models.get(nt_id)
    if not anki_model:
        showWarning("Selected Note Type not found. It may have been deleted.")
        open_settings(); return
    if len(anki_model["flds"]) < 2:
        showWarning(f"Note Type '{anki_model['name']}' has too few fields."); return
    mw.col.models.set_current(anki_model)

    # Deck name
    root_deck, ok = getText(
        f"Enter Root Deck Name:\n\nProfile: {display}\n\n"
        "Cards → Root Deck::Subtopic Name\n\nExample: 'Medical::Pharmacology'",
        mw, title="Import to Deck",
    )
    if not ok or not root_deck: return
    root_deck = sanitize_deck_name(root_deck)

    # Image files
    file_paths, _ = QFileDialog.getOpenFileNames(
        mw, "Select Images to Import", "",
        "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;All Files (*)",
    )
    if not file_paths: return

    valid_files, invalid_files = [], []
    for fp in file_paths:
        ext = os.path.splitext(fp)[1].lower()
        if ext not in SUPPORTED_IMAGE_FORMATS:
            invalid_files.append((os.path.basename(fp), f"Unsupported: {ext}")); continue
        ok2, msg2 = validate_image_file(fp)
        if ok2: valid_files.append(fp)
        else:   invalid_files.append((os.path.basename(fp), msg2))

    if not valid_files:
        lines = "\n".join(f"• {n}: {m}" for n, m in invalid_files[:5])
        if len(invalid_files) > 5: lines += f"\n… and {len(invalid_files)-5} more"
        showWarning(f"No valid images found.\n\n{lines}" if invalid_files else "No image files selected.")
        return

    def nat(p): return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", p)]
    valid_files.sort(key=lambda p: nat(os.path.basename(p)))

    confirm = (f"Ready to import:\n\n• Profile: {display}\n• Images: {len(valid_files)}\n"
               f"• Root Deck: {root_deck}\n• Note Type: {anki_model['name']}\n• Model: {model_name}\n")
    if invalid_files: confirm += f"\n⚠ Skipping {len(invalid_files)} invalid files"
    if not askUser(confirm + "\n\nProceed?"): return

    # Field resolution
    anki_fields = [f["name"] for f in anki_model["flds"]]
    def resolve(slot: str, fb: int = 0) -> Optional[str]:
        mapped = field_map.get(slot)
        if mapped and mapped in anki_fields: return mapped
        return anki_fields[fb] if fb < len(anki_fields) else None

    # Initialise all field variables to None so they're always defined
    fq = fc = fa = ft = fe = None

    if fmt == "mcq":
        fq = resolve(SLOT_QUESTION, 0); fc = resolve(SLOT_CHOICES, 1)
        fa = resolve(SLOT_ANSWER, 2);   fe = resolve(SLOT_EXTRA, 3)
    elif fmt == "cloze":
        ft = resolve(SLOT_TEXT, 0);     fe = resolve(SLOT_EXTRA, 1)
    else:  # basic
        fq = resolve(SLOT_QUESTION, 0); fa = resolve(SLOT_ANSWER, 1); fe = resolve(SLOT_EXTRA, 2)

    prog = ImportProgressDialog(mw)
    prog.show()
    maps = {"mcq":   f"  Question → {fq}\n  Choices  → {fc}\n  Answer   → {fa}\n  Extra    → {fe or 'N/A'}",
            "cloze": f"  Text  → {ft}\n  Extra → {fe or 'N/A'}",
            "basic": f"  Front → {fq}\n  Back  → {fa}\n  Extra → {fe or 'N/A'}"}
    prog.add_detail(f"Field Mapping ({fmt.upper()}):\n{maps.get(fmt,'')}")

    cards_created = files_ok = files_err = 0
    prev_path = None; error_log = []

    try:
        for idx, fp in enumerate(valid_files):
            if prog.is_cancelled(): break
            fname = os.path.basename(fp)
            prog.update_progress(idx + 1, len(valid_files), f"Processing: {fname}")

            try:
                anki_fname = mw.col.media.add_file(fp)
            except Exception:
                m = f"Failed to add media: {fname}"
                prog.add_detail(f"❌ {m}"); error_log.append((fname, m)); files_err += 1; continue

            prog.add_detail("🤖 Calling Gemini API…")
            ok, resp = get_gemini_response(api_key, model_name, fp, prev_path, prompt=prompt)
            if not ok:
                m = f"API Error: {resp}"
                prog.add_detail(f"❌ {m}"); error_log.append((fname, m)); files_err += 1
                if "403" in resp or "invalid" in resp.lower():
                    showWarning(f"Critical API Error:\n\n{resp}\n\nStopping."); break
                continue

            cards = parse_response(resp, fmt)
            if not cards:
                m = "No valid cards in response"
                prog.add_detail(f"⚠ {m}"); error_log.append((fname, m)); files_err += 1; continue

            img_tag = f"<br><br><img src='{anki_fname}'>"
            fc_count = 0
            for card in cards:
                try:
                    sub     = sanitize_deck_name(card.get("subtopic", "") or "General")
                    deck_id = mw.col.decks.id(f"{root_deck}::{sub}")
                    note    = Note(mw.col, anki_model)
                    note.note_type()["did"] = deck_id

                    # Build ordered (field_name, content) pairs for this format.
                    # Order matters: first write wins priority, later writes append.
                    if fmt == "mcq":
                        writes = [
                            (fq, card.get(SLOT_QUESTION, "")),
                            (fc, card.get(SLOT_CHOICES,  "")),
                            (fa, card.get(SLOT_ANSWER,   "")),
                            (fe, card.get(SLOT_EXTRA,    "") + img_tag),
                        ]
                    elif fmt == "cloze":
                        writes = [
                            (ft, card.get(SLOT_TEXT,  "")),
                            (fe, card.get(SLOT_EXTRA, "") + img_tag),
                        ]
                    else:  # basic
                        writes = [
                            (fq, card.get(SLOT_QUESTION, "")),
                            (fa, card.get(SLOT_ANSWER,   "")),
                            (fe, card.get(SLOT_EXTRA,    "") + img_tag),
                        ]

                    # Merge: when two slots point to the same Anki field,
                    # append the later content below the earlier one.
                    field_content: Dict[str, str] = {}
                    for field_name, content in writes:
                        if not field_name:
                            continue  # slot not mapped, skip
                        stripped = content.strip()
                        if not stripped or stripped == img_tag.strip():
                            # Only write empty/bare-image content if field not yet touched
                            if field_name not in field_content:
                                field_content[field_name] = content
                        elif field_name in field_content:
                            existing = field_content[field_name].strip()
                            sep = "<br><br>" if existing else ""
                            field_content[field_name] = field_content[field_name] + sep + content
                        else:
                            field_content[field_name] = content

                    for field_name, content in field_content.items():
                        note[field_name] = content

                    mw.col.add_note(note, deck_id)
                    fc_count += 1; cards_created += 1
                except Exception as e:
                    m = f"Card error: {e}"
                    prog.add_detail(f"⚠ {m}"); error_log.append((fname, m))

            if fc_count > 0:
                prog.add_detail(f"✓ {fc_count} cards from {fname}"); files_ok += 1

            prev_path = fp

    except Exception as e:
        log_error("run_importer", e)
        showWarning(f"Critical error:\n\n{e}\n\nCheck console for details.")
    finally:
        prog.mark_complete(); mw.reset()

    result = (f"Import Complete!\n\n✓ Profile: {display}\n"
              f"✓ Files processed: {files_ok}/{len(valid_files)}\n"
              f"✓ Cards created: {cards_created}\n")
    if files_err: result += f"\n⚠ Files with errors: {files_err}\n"
    prog.add_detail(f"\n{result}")

    if error_log and askUser(f"{result}\n\nView error details?"):
        details = "\n".join(f"{f}: {m}" for f, m in error_log[:20])
        if len(error_log) > 20: details += f"\n\n… and {len(error_log)-20} more"
        showInfo(f"Error Details:\n\n{details}")

    if CONFIG.get("auto_open_media", True) and cards_created > 0:
        if askUser("Open media collection folder?"):
            try: QDesktopServices.openUrl(QUrl.fromLocalFile(mw.col.media.dir()))
            except Exception as e: log_error("open_media", e)


# ============================================================================
# MENU & INITIALISATION
# ============================================================================

def open_settings():
    GeminiSettings(mw).exec()


def show_about():
    showInfo(f"""
    <h2>{ADDON_NAME} v{VERSION}</h2>
    <p><b>Batch import flashcards from images using Google's Gemini AI</b></p>
    <p><b>Active Profile:</b> {CONFIG.get('active_profile','MCQ')}</p>
    <ul>
      <li>MCQ, Cloze Deletion, and Basic card formats</li>
      <li>Prompts stored in config — survive addon updates</li>
      <li>Create fully custom profiles with your own prompt</li>
      <li>Configurable field mapping for any note type</li>
      <li>Intelligent subdeck organisation</li>
      <li>Context-aware processing (previous page memory)</li>
    </ul>
    <p><a href="{NOTE_TYPE_DOWNLOAD_URL}">Note Type Download</a> · 
       <a href="https://ai.google.dev">Google Gemini AI</a></p>
    <p><i>Created for students, by students</i></p>""")


def check_first_run():
    if CONFIG.get("show_welcome", True):
        WelcomeWizard(mw).exec()


def init_addon():
    menu = QMenu("⚡ MCQ Importer", mw)
    mw.form.menubar.insertMenu(mw.form.menuTools.menuAction(), menu)

    imp = QAction("📥 Import Images…", mw)
    imp.triggered.connect(run_importer)
    imp.setShortcut("Ctrl+Shift+G")
    menu.addAction(imp)
    menu.addSeparator()

    stg = QAction("⚙ Settings", mw)
    stg.triggered.connect(open_settings)
    menu.addAction(stg)

    abt = QAction("ℹ About", mw)
    abt.triggered.connect(show_about)
    menu.addAction(abt)

    QTimer.singleShot(1000, check_first_run)

    if CONFIG.get("validate_api_on_startup", False):
        key = CONFIG.get("api_key", "")
        if key:
            def _chk():
                ok, msg = test_api_connection(key, CONFIG.get("model", "gemini-2.5-flash-preview-05-20"))
                if not ok: showWarning(f"Gemini API validation failed:\n\n{msg}\n\nCheck Settings.")
            QTimer.singleShot(2000, _chk)


init_addon()
