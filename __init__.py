# True Anki MCQ Importer - AI Batch Generator (v4.0 - Prompt Profiles Edition)
# Changes from v3.2:
# - Prompt Profiles system: MCQ, Cloze, Basic (each a tuned version of the same high-yield prompt)
# - Per-profile field mapping (handles any note type naming convention)
# - Editable prompt preview in Settings
# - Profile add/delete/reset
# - Parser dispatcher routes output to correct Anki fields based on profile format

import os
import json
import urllib.request
import urllib.error
import base64
import re
import traceback
from typing import Optional, List, Tuple, Dict
import time

from aqt import mw
from aqt.utils import showInfo, showWarning, askUser, tooltip, getText
from aqt.qt import *
from anki.notes import Note

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

ADDON_NAME = "Anki MCQ Importer - AI Batch Generator"
VERSION = "4.0.0"
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

# ============================================================================
# BUILT-IN PROMPT PROFILES
# ============================================================================
# Each profile is a complete, self-contained configuration. The "prompt" key
# is a fully tuned version of the core high-yield prompt for that card format.
# "format" tells the parser how to read the AI's output.
# "field_map" is the logical-slot → actual Anki field name mapping.

MCQ_PROMPT = """***

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

CLOZE_PROMPT = """***

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

BASIC_PROMPT = """***

### ** PROMPT FOR BASIC (FRONT/BACK) CARD CREATION**

**Objective:**
Create a targeted yet comprehensive set of Basic flashcards covering the most high-yield aspects of the provided text. Each card has a Front (the question or cue) and a Back (the complete answer). The goal is maximum coverage with minimum redundancy — every card should test one specific, retrievable fact.

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
- Keep the card set lean. For reciprocal facts, prioritize the version that cues with the broader category and answers with the specific detail (e.g., Front: "Adverse effect unique to Phenformin vs. Metformin:" Back: "Fatal lactic acidosis").
- Ignore exercises and sample problems in the source text.

**2. Front (Question/Cue) Phrasing (CRITICAL):**
- Write the Front as a concise statement-cue or an incomplete sentence — not a full question with "What," "Which," "Where," "How," or "Why."
- Avoid phrases like "According to the text," "from the provided text," etc.
- Avoid ambiguous pronouns such as "this," "that," or "it." Name the subject explicitly.
- Use <b>, <i>, <u> HTML tags to emphasize the key tested concept on the Front.
- The Front must be specific enough that only one correct answer exists — avoid vague cues.
- Mnemonics must NEVER appear on the Front.

**3. Back (Answer) Phrasing:**
- The Back should be the complete, minimal correct answer — not a paragraph.
- For list answers (e.g., drug classes, constituents), use <br> to separate items vertically.
- Use <b> to highlight the most important terms in the answer.
- If the answer is a list, include ALL correct items from the source text.
- Avoid restating the Front verbatim in the Back.

**4. AI Knowledge & Corrections:**
- Stay within the provided text for creating cards, but use broader knowledge to enrich the Extra column.
- Add a `Rationale:` to the Extra column whenever possible for context, mechanism, or clinical significance.
- If you identify a factual error in the source text, create the card using the corrected information and note the correction in the Extra column.

**5. Formatting & Structure:**
- Use pipes `|` as separators.
- Output format per line: Subtopic|Front|Back|Extra
- Skip the header row.
- Use HTML line breaks `<br>` for multi-line content within a column.
- Mnemonics go ONLY in the Extra column — never on the Front or Back.
- Image tags / references (if provided) are to be added at the bottom of the Extra column.

**6. Examples:**

```
Anti-Diabetes|Classes of drugs for <b>diabetes mellitus</b>:|<b>Insulin secretagogues</b><br><b>Biguanides</b><br><b>Thiazolidinediones</b><br><b>Alpha-glucosidase inhibitors</b><br><b>Incretin-based drugs</b><br><b>SGLT2 Inhibitors</b><br><b>Amylin Analogues</b>|Rationale: These are the major pharmacological classes used for Type 2 DM management. Insulin itself is primary therapy for Type 1 DM.<br><br>Mnemonic: <b>I</b>n <b>B</b>right <b>T</b>imes, <b>A</b>ll <b>I</b>ndividuals <b>S</b>hine <b>A</b>gain.
Anti-Diabetes|Mechanism of action of <b>Insulin Secretagogues</b>:|Blockade of <b>ATP-sensitive K+ channels</b> → membrane depolarization → Ca2+ influx → insulin exocytosis|Rationale: This cascade in pancreatic β-cells is the target of sulfonylureas and meglitinides. Depolarization opens voltage-gated Ca2+ channels, and the resulting Ca2+ surge triggers granule release.
Anti-Diabetes|Biguanide withdrawn due to fatal <b>lactic acidosis</b> risk:|<b>Phenformin</b>|Rationale: Phenformin's chemical structure causes greater mitochondrial respiratory chain inhibition than metformin, leading to dangerous lactate accumulation. Withdrawn in the 1970s–80s in most countries.
Tannins|Plant sources rich in <b>tannins</b>:|<b>Psidium guajava</b> (Guava)<br><b>Hamamelis virginiana</b> (Witch Hazel)<br><b>Quercus infectoria</b> (Oak galls)<br><b>Syzygium cumini</b> (Java plum)|Rationale: These plants are exploited for astringent, antidiarrheal, and wound-healing properties. High tannin content gives them commercial and medicinal value.
Sesame oil|Primary antioxidant lignan constituents of <b>Sesamum indicum</b>:|<b>Sesamol</b><br><b>Sesamolin</b>|Rationale: These lignans give sesame oil its exceptional oxidative stability. Both have demonstrated free radical scavenging activity.
Zoonotic Diseases|Causative organisms of <b>Rat-bite fever</b>:|<b>Streptobacillus moniliformis</b> (North America / Haverhill fever)<br><b>Spirillum minus</b> (Asia / Sodoku)|Rationale: Both are transmitted via rat bites or scratches. Geographic distribution guides diagnosis when culture is pending.
```
"""

# Logical field slot names — these are internal identifiers, not Anki field names
# Each profile maps its output columns to these slots
SLOT_QUESTION    = "question"     # MCQ: Question | Basic: Front
SLOT_CHOICES     = "choices"      # MCQ only: the options list
SLOT_ANSWER      = "answer"       # MCQ: Correct Answers | Basic: Back | Cloze: not used (baked into text)
SLOT_TEXT        = "text"         # Cloze: the cloze-formatted sentence
SLOT_EXTRA       = "extra"        # All profiles: rationale / mnemonics
SLOT_SUBTOPIC    = "subtopic"     # All profiles: used for subdeck name (not a field)

DEFAULT_PROFILES = {
    "MCQ": {
        "display_name": "Multiple Choice (MCQ)",
        "format": "mcq",          # determines parser + field mapping UI
        "prompt": MCQ_PROMPT,
        "field_map": {
            # slot → default Anki field name (user can override)
            SLOT_QUESTION: "Question",
            SLOT_CHOICES:  "Multiple Choice",
            SLOT_ANSWER:   "Correct Answers",
            SLOT_EXTRA:    "Extra",
        }
    },
    "Cloze": {
        "display_name": "Cloze Deletion",
        "format": "cloze",
        "prompt": CLOZE_PROMPT,
        "field_map": {
            SLOT_TEXT:  "Text",
            SLOT_EXTRA: "Extra",
        }
    },
    "Basic": {
        "display_name": "Basic (Front / Back)",
        "format": "basic",
        "prompt": BASIC_PROMPT,
        "field_map": {
            SLOT_QUESTION: "Front",
            SLOT_ANSWER:   "Back",
            SLOT_EXTRA:    "Extra",
        }
    },
}

# Slot display info for the field mapping UI
SLOT_META = {
    "mcq": [
        (SLOT_QUESTION, "Question",       "The stem / question text"),
        (SLOT_CHOICES,  "Multiple Choice","All answer options (pipe-delimited <br>)"),
        (SLOT_ANSWER,   "Correct Answers","Correct option(s) (pipe-delimited <br>)"),
        (SLOT_EXTRA,    "Extra / Notes",  "Rationale, mnemonics, image tag"),
    ],
    "cloze": [
        (SLOT_TEXT,  "Text",        "Sentence with {{c1::}} cloze deletions"),
        (SLOT_EXTRA, "Extra / Notes","Rationale, mnemonics, image tag"),
    ],
    "basic": [
        (SLOT_QUESTION, "Front",        "The question / cue side"),
        (SLOT_ANSWER,   "Back",         "The complete answer"),
        (SLOT_EXTRA,    "Extra / Notes","Rationale, mnemonics, image tag"),
    ],
}


def get_default_config():
    return {
        "api_key": "",
        "model": "gemini-2.5-flash-preview-05-20",
        "active_profile": "MCQ",
        "profiles": DEFAULT_PROFILES,
        "show_welcome": True,
        "auto_open_media": True,
        "batch_size": 10,
        "validate_api_on_startup": False,
    }


CONFIG = mw.addonManager.getConfig(__name__)
if CONFIG is None:
    CONFIG = get_default_config()
    mw.addonManager.writeConfig(__name__, CONFIG)

# Ensure profiles key is present (upgrade from v3.x)
if "profiles" not in CONFIG:
    CONFIG["profiles"] = DEFAULT_PROFILES
    CONFIG["active_profile"] = "MCQ"
    mw.addonManager.writeConfig(__name__, CONFIG)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def log_error(context: str, error: Exception):
    error_msg = f"[{ADDON_NAME}] {context}\nError: {str(error)}\n{traceback.format_exc()}"
    print(error_msg)
    return error_msg


def validate_api_key(api_key: str) -> Tuple[bool, str]:
    if not api_key or len(api_key.strip()) == 0:
        return False, "API key cannot be empty"
    if not api_key.startswith("AIzaSy"):
        return False, "Invalid API key format. Gemini API keys start with 'AIzaSy'"
    if len(api_key) < 30:
        return False, "API key appears too short. Please verify your key."
    return True, "API key format looks valid"


def test_api_connection(api_key: str, model: str) -> Tuple[bool, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    test_data = {"contents": [{"parts": [{"text": "Hello"}]}]}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(test_data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            if 'candidates' in result:
                return True, "API connection successful"
            return False, "Unexpected API response format"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='ignore')
        if e.code == 400:
            return False, f"Invalid API key or model name (HTTP 400)\n{error_body}"
        elif e.code == 403:
            return False, "API key authentication failed (HTTP 403). Check your key."
        elif e.code == 429:
            return False, "Rate limit exceeded (HTTP 429). Try again later."
        else:
            return False, f"HTTP Error {e.code}: {error_body}"
    except urllib.error.URLError as e:
        return False, f"Network error: {str(e)}. Check your internet connection."
    except Exception as e:
        return False, f"Connection test failed: {str(e)}"


def list_generate_models(api_key: str) -> Tuple[bool, List[str], str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    models = []
    next_url = url
    try:
        while next_url:
            req = urllib.request.Request(next_url)
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode())
            for model in payload.get("models", []):
                name = model.get("name", "")
                supported = model.get("supportedGenerationMethods", [])
                if "generateContent" not in supported:
                    continue
                clean_name = name.replace("models/", "")
                if clean_name.startswith("gemini"):
                    models.append(clean_name)
            next_page = payload.get("nextPageToken")
            next_url = f"{url}&pageToken={next_page}" if next_page else None
        models = list(dict.fromkeys(models))
        if not models:
            return False, [], "No Gemini models with generateContent support were returned by the API."
        return True, models, f"Found {len(models)} available Gemini model(s)."
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='ignore')
        return False, [], f"Failed to list models (HTTP {e.code}): {error_body}"
    except urllib.error.URLError as e:
        return False, [], f"Network error while listing models: {str(e)}"
    except Exception as e:
        return False, [], f"Failed to list models: {str(e)}"


def choose_model_from_list(api_key: str, preferred_model: Optional[str] = None) -> Tuple[bool, Optional[str], str, List[str]]:
    ok, models, msg = list_generate_models(api_key)
    if not ok:
        return False, None, msg, []
    if preferred_model and preferred_model in models:
        return True, preferred_model, msg, models
    for candidate in ["gemini-2.5-flash-preview-05-20", "gemini-2.5-pro-preview-06-05", "gemini-2.0-flash"]:
        if candidate in models:
            return True, candidate, msg, models
    return True, models[0], msg, models


def validate_image_file(file_path: str) -> Tuple[bool, str]:
    if not os.path.exists(file_path):
        return False, f"File not found: {file_path}"
    if not os.path.isfile(file_path):
        return False, f"Path is not a file: {file_path}"
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            return False, f"File too large ({file_size_mb:.1f}MB). Max: {MAX_FILE_SIZE_MB}MB"
    except Exception as e:
        return False, f"Cannot read file size: {str(e)}"
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in SUPPORTED_IMAGE_FORMATS:
        return False, f"Unsupported format: {ext}. Supported: {', '.join(SUPPORTED_IMAGE_FORMATS)}"
    return True, "File valid"


def sanitize_deck_name(name: str) -> str:
    parts = name.split('::')
    sanitized_parts = []
    for part in parts:
        sanitized = re.sub(r'[\\/*?"<>|]', '', part).strip()
        if sanitized:
            sanitized_parts.append(sanitized)
    result = '::'.join(sanitized_parts)
    return result if result else "Imported"


def get_active_profile() -> Dict:
    profile_key = CONFIG.get("active_profile", "MCQ")
    profiles = CONFIG.get("profiles", DEFAULT_PROFILES)
    return profiles.get(profile_key, DEFAULT_PROFILES["MCQ"])


# ============================================================================
# GEMINI API
# ============================================================================

def encode_image_base64(file_path: str) -> Optional[str]:
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        log_error(f"Image encoding: {file_path}", e)
        return None


def get_gemini_response(api_key: str, model: str, current_image_path: str,
                        prev_image_path: Optional[str] = None,
                        prompt: Optional[str] = None) -> Tuple[bool, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    if prompt is None:
        prompt = get_active_profile().get("prompt", MCQ_PROMPT)

    current_b64 = encode_image_base64(current_image_path)
    if not current_b64:
        return False, f"Failed to encode image: {current_image_path}"

    prev_b64 = encode_image_base64(prev_image_path) if prev_image_path else None

    parts = [{"text": prompt}]

    if prev_b64:
        parts.append({"text": "--- CONTEXT ONLY (Previous Page) ---"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": prev_b64}})

    parts.append({"text": "--- TARGET IMAGE (Generate Cards) ---"})
    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": current_b64}})

    data = {"contents": [{"parts": parts}]}

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode())
            if 'candidates' not in result or not result['candidates']:
                return False, "No response candidates from API"
            candidate = result['candidates'][0]
            if candidate.get('finishReason') == 'SAFETY':
                return False, "Content filtered by safety settings"
            if 'content' not in candidate or 'parts' not in candidate['content']:
                return False, "Invalid response structure from API"
            text = candidate['content']['parts'][0].get('text', '')
            if not text:
                return False, "Empty response from API"
            return True, text
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='ignore')
        if e.code == 400:
            return False, f"Bad request (400): {error_body}"
        elif e.code == 403:
            return False, "API key invalid or unauthorized (403)"
        elif e.code == 429:
            return False, "Rate limit exceeded (429). Please wait and try again."
        elif e.code == 500:
            return False, "Gemini API server error (500). Please try again."
        else:
            return False, f"HTTP Error {e.code}: {error_body}"
    except urllib.error.URLError as e:
        return False, f"Network error: {str(e)}"
    except Exception as e:
        log_error("Gemini API call", e)
        return False, str(e)


# ============================================================================
# CARD PARSERS
# ============================================================================

def _split_pipe_line(line: str, expected_min: int) -> Optional[List[str]]:
    """Split a pipe-delimited line and return parts if count meets minimum."""
    parts = line.split('|')
    if len(parts) < expected_min:
        return None
    return [p.strip() for p in parts]


def parse_mcq_response(response_text: str) -> List[Dict]:
    """Parse MCQ output: Subtopic|Question|Choices|Correct|Extra"""
    cards = []
    for line_num, line in enumerate(response_text.strip().split('\n'), 1):
        line = line.strip()
        if not line or line.startswith('#') or '|' not in line:
            continue
        parts = _split_pipe_line(line, 5)
        if not parts:
            print(f"Warning: Line {line_num} has <5 parts, skipping")
            continue
        subtopic, question, choices, correct, extra = (
            parts[0], parts[1], parts[2], parts[3], parts[4]
        )
        if not question or not choices:
            continue
        cards.append({
            "subtopic": subtopic,
            SLOT_QUESTION: question,
            SLOT_CHOICES:  choices,
            SLOT_ANSWER:   correct,
            SLOT_EXTRA:    extra,
        })
    return cards


def parse_cloze_response(response_text: str) -> List[Dict]:
    """Parse Cloze output: Subtopic|Text|Extra"""
    cards = []
    for line_num, line in enumerate(response_text.strip().split('\n'), 1):
        line = line.strip()
        if not line or line.startswith('#') or '|' not in line:
            continue
        parts = _split_pipe_line(line, 3)
        if not parts:
            print(f"Warning: Line {line_num} has <3 parts, skipping")
            continue
        subtopic = parts[0]
        text     = parts[1]
        extra    = parts[2] if len(parts) > 2 else ""
        if not text or '{{c' not in text:
            print(f"Warning: Line {line_num} has no cloze syntax, skipping")
            continue
        cards.append({
            "subtopic": subtopic,
            SLOT_TEXT:  text,
            SLOT_EXTRA: extra,
        })
    return cards


def parse_basic_response(response_text: str) -> List[Dict]:
    """Parse Basic output: Subtopic|Front|Back|Extra"""
    cards = []
    for line_num, line in enumerate(response_text.strip().split('\n'), 1):
        line = line.strip()
        if not line or line.startswith('#') or '|' not in line:
            continue
        parts = _split_pipe_line(line, 4)
        if not parts:
            print(f"Warning: Line {line_num} has <4 parts, skipping")
            continue
        subtopic = parts[0]
        front    = parts[1]
        back     = parts[2]
        extra    = parts[3] if len(parts) > 3 else ""
        if not front or not back:
            continue
        cards.append({
            "subtopic": subtopic,
            SLOT_QUESTION: front,
            SLOT_ANSWER:   back,
            SLOT_EXTRA:    extra,
        })
    return cards


def parse_response(response_text: str, fmt: str) -> List[Dict]:
    """Dispatcher: route to correct parser based on profile format string."""
    if fmt == "mcq":
        return parse_mcq_response(response_text)
    elif fmt == "cloze":
        return parse_cloze_response(response_text)
    elif fmt == "basic":
        return parse_basic_response(response_text)
    else:
        print(f"Warning: Unknown format '{fmt}', falling back to MCQ parser")
        return parse_mcq_response(response_text)


# ============================================================================
# WELCOME WIZARD
# ============================================================================

class WelcomeWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {ADDON_NAME}!")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)

        layout = QVBoxLayout()
        self.setLayout(layout)

        welcome_text = QLabel(f"""
        <h2>Welcome to {ADDON_NAME} v{VERSION}!</h2>
        <p>This wizard will help you set up the addon in 2 easy steps:</p>
        <ol>
            <li><b>Get your Gemini API Key</b> (free from Google)</li>
            <li><b>Download and install the Note Type</b> (for MCQ cards)</li>
        </ol>
        <p>The entire setup takes less than 2 minutes!</p>
        """)
        welcome_text.setWordWrap(True)
        layout.addWidget(welcome_text)

        layout.addWidget(QLabel("<hr>"))
        layout.addWidget(QLabel("<h3>Step 1: Gemini API Key</h3>"))

        api_instructions = QLabel("""
        <p>1. Visit <a href="https://aistudio.google.com/app/apikey">Google AI Studio</a><br>
        2. Sign in with your Google account<br>
        3. Click "Create API Key"<br>
        4. Copy the key and paste it below</p>
        <p><i>Note: The API key is free and includes generous usage limits.</i></p>
        """)
        api_instructions.setOpenExternalLinks(True)
        api_instructions.setWordWrap(True)
        layout.addWidget(api_instructions)

        self.api_input = QLineEdit()
        self.api_input.setPlaceholderText("Paste your API key here (starts with AIzaSy...)")
        self.api_input.textChanged.connect(self.validate_inputs)
        layout.addWidget(self.api_input)

        self.api_status = QLabel("")
        self.api_status.setWordWrap(True)
        layout.addWidget(self.api_status)

        test_api_btn = QPushButton("Test API Connection")
        test_api_btn.clicked.connect(self.test_api)
        layout.addWidget(test_api_btn)

        layout.addWidget(QLabel("<hr>"))
        layout.addWidget(QLabel("<h3>Step 2: Install Note Type (MCQ only)</h3>"))

        nt_instructions = QLabel(f"""
        <p><b>Only needed if you plan to use MCQ cards.</b> Basic and Cloze cards use Anki's built-in note types.</p>
        <p>1. Click the button below to open the GitHub releases page<br>
        2. Download the latest .apkg file<br>
        3. In Anki, go to: File → Import<br>
        4. Select the downloaded .apkg file<br>
        5. Return here and click "I've Installed It"</p>
        """)
        nt_instructions.setWordWrap(True)
        layout.addWidget(nt_instructions)

        open_github_btn = QPushButton("🌐 Open Note Type Download Page")
        open_github_btn.clicked.connect(self.open_github_releases)
        layout.addWidget(open_github_btn)

        confirm_install_btn = QPushButton("✓ I've Installed the Note Type")
        confirm_install_btn.clicked.connect(self.confirm_note_type_installed)
        layout.addWidget(confirm_install_btn)

        self.nt_status = QLabel("Status: Not installed yet (optional for Basic/Cloze)")
        self.nt_status.setWordWrap(True)
        layout.addWidget(self.nt_status)

        layout.addWidget(QLabel("<hr>"))

        button_layout = QHBoxLayout()
        self.finish_btn = QPushButton("✓ Finish Setup")
        self.finish_btn.clicked.connect(self.finish_setup)
        self.finish_btn.setEnabled(False)
        button_layout.addWidget(self.finish_btn)

        skip_btn = QPushButton("Skip (Configure Later)")
        skip_btn.clicked.connect(self.skip_setup)
        button_layout.addWidget(skip_btn)

        layout.addLayout(button_layout)

        self.note_type_confirmed = False
        self.api_tested = False

    def validate_inputs(self):
        has_api = len(self.api_input.text().strip()) > 0
        self.finish_btn.setEnabled(has_api)

    def test_api(self):
        api_key = self.api_input.text().strip()
        valid, msg = validate_api_key(api_key)
        if not valid:
            self.api_status.setText(f"<span style='color: red;'>❌ {msg}</span>")
            return
        self.api_status.setText("Testing connection...")
        QApplication.processEvents()
        success, selected_model, msg, _ = choose_model_from_list(api_key)
        if not success or not selected_model:
            self.api_status.setText(f"<span style='color: red;'>❌ {msg}</span>")
            return
        success, msg = test_api_connection(api_key, selected_model)
        if success:
            self.api_status.setText(f"<span style='color: green;'>✓ {msg}</span>")
            self.api_tested = True
            self.validate_inputs()
        else:
            self.api_status.setText(f"<span style='color: red;'>❌ {msg}</span>")

    def open_github_releases(self):
        QDesktopServices.openUrl(QUrl(NOTE_TYPE_DOWNLOAD_URL))
        tooltip("Opening download page in your browser...", period=2000)

    def confirm_note_type_installed(self):
        models = mw.col.models.all()
        mcq_models = [m for m in models if "Multiple Choice" in m['name'] or "MCQ" in m['name']]
        if mcq_models:
            self.nt_status.setText(f"<span style='color: green;'>✓ Found note type: {mcq_models[0]['name']}</span>")
            self.note_type_confirmed = True
        else:
            if askUser("No Multiple Choice note type detected.\n\nHave you imported the .apkg file?\n\nMark as completed anyway?"):
                self.nt_status.setText("<span style='color: orange;'>⚠ Marked as installed (no MCQ note type detected)</span>")
                self.note_type_confirmed = True

    def finish_setup(self):
        api_key = self.api_input.text().strip()
        CONFIG["api_key"] = api_key
        CONFIG["show_welcome"] = False
        models = mw.col.models.all()
        for m in models:
            if "Multiple Choice" in m['name'] or "MCQ" in m['name']:
                CONFIG["note_type_id"] = m['id']
                break
        mw.addonManager.writeConfig(__name__, CONFIG)
        self.accept()
        showInfo(f"Setup complete! You can now use {ADDON_NAME}.\n\n"
                 "Access it from: Tools → Anki MCQ Importer → Import Images")

    def skip_setup(self):
        CONFIG["show_welcome"] = False
        mw.addonManager.writeConfig(__name__, CONFIG)
        self.reject()


# ============================================================================
# FIELD MAPPING WIDGET
# ============================================================================

class FieldMappingWidget(QGroupBox):
    """
    Shows logical slot → Anki field dropdowns for a given profile format.
    The user picks which of their note type's actual fields maps to each slot.
    """

    def __init__(self, fmt: str, field_map: Dict[str, str], anki_fields: List[str], parent=None):
        super().__init__("Field Mapping", parent)
        self.fmt = fmt
        self.combos: Dict[str, QComboBox] = {}

        layout = QFormLayout()
        self.setLayout(layout)

        slots = SLOT_META.get(fmt, [])
        if not slots:
            layout.addRow(QLabel("No field mapping needed for this format."))
            return

        for slot_key, slot_label, slot_desc in slots:
            combo = QComboBox()
            combo.addItems(anki_fields)
            # Try to select current mapping or best guess
            current = field_map.get(slot_key, "")
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            elif anki_fields:
                # Fuzzy fallback: find field containing slot_label keyword
                for i, f in enumerate(anki_fields):
                    if slot_label.lower().split('/')[0].strip() in f.lower():
                        combo.setCurrentIndex(i)
                        break
            label_widget = QLabel(f"<b>{slot_label}</b><br><small>{slot_desc}</small>")
            label_widget.setWordWrap(True)
            layout.addRow(label_widget, combo)
            self.combos[slot_key] = combo

    def get_mapping(self) -> Dict[str, str]:
        return {slot: combo.currentText() for slot, combo in self.combos.items()}

    def update_anki_fields(self, anki_fields: List[str]):
        """Refresh combo options when user changes note type."""
        for slot, combo in self.combos.items():
            current = combo.currentText()
            combo.clear()
            combo.addItems(anki_fields)
            idx = combo.findText(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)


# ============================================================================
# SETTINGS DIALOG
# ============================================================================

class GeminiSettings(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{ADDON_NAME} Settings")
        self.setMinimumWidth(750)
        self.setMinimumHeight(700)

        # Working copy of profiles so we can cancel without saving
        import copy
        self._profiles: Dict = copy.deepcopy(CONFIG.get("profiles", DEFAULT_PROFILES))
        self._active_profile_key: str = CONFIG.get("active_profile", "MCQ")
        self._field_mapping_widget: Optional[FieldMappingWidget] = None

        layout = QVBoxLayout()
        self.setLayout(layout)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── Tab 1: API ────────────────────────────────────────────────────
        api_tab = QWidget()
        api_layout = QVBoxLayout()
        api_tab.setLayout(api_layout)
        tabs.addTab(api_tab, "API Settings")

        api_layout.addWidget(QLabel("<h3>Gemini API Configuration</h3>"))
        api_help = QLabel("""
        <p><b>Get your free API key:</b><br>
        Visit <a href="https://aistudio.google.com/app/apikey">Google AI Studio</a>
        and create a new API key.</p>
        """)
        api_help.setOpenExternalLinks(True)
        api_help.setWordWrap(True)
        api_layout.addWidget(api_help)

        api_layout.addWidget(QLabel("<b>API Key:</b>"))
        self.api_input = QLineEdit()
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_input.setText(CONFIG.get("api_key", ""))
        self.api_input.setPlaceholderText("AIzaSy...")
        api_layout.addWidget(self.api_input)

        show_key_btn = QPushButton("👁 Show/Hide Key")
        show_key_btn.clicked.connect(self.toggle_api_visibility)
        api_layout.addWidget(show_key_btn)

        self.api_status_label = QLabel("")
        self.api_status_label.setWordWrap(True)
        api_layout.addWidget(self.api_status_label)

        test_btn = QPushButton("Test API Connection")
        test_btn.clicked.connect(self.test_api_key)
        api_layout.addWidget(test_btn)

        api_layout.addWidget(QLabel("<hr>"))
        api_layout.addWidget(QLabel("<b>Gemini Model:</b>"))
        model_help = QLabel("<p><i>Flash models are faster; Pro models are more capable.</i></p>")
        model_help.setWordWrap(True)
        api_layout.addWidget(model_help)

        self.model_combo = QComboBox()
        self.model_combo.addItems(GEMINI_MODELS)
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText(CONFIG.get("model", "gemini-2.5-flash-preview-05-20"))
        api_layout.addWidget(self.model_combo)

        refresh_models_btn = QPushButton("🔄 Refresh Available Models")
        refresh_models_btn.clicked.connect(self.refresh_models)
        api_layout.addWidget(refresh_models_btn)
        api_layout.addStretch()

        # ── Tab 2: Prompt Profiles ────────────────────────────────────────
        profile_tab = QWidget()
        profile_layout = QVBoxLayout()
        profile_tab.setLayout(profile_layout)
        tabs.addTab(profile_tab, "Prompt Profiles")

        profile_layout.addWidget(QLabel("<h3>Prompt Profiles</h3>"))
        profile_layout.addWidget(QLabel(
            "<p>Each profile is a complete card format with its own tuned prompt. "
            "The <b>active profile</b> is used when you run an import. "
            "You can freely edit the prompt text — use <b>Reset to Default</b> to restore the original.</p>"
        ))

        # Profile selector row
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("<b>Profile:</b>"))
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        selector_row.addWidget(self.profile_combo, 1)

        set_active_btn = QPushButton("⭐ Set as Active")
        set_active_btn.setToolTip("This profile will be used for the next import")
        set_active_btn.clicked.connect(self._set_active_profile)
        selector_row.addWidget(set_active_btn)

        add_profile_btn = QPushButton("➕ Duplicate")
        add_profile_btn.setToolTip("Duplicate current profile to customize")
        add_profile_btn.clicked.connect(self._duplicate_profile)
        selector_row.addWidget(add_profile_btn)

        del_profile_btn = QPushButton("🗑 Delete")
        del_profile_btn.setToolTip("Delete selected profile (cannot delete built-in defaults)")
        del_profile_btn.clicked.connect(self._delete_profile)
        selector_row.addWidget(del_profile_btn)

        profile_layout.addLayout(selector_row)

        # Active profile indicator
        self.active_indicator = QLabel("")
        self.active_indicator.setWordWrap(True)
        profile_layout.addWidget(self.active_indicator)

        # Profile display name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("<b>Display Name:</b>"))
        self.profile_name_edit = QLineEdit()
        self.profile_name_edit.textChanged.connect(self._on_profile_name_changed)
        name_row.addWidget(self.profile_name_edit)
        profile_layout.addLayout(name_row)

        # Format indicator (read-only for built-ins, editable label for custom)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("<b>Card Format:</b>"))
        self.format_label = QLabel("")
        fmt_row.addWidget(self.format_label, 1)
        profile_layout.addLayout(fmt_row)

        profile_layout.addWidget(QLabel("<b>Prompt Text:</b> (Edit freely — this is sent directly to Gemini)"))

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMinimumHeight(280)
        font = QFont("Courier New", 9)
        self.prompt_edit.setFont(font)
        self.prompt_edit.textChanged.connect(self._on_prompt_changed)
        profile_layout.addWidget(self.prompt_edit)

        prompt_btn_row = QHBoxLayout()
        reset_prompt_btn = QPushButton("↩ Reset Prompt to Default")
        reset_prompt_btn.setToolTip("Restore the original built-in prompt for this profile")
        reset_prompt_btn.clicked.connect(self._reset_prompt)
        prompt_btn_row.addWidget(reset_prompt_btn)
        prompt_btn_row.addStretch()
        char_count_label = QLabel("")
        self.char_count_label = char_count_label
        prompt_btn_row.addWidget(char_count_label)
        profile_layout.addLayout(prompt_btn_row)

        # ── Tab 3: Note Type & Field Mapping ─────────────────────────────
        nt_tab = QWidget()
        nt_layout = QVBoxLayout()
        nt_tab.setLayout(nt_layout)
        tabs.addTab(nt_tab, "Note Type & Fields")

        nt_layout.addWidget(QLabel("<h3>Note Type & Field Mapping</h3>"))
        nt_layout.addWidget(QLabel(
            "<p>Select the Anki note type to use for the <b>active profile</b>, "
            "then map each logical slot to the correct field in that note type. "
            "Field names vary between note types — this mapping handles any naming convention.</p>"
        ))

        nt_layout.addWidget(QLabel(f"""
        <p><b>Need the MCQ note type?</b><br>
        Download from <a href="{NOTE_TYPE_DOWNLOAD_URL}">{NOTE_TYPE_DOWNLOAD_URL}</a></p>
        """))

        open_link_btn = QPushButton("🌐 Open Note Type Download Page")
        open_link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(NOTE_TYPE_DOWNLOAD_URL)))
        nt_layout.addWidget(open_link_btn)

        nt_layout.addWidget(QLabel("<hr>"))

        nt_select_row = QHBoxLayout()
        nt_select_row.addWidget(QLabel("<b>Note Type:</b>"))
        self.nt_combo = QComboBox()
        self.nt_combo.currentIndexChanged.connect(self._on_note_type_changed)
        nt_select_row.addWidget(self.nt_combo, 1)

        refresh_nt_btn = QPushButton("🔄 Refresh")
        refresh_nt_btn.clicked.connect(self._refresh_note_types)
        nt_select_row.addWidget(refresh_nt_btn)

        fields_btn = QPushButton("View All Fields")
        fields_btn.clicked.connect(self.show_note_type_fields)
        nt_select_row.addWidget(fields_btn)
        nt_layout.addLayout(nt_select_row)

        # Field mapping widget placeholder — rebuilt when profile/note type changes
        self.field_mapping_container = QVBoxLayout()
        nt_layout.addLayout(self.field_mapping_container)
        nt_layout.addStretch()

        # ── Tab 4: Advanced ───────────────────────────────────────────────
        adv_tab = QWidget()
        adv_layout = QVBoxLayout()
        adv_tab.setLayout(adv_layout)
        tabs.addTab(adv_tab, "Advanced")

        adv_layout.addWidget(QLabel("<h3>Advanced Options</h3>"))
        self.auto_open_cb = QCheckBox("Automatically open media folder after import")
        self.auto_open_cb.setChecked(CONFIG.get("auto_open_media", True))
        adv_layout.addWidget(self.auto_open_cb)

        adv_layout.addWidget(QLabel("<br><b>Batch Processing:</b>"))
        batch_layout = QHBoxLayout()
        batch_layout.addWidget(QLabel("Batch size:"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 50)
        self.batch_spin.setValue(CONFIG.get("batch_size", 10))
        batch_layout.addWidget(self.batch_spin)
        batch_layout.addStretch()
        adv_layout.addLayout(batch_layout)

        adv_layout.addWidget(QLabel("<hr>"))
        self.validate_startup_cb = QCheckBox("Validate API connection on Anki startup (slower startup)")
        self.validate_startup_cb.setChecked(CONFIG.get("validate_api_on_startup", False))
        adv_layout.addWidget(self.validate_startup_cb)

        adv_layout.addWidget(QLabel("<hr>"))
        reset_btn = QPushButton("Reset ALL Profiles to Factory Defaults")
        reset_btn.clicked.connect(self.reset_all_profiles)
        adv_layout.addWidget(reset_btn)
        adv_layout.addStretch()

        # Bottom buttons
        button_layout = QHBoxLayout()
        save_btn = QPushButton("💾 Save Settings")
        save_btn.clicked.connect(self.save_config)
        save_btn.setDefault(True)
        button_layout.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        # Populate note types
        self._refresh_note_types(silent=True)
        # Populate profiles (triggers _on_profile_changed)
        self._refresh_profile_combo()

    # ── Profile combo helpers ─────────────────────────────────────────────

    def _refresh_profile_combo(self):
        """Rebuild profile combo from self._profiles."""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for key, profile in self._profiles.items():
            display = profile.get("display_name", key)
            if key == self._active_profile_key:
                display = f"⭐ {display}"
            self.profile_combo.addItem(display, key)
        # Select active profile
        idx = self.profile_combo.findData(self._active_profile_key)
        if idx < 0:
            idx = 0
        self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._on_profile_changed(self.profile_combo.currentIndex())

    def _current_profile_key(self) -> str:
        return self.profile_combo.currentData() or list(self._profiles.keys())[0]

    def _on_profile_changed(self, _index: int):
        """Load selected profile's data into UI."""
        key = self._current_profile_key()
        profile = self._profiles.get(key, {})

        self.profile_name_edit.blockSignals(True)
        self.profile_name_edit.setText(profile.get("display_name", key))
        self.profile_name_edit.blockSignals(False)

        fmt = profile.get("format", "mcq")
        fmt_labels = {"mcq": "Multiple Choice (MCQ)", "cloze": "Cloze Deletion", "basic": "Basic (Front/Back)"}
        self.format_label.setText(f"<i>{fmt_labels.get(fmt, fmt)}</i>")

        self.prompt_edit.blockSignals(True)
        self.prompt_edit.setPlainText(profile.get("prompt", ""))
        self.prompt_edit.blockSignals(False)
        self._update_char_count()

        is_active = (key == self._active_profile_key)
        self.active_indicator.setText(
            f"<span style='color:green;'>⭐ This is the <b>active profile</b> — used on next import.</span>"
            if is_active else
            "<span style='color:gray;'>Not active. Click ⭐ Set as Active to use this profile on import.</span>"
        )

        # Rebuild field mapping widget for this profile's format
        self._rebuild_field_mapping(profile)

    def _on_profile_name_changed(self, text: str):
        key = self._current_profile_key()
        if key in self._profiles:
            self._profiles[key]["display_name"] = text
            # Refresh combo label
            idx = self.profile_combo.currentIndex()
            display = text
            if key == self._active_profile_key:
                display = f"⭐ {text}"
            self.profile_combo.setItemText(idx, display)

    def _on_prompt_changed(self):
        key = self._current_profile_key()
        if key in self._profiles:
            self._profiles[key]["prompt"] = self.prompt_edit.toPlainText()
        self._update_char_count()

    def _update_char_count(self):
        chars = len(self.prompt_edit.toPlainText())
        self.char_count_label.setText(f"<small>{chars:,} chars</small>")

    def _set_active_profile(self):
        key = self._current_profile_key()
        self._active_profile_key = key
        self._refresh_profile_combo()
        tooltip(f"Active profile set to: {self._profiles[key].get('display_name', key)}", period=2000)

    def _duplicate_profile(self):
        import copy
        key = self._current_profile_key()
        profile = copy.deepcopy(self._profiles[key])
        # Generate unique key
        base_name = profile.get("display_name", key) + " (Copy)"
        new_key = base_name
        counter = 1
        while new_key in self._profiles:
            new_key = f"{base_name} {counter}"
            counter += 1
        profile["display_name"] = base_name
        self._profiles[new_key] = profile
        self._refresh_profile_combo()
        # Select new profile
        idx = self.profile_combo.findData(new_key)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        tooltip(f"Duplicated profile as '{base_name}'", period=2000)

    def _delete_profile(self):
        key = self._current_profile_key()
        if key in DEFAULT_PROFILES:
            showWarning("Cannot delete built-in profiles (MCQ, Cloze, Basic).\n\n"
                        "You can duplicate and customize them instead.")
            return
        if not askUser(f"Delete profile '{self._profiles[key].get('display_name', key)}'?"):
            return
        del self._profiles[key]
        if self._active_profile_key == key:
            self._active_profile_key = "MCQ"
        self._refresh_profile_combo()

    def _reset_prompt(self):
        key = self._current_profile_key()
        default = DEFAULT_PROFILES.get(key)
        if not default:
            showWarning("No built-in default prompt for this profile.\n\n"
                        "Only MCQ, Cloze, and Basic profiles have factory defaults.")
            return
        if not askUser("Reset prompt to the factory default?\n\nYour current edits will be lost."):
            return
        self._profiles[key]["prompt"] = default["prompt"]
        self.prompt_edit.blockSignals(True)
        self.prompt_edit.setPlainText(default["prompt"])
        self.prompt_edit.blockSignals(False)
        self._update_char_count()
        tooltip("Prompt reset to default.", period=2000)

    # ── Note type / field mapping helpers ────────────────────────────────

    def _refresh_note_types(self, silent: bool = False):
        self.nt_combo.blockSignals(True)
        self.nt_combo.clear()
        for m in mw.col.models.all():
            self.nt_combo.addItem(m['name'], m['id'])
        saved_id = CONFIG.get("note_type_id")
        if saved_id:
            idx = self.nt_combo.findData(saved_id)
            if idx >= 0:
                self.nt_combo.setCurrentIndex(idx)
        self.nt_combo.blockSignals(False)
        if not silent:
            self._on_note_type_changed(self.nt_combo.currentIndex())

    def _on_note_type_changed(self, _index: int):
        anki_fields = self._get_current_anki_fields()
        if self._field_mapping_widget:
            self._field_mapping_widget.update_anki_fields(anki_fields)

    def _get_current_anki_fields(self) -> List[str]:
        nt_id = self.nt_combo.currentData()
        if not nt_id:
            return []
        model = mw.col.models.get(nt_id)
        if not model:
            return []
        return [f['name'] for f in model['flds']]

    def _rebuild_field_mapping(self, profile: Dict):
        """Remove old field mapping widget and build a fresh one."""
        # Clear old widget
        if self._field_mapping_widget:
            self.field_mapping_container.removeWidget(self._field_mapping_widget)
            self._field_mapping_widget.deleteLater()
            self._field_mapping_widget = None

        fmt = profile.get("format", "mcq")
        field_map = profile.get("field_map", {})
        anki_fields = self._get_current_anki_fields()

        widget = FieldMappingWidget(fmt, field_map, anki_fields)
        self.field_mapping_container.addWidget(widget)
        self._field_mapping_widget = widget

    def show_note_type_fields(self):
        nt_id = self.nt_combo.currentData()
        if not nt_id:
            showWarning("Please select a note type first")
            return
        model = mw.col.models.get(nt_id)
        if not model:
            showWarning("Note type not found")
            return
        fields = [f['name'] for f in model['flds']]
        field_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(fields)])
        showInfo(f"Fields in '{model['name']}':\n\n{field_list}")

    # ── API helpers ───────────────────────────────────────────────────────

    def toggle_api_visibility(self):
        if self.api_input.echoMode() == QLineEdit.EchoMode.Password:
            self.api_input.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.api_input.setEchoMode(QLineEdit.EchoMode.Password)

    def test_api_key(self):
        api_key = self.api_input.text().strip()
        model = self.model_combo.currentText().strip()
        if not api_key:
            self.api_status_label.setText("<span style='color: red;'>Please enter an API key first</span>")
            return
        valid, msg = validate_api_key(api_key)
        if not valid:
            self.api_status_label.setText(f"<span style='color: red;'>❌ {msg}</span>")
            return
        self.api_status_label.setText("Testing connection...")
        QApplication.processEvents()
        list_ok, selected_model, list_msg, _ = choose_model_from_list(api_key, model)
        if not list_ok or not selected_model:
            self.api_status_label.setText(f"<span style='color: red;'>❌ {list_msg}</span>")
            return
        if model != selected_model:
            self.model_combo.setCurrentText(selected_model)
            model = selected_model
        success, msg = test_api_connection(api_key, model)
        if success:
            self.api_status_label.setText(f"<span style='color: green;'>✓ {msg}</span>")
            tooltip(f"API connection successful! {list_msg}", period=3000)
        else:
            self.api_status_label.setText(f"<span style='color: red;'>❌ {msg}</span>")

    def refresh_models(self):
        api_key = self.api_input.text().strip()
        if not api_key:
            self.api_status_label.setText("<span style='color: red;'>Enter API key first to refresh models.</span>")
            return
        self.api_status_label.setText("Refreshing model list...")
        QApplication.processEvents()
        ok, models, msg = list_generate_models(api_key)
        if not ok:
            self.api_status_label.setText(f"<span style='color: red;'>❌ {msg}</span>")
            return
        current = self.model_combo.currentText().strip()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setEditable(True)
        if current in models:
            self.model_combo.setCurrentText(current)
        else:
            self.model_combo.setCurrentIndex(0)
        self.api_status_label.setText(f"<span style='color: green;'>✓ {msg}</span>")

    def reset_all_profiles(self):
        if not askUser("Reset ALL profiles to factory defaults?\n\n"
                       "Any custom profiles will be deleted and edited prompts will be restored.\n\n"
                       "Your API key and note type selection will be preserved."):
            return
        import copy
        self._profiles = copy.deepcopy(DEFAULT_PROFILES)
        self._active_profile_key = "MCQ"
        self._refresh_profile_combo()
        tooltip("All profiles reset to factory defaults.", period=2000)

    # ── Save ──────────────────────────────────────────────────────────────

    def save_config(self):
        api_key = self.api_input.text().strip()
        if api_key:
            valid, msg = validate_api_key(api_key)
            if not valid:
                showWarning(f"Invalid API key:\n\n{msg}")
                return

        nt_id = self.nt_combo.currentData()
        if not nt_id:
            if not askUser("No note type selected.\n\nYou won't be able to import until you select one.\n\nContinue anyway?"):
                return

        # Save field mapping back into the currently selected profile
        key = self._current_profile_key()
        if self._field_mapping_widget and key in self._profiles:
            self._profiles[key]["field_map"] = self._field_mapping_widget.get_mapping()

        CONFIG["api_key"] = api_key
        CONFIG["model"] = self.model_combo.currentText().strip()
        CONFIG["note_type_id"] = nt_id
        CONFIG["active_profile"] = self._active_profile_key
        CONFIG["profiles"] = self._profiles
        CONFIG["auto_open_media"] = self.auto_open_cb.isChecked()
        CONFIG["batch_size"] = self.batch_spin.value()
        CONFIG["validate_api_on_startup"] = self.validate_startup_cb.isChecked()

        mw.addonManager.writeConfig(__name__, CONFIG)
        self.accept()
        tooltip("Settings saved successfully!", period=2000)


# ============================================================================
# PROGRESS DIALOG
# ============================================================================

class ImportProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Progress")
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowCloseButtonHint)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.status_label = QLabel("Initializing...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        layout.addWidget(self.details_text)

        self.cancel_btn = QPushButton("Cancel Import")
        self.cancel_btn.clicked.connect(self.cancel_import)
        layout.addWidget(self.cancel_btn)

        self.cancelled = False
        self.import_complete = False

    def update_progress(self, current: int, total: int, status: str):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"{status} ({current}/{total})")
        QApplication.processEvents()

    def add_detail(self, message: str):
        self.details_text.append(message)
        QApplication.processEvents()

    def is_cancelled(self) -> bool:
        return self.cancelled

    def mark_complete(self):
        self.import_complete = True
        self.cancel_btn.setText("Close")
        self.status_label.setText("Import Complete!")

    def cancel_import(self):
        if self.import_complete:
            self.accept()
        else:
            if askUser("Cancel import?\n\nAlready imported cards will be kept."):
                self.cancelled = True
                self.cancel_btn.setEnabled(False)
                self.status_label.setText("Cancelling...")

    def closeEvent(self, event):
        if self.import_complete:
            event.accept()
        else:
            if askUser("Cancel import?\n\nAlready imported cards will be kept."):
                self.cancelled = True
                self.cancel_btn.setEnabled(False)
                self.status_label.setText("Cancelling...")
                event.accept()
            else:
                event.ignore()


# ============================================================================
# MAIN IMPORT WORKFLOW
# ============================================================================

def run_importer():
    """Main import workflow — profile-aware."""

    # 1. Validate configuration
    api_key = CONFIG.get("api_key", "").strip()
    model_name = CONFIG.get("model", "gemini-2.5-flash-preview-05-20").strip()

    if not api_key:
        showWarning("API Key not configured.\n\nPlease set your Gemini API key in Settings.")
        open_settings()
        return

    valid, msg = validate_api_key(api_key)
    if not valid:
        showWarning(f"Invalid API key:\n\n{msg}\n\nPlease check your settings.")
        open_settings()
        return

    model_ok, resolved_model, model_msg, _ = choose_model_from_list(api_key, model_name)
    if not model_ok or not resolved_model:
        showWarning(f"Could not resolve a supported Gemini model:\n\n{model_msg}\n\nPlease check API key/project access in Settings.")
        return
    model_name = resolved_model

    # 2. Load active profile
    profile_key = CONFIG.get("active_profile", "MCQ")
    profiles = CONFIG.get("profiles", DEFAULT_PROFILES)
    profile = profiles.get(profile_key, DEFAULT_PROFILES["MCQ"])
    profile_fmt = profile.get("format", "mcq")
    profile_prompt = profile.get("prompt", MCQ_PROMPT)
    profile_field_map = profile.get("field_map", {})
    profile_display = profile.get("display_name", profile_key)

    # 3. Validate note type
    nt_id = CONFIG.get("note_type_id")
    if not nt_id:
        showWarning("Note Type not selected.\n\nPlease select a note type in Settings → Note Type & Fields.")
        open_settings()
        return

    anki_model = mw.col.models.get(nt_id)
    if not anki_model:
        showWarning("Selected Note Type not found.\n\nIt may have been deleted. Please select another.")
        open_settings()
        return

    if len(anki_model['flds']) < 2:
        showWarning(f"Note Type '{anki_model['name']}' has too few fields.")
        return

    mw.col.models.set_current(anki_model)

    # 4. Get deck name from user
    root_deck, ok = getText(
        "Enter Root Deck Name:\n\n"
        f"Profile: {profile_display}\n\n"
        "Cards will be organized as:\n"
        "Root Deck::Subtopic Name\n\n"
        "Example: 'Medical::Pharmacology'",
        mw,
        title="Import to Deck"
    )
    if not ok or not root_deck:
        return
    root_deck = sanitize_deck_name(root_deck)

    # 5. Select image files
    file_paths, _ = QFileDialog.getOpenFileNames(
        mw,
        "Select Images to Import",
        "",
        "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;All Files (*)"
    )
    if not file_paths:
        return

    # 6. Validate files
    valid_files = []
    invalid_files = []
    for file_path in file_paths:
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_IMAGE_FORMATS:
            invalid_files.append((filename, f"Unsupported format: {ext}"))
            continue
        is_valid, msg = validate_image_file(file_path)
        if is_valid:
            valid_files.append(file_path)
        else:
            invalid_files.append((filename, msg))

    if not valid_files:
        if invalid_files:
            invalid_list = "\n".join([f"• {name}: {msg}" for name, msg in invalid_files[:5]])
            if len(invalid_files) > 5:
                invalid_list += f"\n... and {len(invalid_files) - 5} more"
            showWarning(f"No valid images found.\n\nIssues:\n{invalid_list}")
        else:
            showWarning("No image files selected.")
        return

    # Sort naturally
    def natural_sort_key(text):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]
    valid_files.sort(key=lambda p: natural_sort_key(os.path.basename(p)))

    # 7. Confirm
    confirm_msg = (
        f"Ready to import:\n\n"
        f"• Profile: {profile_display}\n"
        f"• Images: {len(valid_files)} files\n"
        f"• Root Deck: {root_deck}\n"
        f"• Note Type: {anki_model['name']}\n"
        f"• Model: {model_name}\n"
    )
    if invalid_files:
        confirm_msg += f"\n⚠ Skipping {len(invalid_files)} invalid files"
    confirm_msg += "\n\nProceed with import?"
    if not askUser(confirm_msg):
        return

    # 8. Resolve Anki field names from field map
    anki_field_names = [f['name'] for f in anki_model['flds']]

    def resolve_field(slot_key: str, fallback_idx: int = 0) -> Optional[str]:
        """Get the mapped Anki field name for a logical slot."""
        mapped = profile_field_map.get(slot_key)
        if mapped and mapped in anki_field_names:
            return mapped
        # Fuzzy fallback
        if fallback_idx < len(anki_field_names):
            return anki_field_names[fallback_idx]
        return None

    if profile_fmt == "mcq":
        f_question = resolve_field(SLOT_QUESTION, 0)
        f_choices  = resolve_field(SLOT_CHOICES, 1)
        f_answer   = resolve_field(SLOT_ANSWER, 2)
        f_extra    = resolve_field(SLOT_EXTRA, 3)
    elif profile_fmt == "cloze":
        f_text  = resolve_field(SLOT_TEXT, 0)
        f_extra = resolve_field(SLOT_EXTRA, 1)
    elif profile_fmt == "basic":
        f_question = resolve_field(SLOT_QUESTION, 0)
        f_answer   = resolve_field(SLOT_ANSWER, 1)
        f_extra    = resolve_field(SLOT_EXTRA, 2)

    # 9. Process
    progress_dlg = ImportProgressDialog(mw)
    progress_dlg.show()

    if profile_fmt == "mcq":
        progress_dlg.add_detail(
            f"Field Mapping (MCQ):\n"
            f"  Question → {f_question}\n"
            f"  Choices  → {f_choices}\n"
            f"  Answer   → {f_answer}\n"
            f"  Extra    → {f_extra or 'N/A'}"
        )
    elif profile_fmt == "cloze":
        progress_dlg.add_detail(
            f"Field Mapping (Cloze):\n"
            f"  Text  → {f_text}\n"
            f"  Extra → {f_extra or 'N/A'}"
        )
    elif profile_fmt == "basic":
        progress_dlg.add_detail(
            f"Field Mapping (Basic):\n"
            f"  Front → {f_question}\n"
            f"  Back  → {f_answer}\n"
            f"  Extra → {f_extra or 'N/A'}"
        )

    cards_created = 0
    files_processed = 0
    files_failed = 0
    prev_file_path = None
    error_log = []

    try:
        for index, file_path in enumerate(valid_files):
            if progress_dlg.is_cancelled():
                break

            filename = os.path.basename(file_path)
            progress_dlg.update_progress(index + 1, len(valid_files), f"Processing: {filename}")

            # Add image to Anki media
            try:
                anki_filename = mw.col.media.add_file(file_path)
            except Exception:
                error_msg = f"Failed to add media: {filename}"
                progress_dlg.add_detail(f"❌ {error_msg}")
                error_log.append((filename, error_msg))
                files_failed += 1
                continue

            # Call Gemini
            progress_dlg.add_detail("🤖 Calling Gemini API...")
            success, response = get_gemini_response(
                api_key, model_name, file_path, prev_file_path, prompt=profile_prompt
            )

            if not success:
                error_msg = f"API Error: {response}"
                progress_dlg.add_detail(f"❌ {error_msg}")
                error_log.append((filename, error_msg))
                files_failed += 1
                if "403" in response or "invalid" in response.lower():
                    showWarning(f"Critical API Error:\n\n{response}\n\nStopping import.")
                    break
                continue

            # Parse
            cards = parse_response(response, profile_fmt)

            if not cards:
                error_msg = "No valid cards found in response"
                progress_dlg.add_detail(f"⚠ {error_msg}")
                error_log.append((filename, error_msg))
                files_failed += 1
                continue

            # Create notes
            file_card_count = 0
            for card_data in cards:
                try:
                    subtopic = card_data.get("subtopic", "") or "General"
                    clean_subtopic = sanitize_deck_name(subtopic)
                    target_deck = f"{root_deck}::{clean_subtopic}"
                    deck_id = mw.col.decks.id(target_deck)

                    note = Note(mw.col, anki_model)
                    note.note_type()['did'] = deck_id

                    img_tag = f"<br><br><img src='{anki_filename}'>"

                    if profile_fmt == "mcq":
                        if f_question: note[f_question] = card_data.get(SLOT_QUESTION, "")
                        if f_choices:  note[f_choices]  = card_data.get(SLOT_CHOICES, "")
                        if f_answer:   note[f_answer]   = card_data.get(SLOT_ANSWER, "")
                        if f_extra:    note[f_extra]    = card_data.get(SLOT_EXTRA, "") + img_tag

                    elif profile_fmt == "cloze":
                        if f_text:  note[f_text]  = card_data.get(SLOT_TEXT, "")
                        if f_extra: note[f_extra] = card_data.get(SLOT_EXTRA, "") + img_tag

                    elif profile_fmt == "basic":
                        if f_question: note[f_question] = card_data.get(SLOT_QUESTION, "")
                        if f_answer:   note[f_answer]   = card_data.get(SLOT_ANSWER, "")
                        if f_extra:    note[f_extra]    = card_data.get(SLOT_EXTRA, "") + img_tag

                    mw.col.add_note(note, deck_id)
                    file_card_count += 1
                    cards_created += 1

                except Exception as e:
                    error_msg = f"Card creation error: {str(e)}"
                    progress_dlg.add_detail(f"⚠ {error_msg}")
                    error_log.append((filename, error_msg))

            if file_card_count > 0:
                progress_dlg.add_detail(f"✓ Created {file_card_count} cards from {filename}")
                files_processed += 1

            prev_file_path = file_path

    except Exception as e:
        log_error("Import workflow", e)
        showWarning(f"Critical error during import:\n\n{str(e)}\n\nCheck console for details.")

    finally:
        progress_dlg.mark_complete()
        mw.reset()

    # 10. Results
    result_msg = (
        f"Import Complete!\n\n"
        f"✓ Profile: {profile_display}\n"
        f"✓ Files processed: {files_processed}/{len(valid_files)}\n"
        f"✓ Cards created: {cards_created}\n"
    )
    if files_failed > 0:
        result_msg += f"\n⚠ Files with errors: {files_failed}\n"

    progress_dlg.add_detail(f"\n{result_msg}")

    if error_log and askUser(f"{result_msg}\n\nView error details?"):
        error_details = "\n".join([f"{fname}: {msg}" for fname, msg in error_log[:20]])
        if len(error_log) > 20:
            error_details += f"\n\n... and {len(error_log) - 20} more errors"
        showInfo(f"Error Details:\n\n{error_details}")

    if CONFIG.get("auto_open_media", True) and cards_created > 0:
        if askUser("Open media collection folder?"):
            try:
                media_folder = mw.col.media.dir()
                QDesktopServices.openUrl(QUrl.fromLocalFile(media_folder))
            except Exception as e:
                log_error("Open media folder", e)


# ============================================================================
# MENU ACTIONS
# ============================================================================

def open_settings():
    dlg = GeminiSettings(mw)
    dlg.exec()


def show_about():
    active_profile = CONFIG.get("active_profile", "MCQ")
    about_text = f"""
    <h2>{ADDON_NAME} v{VERSION}</h2>
    <p><b>Batch import flashcards from images using Google's Gemini AI</b></p>
    <p><b>Active Profile:</b> {active_profile}</p>

    <p><b>Features:</b></p>
    <ul>
        <li>Three card formats: MCQ, Cloze Deletion, Basic</li>
        <li>Fully editable prompts per profile</li>
        <li>Configurable field mapping for any note type</li>
        <li>Intelligent subdeck organization</li>
        <li>Context-aware processing (previous page memory)</li>
        <li>Latest Gemini model support</li>
    </ul>

    <p><b>Support / Note Type:</b><br>
    <a href="{NOTE_TYPE_DOWNLOAD_URL}">{NOTE_TYPE_DOWNLOAD_URL}</a></p>

    <p><b>API Provider:</b><br>
    Google Gemini AI (<a href="https://ai.google.dev">ai.google.dev</a>)</p>

    <p><i>Created for students, by students</i></p>
    """
    showInfo(about_text)


def check_first_run():
    if CONFIG.get("show_welcome", True):
        dlg = WelcomeWizard(mw)
        dlg.exec()


# ============================================================================
# INITIALIZATION
# ============================================================================

def init_addon():
    menu = QMenu("⚡ MCQ Importer", mw)
    mw.form.menubar.insertMenu(mw.form.menuTools.menuAction(), menu)

    action_import = QAction("📥 Import Images...", mw)
    action_import.triggered.connect(run_importer)
    action_import.setShortcut("Ctrl+Shift+G")
    menu.addAction(action_import)

    menu.addSeparator()

    action_settings = QAction("⚙ Settings", mw)
    action_settings.triggered.connect(open_settings)
    menu.addAction(action_settings)

    action_about = QAction("ℹ About", mw)
    action_about.triggered.connect(show_about)
    menu.addAction(action_about)

    QTimer.singleShot(1000, check_first_run)

    if CONFIG.get("validate_api_on_startup", False):
        api_key = CONFIG.get("api_key", "")
        if api_key:
            def validate():
                success, msg = test_api_connection(api_key, CONFIG.get("model", "gemini-2.5-flash-preview-05-20"))
                if not success:
                    showWarning(f"Gemini API validation failed:\n\n{msg}\n\n"
                                "Please check your settings.")
            QTimer.singleShot(2000, validate)


init_addon()
