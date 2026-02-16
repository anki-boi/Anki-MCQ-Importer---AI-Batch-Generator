# True Anki MCQ Importer - AI Batch Generator (v3.2 - Fixed Edition)
# Fixes: 
# - API key validation now properly saves and doesn't re-prompt
# - Progress dialog can be closed with X button
# - Manual note type installation (provides download link only)
# - Updated to Gemini 3 models

import os
import json
import urllib.request
import urllib.error
import base64
import re
import traceback
from typing import Optional, List, Tuple
import time

from aqt import mw
from aqt.utils import showInfo, showWarning, askUser, tooltip, getText
from aqt.qt import *
from anki.notes import Note

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

ADDON_NAME = "Anki MCQ Importer - AI Batch Generator"
VERSION = "3.2.0"
DEFAULT_GITHUB_REPO = "anki-boi/True-Anki-MCQ-Note-Template"
NOTE_TYPE_DOWNLOAD_URL = "https://github.com/anki-boi/True-Anki-MCQ-Note-Template/releases/latest"
SUPPORTED_IMAGE_FORMATS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
MAX_FILE_SIZE_MB = 20  # Maximum image file size in MB
GEMINI_MODELS = [
    "gemini-3-pro-preview",
    "gemini-3-flash-preview"
]


# Load or create default configuration
def get_default_config():
    return {
        "api_key": "",
        "model": "gemini-3-flash-preview",
        "note_type_id": None,
        "show_welcome": True,
        "auto_open_media": True,
        "batch_size": 10,
        "validate_api_on_startup": False
    }


CONFIG = mw.addonManager.getConfig(__name__)
if CONFIG is None:
    CONFIG = get_default_config()
    mw.addonManager.writeConfig(__name__, CONFIG)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def log_error(context: str, error: Exception):
    """Centralized error logging"""
    error_msg = f"[{ADDON_NAME}] {context}\nError: {str(error)}\n{traceback.format_exc()}"
    print(error_msg)
    return error_msg


def validate_api_key(api_key: str) -> Tuple[bool, str]:
    """Validate API key format and basic connectivity"""
    if not api_key or len(api_key.strip()) == 0:
        return False, "API key cannot be empty"

    if not api_key.startswith("AIzaSy"):
        return False, "Invalid API key format. Gemini API keys start with 'AIzaSy'"

    if len(api_key) < 30:
        return False, "API key appears too short. Please verify your key."

    return True, "API key format looks valid"


def test_api_connection(api_key: str, model: str) -> Tuple[bool, str]:
    """Test actual API connectivity with a minimal request"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    test_data = {
        "contents": [{
            "parts": [{"text": "Hello"}]
        }]
    }

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
            else:
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
    """List available Gemini models that support generateContent."""
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
            if next_page:
                next_url = f"{url}&pageToken={next_page}"
            else:
                next_url = None

        # Remove duplicates while preserving order
        models = list(dict.fromkeys(models))

        if not models:
            return False, [], "No Gemini models with generateContent support were returned by the API."

        return True, models, f"Found {len(models)} available Gemini model(s)."

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='ignore')
        if e.code == 403:
            return False, [], "API key authentication failed (HTTP 403). Check your key permissions."
        return False, [], f"Failed to list models (HTTP {e.code}): {error_body}"
    except urllib.error.URLError as e:
        return False, [], f"Network error while listing models: {str(e)}"
    except Exception as e:
        return False, [], f"Failed to list models: {str(e)}"


def choose_model_from_list(api_key: str, preferred_model: Optional[str] = None) -> Tuple[bool, Optional[str], str, List[str]]:
    """Resolve a model dynamically from the API model list."""
    ok, models, msg = list_generate_models(api_key)
    if not ok:
        return False, None, msg, []

    if preferred_model and preferred_model in models:
        return True, preferred_model, msg, models

    # Prefer Gemini 3 models first
    for candidate in ["gemini-3-flash-preview", "gemini-3-pro-preview"]:
        if candidate in models:
            return True, candidate, msg, models

    # Fallback to any available model
    return True, models[0], msg, models


def validate_image_file(file_path: str) -> Tuple[bool, str]:
    """Validate image file exists, is readable, and within size limits"""
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
    """Remove invalid characters from deck names"""
    # Remove invalid filesystem characters and Anki-specific reserved chars
    invalid_chars = r'[\\/:*?"<>|]'
    sanitized = re.sub(invalid_chars, '', name)
    sanitized = sanitized.strip()

    # Ensure not empty
    if not sanitized:
        sanitized = "Imported"

    return sanitized

# ============================================================================
# WELCOME WIZARD
# ============================================================================


class WelcomeWizard(QDialog):
    """First-run setup wizard for new users"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {ADDON_NAME}!")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)

        layout = QVBoxLayout()
        self.setLayout(layout)

        # Welcome message
        welcome_text = QLabel(f"""
        <h2>Welcome to {ADDON_NAME} v{VERSION}!</h2>
        <p>This wizard will help you set up the addon in 2 easy steps:</p>
        <ol>
            <li><b>Get your Gemini API Key</b> (free from Google)</li>
            <li><b>Download and install the Note Type</b> (manual installation)</li>
        </ol>
        <p>The entire setup takes less than 2 minutes!</p>
        """)
        welcome_text.setWordWrap(True)
        layout.addWidget(welcome_text)

        # Step 1: API Key
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

        # Step 2: Note Type (Manual Download)
        layout.addWidget(QLabel("<hr>"))
        layout.addWidget(QLabel("<h3>Step 2: Install Note Type</h3>"))

        nt_instructions = QLabel(f"""
        <p><b>Manual Installation Required:</b></p>
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

        self.nt_status = QLabel("Status: Not installed yet")
        self.nt_status.setWordWrap(True)
        layout.addWidget(self.nt_status)

        # Completion buttons
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
        """Enable finish button when requirements met"""
        has_api = len(self.api_input.text().strip()) > 0
        self.finish_btn.setEnabled(has_api and self.note_type_confirmed)

    def test_api(self):
        """Test API key validity"""
        api_key = self.api_input.text().strip()

        # Format validation
        valid, msg = validate_api_key(api_key)
        if not valid:
            self.api_status.setText(f"<span style='color: red;'>❌ {msg}</span>")
            return

        # Connection test
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
        """Open GitHub releases page in browser"""
        QDesktopServices.openUrl(QUrl(NOTE_TYPE_DOWNLOAD_URL))
        tooltip("Opening download page in your browser...", period=2000)

    def confirm_note_type_installed(self):
        """User confirms they've installed the note type"""
        # Check if any MCQ-related note type exists
        models = mw.col.models.all()
        mcq_models = [m for m in models if "Multiple Choice" in m['name'] or "MCQ" in m['name']]

        if mcq_models:
            self.nt_status.setText(f"<span style='color: green;'>✓ Found note type: {mcq_models[0]['name']}</span>")
            self.note_type_confirmed = True
            self.validate_inputs()
        else:
            if askUser("No Multiple Choice note type detected.\n\nHave you imported the .apkg file in Anki?\n\nMark as completed anyway?"):
                self.nt_status.setText("<span style='color: orange;'>⚠ Marked as installed (no MCQ note type detected)</span>")
                self.note_type_confirmed = True
                self.validate_inputs()

    def finish_setup(self):
        """Save configuration and close"""
        api_key = self.api_input.text().strip()
        
        # Save API key
        CONFIG["api_key"] = api_key
        CONFIG["show_welcome"] = False

        # Try to auto-select the downloaded note type
        models = mw.col.models.all()
        for m in models:
            if "Multiple Choice" in m['name'] or "MCQ" in m['name']:
                CONFIG["note_type_id"] = m['id']
                break

        # Force save config
        mw.addonManager.writeConfig(__name__, CONFIG)
        
        self.accept()

        showInfo(f"Setup complete! You can now use {ADDON_NAME}.\n\n"
                 "Access it from: Tools → Anki MCQ Importer → Import Folder")

    def skip_setup(self):
        """Skip wizard and configure later"""
        CONFIG["show_welcome"] = False
        mw.addonManager.writeConfig(__name__, CONFIG)
        self.reject()


# ============================================================================
# SETTINGS DIALOG
# ============================================================================

class GeminiSettings(QDialog):
    """Enhanced settings dialog with validation and help"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{ADDON_NAME} Settings")
        self.setMinimumWidth(650)

        layout = QVBoxLayout()
        self.setLayout(layout)

        # Create tabs for organization
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Tab 1: API Configuration
        api_tab = QWidget()
        api_layout = QVBoxLayout()
        api_tab.setLayout(api_layout)
        tabs.addTab(api_tab, "API Settings")

        # API Key section
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

        # Model selection
        api_layout.addWidget(QLabel("<b>Gemini Model:</b>"))
        model_help = QLabel("""
        <p><i>Flash models are faster and cheaper, Pro models are more capable.</i></p>
        """)
        model_help.setWordWrap(True)
        api_layout.addWidget(model_help)

        self.model_combo = QComboBox()
        self.model_combo.addItems(GEMINI_MODELS)
        self.model_combo.setEditable(True)
        current_model = CONFIG.get("model", "gemini-3-flash-preview")
        self.model_combo.setCurrentText(current_model)
        api_layout.addWidget(self.model_combo)

        refresh_models_btn = QPushButton("🔄 Refresh Available Models")
        refresh_models_btn.clicked.connect(self.refresh_models)
        api_layout.addWidget(refresh_models_btn)

        api_layout.addStretch()

        # Tab 2: Note Type Management
        nt_tab = QWidget()
        nt_layout = QVBoxLayout()
        nt_tab.setLayout(nt_layout)
        tabs.addTab(nt_tab, "Note Type")

        nt_layout.addWidget(QLabel("<h3>Note Type Management</h3>"))

        nt_layout.addWidget(QLabel(f"""
        <p><b>Download the Multiple Choice note type:</b></p>
        <p>1. Click the button below to open GitHub releases<br>
        2. Download the latest .apkg file<br>
        3. Import it in Anki: File → Import<br>
        4. Return here to select it</p>
        """))

        open_link_btn = QPushButton("🌐 Open Note Type Download Page")
        open_link_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(NOTE_TYPE_DOWNLOAD_URL)))
        nt_layout.addWidget(open_link_btn)

        nt_layout.addWidget(QLabel("<hr>"))

        select_section = QGroupBox("Select Note Type")
        select_layout = QVBoxLayout()
        select_section.setLayout(select_layout)
        nt_layout.addWidget(select_section)

        select_layout.addWidget(QLabel("""
        <p><b>Choose which note type to use for importing cards:</b></p>
        """))

        self.nt_combo = QComboBox()
        self.populate_note_types()
        select_layout.addWidget(self.nt_combo)

        refresh_nt_btn = QPushButton("🔄 Refresh Note Type List")
        refresh_nt_btn.clicked.connect(self.populate_note_types)
        select_layout.addWidget(refresh_nt_btn)

        fields_btn = QPushButton("View Fields")
        fields_btn.clicked.connect(self.show_note_type_fields)
        select_layout.addWidget(fields_btn)

        nt_layout.addStretch()

        # Tab 3: Advanced Options
        adv_tab = QWidget()
        adv_layout = QVBoxLayout()
        adv_tab.setLayout(adv_layout)
        tabs.addTab(adv_tab, "Advanced")

        adv_layout.addWidget(QLabel("<h3>Advanced Options</h3>"))

        self.auto_open_cb = QCheckBox("Automatically open media folder after import")
        self.auto_open_cb.setChecked(CONFIG.get("auto_open_media", True))
        adv_layout.addWidget(self.auto_open_cb)

        adv_layout.addWidget(QLabel("<br><b>Batch Processing:</b>"))
        batch_help = QLabel("<i>Number of images to process before updating progress (higher = faster but less responsive)</i>")
        batch_help.setWordWrap(True)
        adv_layout.addWidget(batch_help)

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

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
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

    def toggle_api_visibility(self):
        """Toggle API key visibility"""
        if self.api_input.echoMode() == QLineEdit.EchoMode.Password:
            self.api_input.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.api_input.setEchoMode(QLineEdit.EchoMode.Password)

    def test_api_key(self):
        """Test the API key"""
        api_key = self.api_input.text().strip()
        model = self.model_combo.currentText().strip()

        if not api_key:
            self.api_status_label.setText("<span style='color: red;'>Please enter an API key first</span>")
            return

        # Format validation
        valid, msg = validate_api_key(api_key)
        if not valid:
            self.api_status_label.setText(f"<span style='color: red;'>❌ {msg}</span>")
            return

        # Connection test
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
        """Refresh model list dynamically from Gemini ListModels endpoint."""
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

    def populate_note_types(self):
        """Populate note type dropdown"""
        self.nt_combo.clear()
        models = mw.col.models.all()

        for m in models:
            self.nt_combo.addItem(m['name'], m['id'])

        # Set current selection
        saved_id = CONFIG.get("note_type_id")
        if saved_id:
            index = self.nt_combo.findData(saved_id)
            if index >= 0:
                self.nt_combo.setCurrentIndex(index)

    def show_note_type_fields(self):
        """Show fields of selected note type"""
        nt_id = self.nt_combo.currentData()
        if not nt_id:
            showWarning("Please select a note type first")
            return

        model = mw.col.models.get(nt_id)
        if not model:
            showWarning("Note type not found")
            return

        fields = [f['name'] for f in model['flds']]
        field_list = "\n".join([f"{i + 1}. {name}" for i, name in enumerate(fields)])

        showInfo(f"Fields in '{model['name']}':\n\n{field_list}")

    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        if not askUser("Reset all settings to defaults?\n\n"
                       "This will NOT delete your API key or note types."):
            return

        # Keep API key and note type
        api_key = CONFIG.get("api_key", "")
        note_type_id = CONFIG.get("note_type_id")

        # Reset to defaults
        defaults = get_default_config()
        defaults["api_key"] = api_key
        defaults["note_type_id"] = note_type_id

        CONFIG.clear()
        CONFIG.update(defaults)

        # Update UI
        self.model_combo.setCurrentText(defaults["model"])
        self.auto_open_cb.setChecked(defaults["auto_open_media"])
        self.batch_spin.setValue(defaults["batch_size"])
        self.validate_startup_cb.setChecked(defaults["validate_api_on_startup"])

        tooltip("Settings reset to defaults", period=2000)

    def save_config(self):
        """Validate and save configuration"""
        api_key = self.api_input.text().strip()

        # Validate API key if provided
        if api_key:
            valid, msg = validate_api_key(api_key)
            if not valid:
                showWarning(f"Invalid API key:\n\n{msg}")
                return

        # Validate note type selection
        nt_id = self.nt_combo.currentData()
        if not nt_id:
            if not askUser("No note type selected.\n\nYou won't be able to import until you select one.\n\nContinue anyway?"):
                return

        # Save configuration
        CONFIG["api_key"] = api_key
        CONFIG["model"] = self.model_combo.currentText().strip()
        CONFIG["note_type_id"] = nt_id
        CONFIG["auto_open_media"] = self.auto_open_cb.isChecked()
        CONFIG["batch_size"] = self.batch_spin.value()
        CONFIG["validate_api_on_startup"] = self.validate_startup_cb.isChecked()

        mw.addonManager.writeConfig(__name__, CONFIG)

        self.accept()
        tooltip("Settings saved successfully!", period=2000)


# ============================================================================
# GEMINI API INTERACTION
# ============================================================================

def construct_prompt() -> str:
    """Generate the system prompt for Gemini"""
    return """***

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


def encode_image_base64(file_path: str) -> Optional[str]:
    """Safely encode image to base64"""
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        log_error(f"Image encoding: {file_path}", e)
        return None


def get_gemini_response(api_key: str, model: str, current_image_path: str,
                        prev_image_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Get response from Gemini API
    Returns: (success: bool, response_text_or_error: str)
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    # Encode images
    current_b64 = encode_image_base64(current_image_path)
    if not current_b64:
        return False, f"Failed to encode image: {current_image_path}"

    prev_b64 = encode_image_base64(prev_image_path) if prev_image_path else None

    # Construct request
    parts = [{"text": construct_prompt()}]

    if prev_b64:
        parts.append({"text": "--- CONTEXT ONLY (Previous Page) ---"})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": prev_b64
            }
        })

    parts.append({"text": "--- TARGET IMAGE (Generate Cards) ---"})
    parts.append({
        "inline_data": {
            "mime_type": "image/jpeg",
            "data": current_b64
        }
    })

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

            # Check for content filtering
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
# CARD PARSING & VALIDATION
# ============================================================================

def parse_gemini_response(response_text: str) -> List[Tuple[str, str, str, str, str]]:
    """
    Parse Gemini response into card tuples
    Returns: List of (subtopic, question, choices, correct, extra)
    """
    cards = []
    lines = response_text.strip().split('\n')

    for line_num, line in enumerate(lines, 1):
        line = line.strip()

        # Skip empty lines and markdown headers
        if not line or line.startswith('#') or '|' not in line:
            continue

        parts = line.split('|')

        # Need at least 5 parts
        if len(parts) < 5:
            print(f"Warning: Line {line_num} has only {len(parts)} parts, skipping")
            continue

        # Extract and clean parts
        subtopic = parts[0].strip()
        question = parts[1].strip()
        choices = parts[2].strip()
        correct = parts[3].strip()
        extra = parts[4].strip()

        # Validation
        if not question or not choices:
            print(f"Warning: Line {line_num} missing question or choices, skipping")
            continue

        cards.append((subtopic, question, choices, correct, extra))

    return cards


# ============================================================================
# MAIN IMPORT WORKFLOW
# ============================================================================

class ImportProgressDialog(QDialog):
    """Progress dialog with detailed status - NOW CLOSEABLE"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Progress")
        self.setMinimumWidth(500)
        
        # Allow closing with X button
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
        """Update progress bar and status"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"{status} ({current}/{total})")
        QApplication.processEvents()

    def add_detail(self, message: str):
        """Add detail message"""
        self.details_text.append(message)
        QApplication.processEvents()

    def is_cancelled(self) -> bool:
        """Check if user cancelled"""
        return self.cancelled

    def mark_complete(self):
        """Mark import as complete - changes button behavior"""
        self.import_complete = True
        self.cancel_btn.setText("Close")
        self.status_label.setText("Import Complete!")

    def cancel_import(self):
        """Handle cancel/close"""
        if self.import_complete:
            # Import done, just close
            self.accept()
        else:
            # Import in progress, confirm cancellation
            if askUser("Cancel import?\n\nAlready imported cards will be kept."):
                self.cancelled = True
                self.cancel_btn.setEnabled(False)
                self.status_label.setText("Cancelling...")
                
    def closeEvent(self, event):
        """Handle window close button (X)"""
        if self.import_complete:
            # Import done, allow close
            event.accept()
        else:
            # Import in progress, confirm cancellation
            if askUser("Cancel import?\n\nAlready imported cards will be kept."):
                self.cancelled = True
                self.cancel_btn.setEnabled(False)
                self.status_label.setText("Cancelling...")
                event.accept()
            else:
                event.ignore()


def run_importer():
    """Main import workflow with comprehensive error handling"""

    # 1. Validate Configuration
    api_key = CONFIG.get("api_key", "").strip()
    model_name = CONFIG.get("model", "gemini-3-flash-preview").strip()
    nt_id = CONFIG.get("note_type_id")

    # Check if API key exists and is valid format
    if not api_key:
        showWarning("API Key not configured.\n\nPlease set your Gemini API key in Settings.")
        open_settings()
        return

    # Validate API key format
    valid, msg = validate_api_key(api_key)
    if not valid:
        showWarning(f"Invalid API key:\n\n{msg}\n\nPlease check your settings.")
        open_settings()
        return

    # Resolve model dynamically from available ListModels results
    model_ok, resolved_model, model_msg, _ = choose_model_from_list(api_key, model_name)
    if not model_ok or not resolved_model:
        showWarning(f"Could not resolve a supported Gemini model:\n\n{model_msg}\n\nPlease check API key/project access in Settings.")
        return

    model_name = resolved_model

    # Validate note type
    if not nt_id:
        showWarning("Note Type not selected.\n\nPlease select a note type in Settings.")
        open_settings()
        return

    model = mw.col.models.get(nt_id)
    if not model:
        showWarning("Selected Note Type not found.\n\nIt may have been deleted. Please select another.")
        open_settings()
        return

    # Verify note type has enough fields
    if len(model['flds']) < 4:
        showWarning(f"Note Type '{model['name']}' has only {len(model['flds'])} fields.\n\n"
                    "Need at least 4 fields (Question, Choices, Answer, Extra).")
        return

    mw.col.models.set_current(model)

    # 2. Get User Input
    root_deck, ok = getText(
        "Enter Root Deck Name:\n\n"
        "Cards will be organized as:\n"
        "Root Deck::Subtopic Name\n\n"
        "Example: 'Medical::Pharmacology'",
        mw,
        title="Import to Deck"
    )

    if not ok or not root_deck:
        return

    root_deck = sanitize_deck_name(root_deck)

    # Select folder
    folder_path = QFileDialog.getExistingDirectory(
        mw,
        "Select Folder with Images",
        "",
        QFileDialog.Option.ShowDirsOnly
    )

    if not folder_path:
        return

    # 3. Validate and Sort Files
    try:
        all_files = [f for f in os.listdir(folder_path)
                     if os.path.isfile(os.path.join(folder_path, f))]
    except Exception as e:
        showWarning(f"Cannot read folder:\n\n{str(e)}")
        return

    # Filter valid images
    valid_files = []
    invalid_files = []

    for filename in all_files:
        file_path = os.path.join(folder_path, filename)
        ext = os.path.splitext(filename)[1].lower()

        if ext not in SUPPORTED_IMAGE_FORMATS:
            continue

        is_valid, msg = validate_image_file(file_path)
        if is_valid:
            valid_files.append(filename)
        else:
            invalid_files.append((filename, msg))

    if not valid_files:
        if invalid_files:
            invalid_list = "\n".join([f"• {name}: {msg}" for name, msg in invalid_files[:5]])
            if len(invalid_files) > 5:
                invalid_list += f"\n... and {len(invalid_files) - 5} more"
            showWarning(f"No valid images found.\n\nIssues:\n{invalid_list}")
        else:
            showWarning(f"No image files found in folder.\n\n"
                        f"Supported formats: {', '.join(SUPPORTED_IMAGE_FORMATS)}")
        return

    # Sort files naturally (1, 2, 10 instead of 1, 10, 2)
    def natural_sort_key(text):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

    valid_files.sort(key=natural_sort_key)

    # Show confirmation
    confirm_msg = f"Ready to import:\n\n"
    confirm_msg += f"• Folder: {os.path.basename(folder_path)}\n"
    confirm_msg += f"• Images: {len(valid_files)} files\n"
    confirm_msg += f"• Root Deck: {root_deck}\n"
    confirm_msg += f"• Note Type: {model['name']}\n"
    confirm_msg += f"• Model: {model_name}\n"

    if invalid_files:
        confirm_msg += f"\n⚠ Skipping {len(invalid_files)} invalid files"

    confirm_msg += "\n\nProceed with import?"

    if not askUser(confirm_msg):
        return

    # 4. Process Images
    progress_dlg = ImportProgressDialog(mw)
    progress_dlg.show()

    # Map field names
    field_names = [f['name'] for f in model['flds']]

    def find_field(keyword):
        for fname in field_names:
            if keyword.lower() in fname.lower():
                return fname
        return None

    f_question = find_field("Question") or field_names[0]
    f_choices = find_field("Multiple") or find_field("Choice") or field_names[1]
    f_answer = find_field("Correct") or find_field("Answer") or field_names[2]
    f_extra = find_field("Extra") or field_names[3] if len(field_names) > 3 else None

    progress_dlg.add_detail(f"Field Mapping:\n"
                            f"  Question → {f_question}\n"
                            f"  Choices → {f_choices}\n"
                            f"  Answer → {f_answer}\n"
                            f"  Extra → {f_extra or 'N/A'}")

    cards_created = 0
    files_processed = 0
    files_failed = 0
    prev_file_path = None
    error_log = []

    try:
        for index, filename in enumerate(valid_files):
            if progress_dlg.is_cancelled():
                break

            file_path = os.path.join(folder_path, filename)
            progress_dlg.update_progress(
                index + 1,
                len(valid_files),
                f"Processing: {filename}"
            )

            # Add image to Anki media
            try:
                anki_filename = mw.col.media.add_file(file_path)
            except Exception:
                error_msg = f"Failed to add media: {filename}"
                progress_dlg.add_detail(f"❌ {error_msg}")
                error_log.append((filename, error_msg))
                files_failed += 1
                continue

            # Call Gemini API
            progress_dlg.add_detail("🤖 Calling Gemini API...")
            success, response = get_gemini_response(api_key, model_name, file_path, prev_file_path)

            if not success:
                error_msg = f"API Error: {response}"
                progress_dlg.add_detail(f"❌ {error_msg}")
                error_log.append((filename, error_msg))
                files_failed += 1

                # Critical errors should stop
                if "403" in response or "invalid" in response.lower():
                    showWarning(f"Critical API Error:\n\n{response}\n\nStopping import.")
                    break

                continue

            # Parse response
            cards = parse_gemini_response(response)

            if not cards:
                error_msg = "No valid cards found in response"
                progress_dlg.add_detail(f"⚠ {error_msg}")
                error_log.append((filename, error_msg))
                files_failed += 1
                continue

            # Create notes
            file_card_count = 0
            for subtopic, question, choices, correct, extra in cards:
                try:
                    # Create deck
                    clean_subtopic = sanitize_deck_name(subtopic) if subtopic else "General"
                    target_deck = f"{root_deck}::{clean_subtopic}"
                    deck_id = mw.col.decks.id(target_deck)

                    # Create note
                    note = Note(mw.col, model)
                    note.note_type()['did'] = deck_id

                    note[f_question] = question
                    note[f_choices] = choices
                    note[f_answer] = correct

                    if f_extra:
                        extra_content = f"{extra}<br><br><img src='{anki_filename}'>"
                        note[f_extra] = extra_content

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
        # Mark import as complete
        progress_dlg.mark_complete()
        mw.reset()

    # 5. Show Results
    result_msg = "Import Complete!\n\n"
    result_msg += f"✓ Files processed: {files_processed}/{len(valid_files)}\n"
    result_msg += f"✓ Cards created: {cards_created}\n"

    if files_failed > 0:
        result_msg += f"\n⚠ Files with errors: {files_failed}\n"

    progress_dlg.add_detail(f"\n{result_msg}")

    if error_log and askUser(f"{result_msg}\n\nView error details?"):
        error_details = "\n".join([f"{fname}: {msg}" for fname, msg in error_log[:20]])
        if len(error_log) > 20:
            error_details += f"\n\n... and {len(error_log) - 20} more errors"
        showInfo(f"Error Details:\n\n{error_details}")

    # Optional: Open media folder
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
    """Open settings dialog"""
    dlg = GeminiSettings(mw)
    dlg.exec()


def show_about():
    """Show about dialog"""
    about_text = f"""
    <h2>{ADDON_NAME} v{VERSION}</h2>
    <p><b>Batch import flashcards from images using Google's Gemini AI</b></p>

    <p><b>Features:</b></p>
    <ul>
        <li>Automatic card generation from lecture slides/notes</li>
        <li>Intelligent subdeck organization</li>
        <li>Multiple Choice question format</li>
        <li>Context-aware processing (previous page memory)</li>
        <li>Gemini 3 model support</li>
    </ul>

    <p><b>Support:</b><br>
    GitHub: <a href="https://github.com/{DEFAULT_GITHUB_REPO}">
    {DEFAULT_GITHUB_REPO}</a></p>

    <p><b>Note Type Download:</b><br>
    <a href="{NOTE_TYPE_DOWNLOAD_URL}">{NOTE_TYPE_DOWNLOAD_URL}</a></p>

    <p><b>API Provider:</b><br>
    Google Gemini AI (<a href="https://ai.google.dev">ai.google.dev</a>)</p>

    <p><i>Created for students, by students</i></p>
    """

    showInfo(about_text)


def check_first_run():
    """Check if this is first run and show welcome wizard"""
    if CONFIG.get("show_welcome", True):
        dlg = WelcomeWizard(mw)
        dlg.exec()


# ============================================================================
# INITIALIZATION
# ============================================================================

def init_addon():
    """Initialize addon on Anki startup"""

    # Create menu
    menu = mw.form.menuTools.addMenu(f"⚡ {ADDON_NAME}")

    # Main import action
    action_import = QAction("📥 Import Folder...", mw)
    action_import.triggered.connect(run_importer)
    action_import.setShortcut("Ctrl+Shift+G")
    menu.addAction(action_import)

    menu.addSeparator()

    # Settings
    action_settings = QAction("⚙ Settings", mw)
    action_settings.triggered.connect(open_settings)
    menu.addAction(action_settings)

    # About
    action_about = QAction("ℹ About", mw)
    action_about.triggered.connect(show_about)
    menu.addAction(action_about)

    # Check first run (delayed to avoid startup lag)
    QTimer.singleShot(1000, check_first_run)

    # Optional: Validate API on startup
    if CONFIG.get("validate_api_on_startup", False):
        api_key = CONFIG.get("api_key", "")
        if api_key:
            def validate():
                success, msg = test_api_connection(api_key, CONFIG.get("model", "gemini-3-flash-preview"))
                if not success:
                    showWarning(f"Gemini API validation failed:\n\n{msg}\n\n"
                                "Please check your settings.")

            QTimer.singleShot(2000, validate)


# Run initialization
init_addon()
