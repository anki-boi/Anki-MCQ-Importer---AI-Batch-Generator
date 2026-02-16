# True Anki MCQ Importer - AI Batch Generator (v3.1 - Production Ready Edition)
# Features: Robust Error Handling, Auto-Setup Wizard, GitHub Auto-Update,
# Dynamic Note Type Selection, Model Switching, Settings GUI, Comprehensive Validation

import os
import json
import urllib.request
import urllib.error
import base64
import re
import tempfile
import traceback
from typing import Optional, List, Tuple
import time

from aqt import mw
from aqt.utils import showInfo, showWarning, askUser, tooltip, getText
from aqt.qt import *
from anki.notes import Note
from anki.importing.apkg import AnkiPackageImporter

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

ADDON_NAME = "Anki MCQ Importer - AI Batch Generator"
VERSION = "3.1.0"
DEFAULT_GITHUB_REPO = "anki-boi/True-Anki-MCQ-Note-Template"
DEFAULT_NOTE_TYPE_URL = "https://github.com/anki-boi/True-Anki-MCQ-Note-Template/releases/download/v4.25.0/zNote.Updater.apkg"
SUPPORTED_IMAGE_FORMATS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')
MAX_FILE_SIZE_MB = 20  # Maximum image file size in MB
GEMINI_MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
    "gemini-2.0-flash-exp"
]


# Load or create default configuration
def get_default_config():
    return {
        "api_key": "",
        "model": "gemini-1.5-flash",
        "note_type_id": None,
        "github_repo": DEFAULT_GITHUB_REPO,
        "show_welcome": True,
        "auto_open_media": True,
        "batch_size": 10,  # For progress updates
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

    # Prefer common fast/cost-effective models first when available.
    for candidate in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        if candidate in models:
            return True, candidate, msg, models

    return True, models[0], msg, models


def download_note_type_apkg(repo: str) -> Tuple[bytes, str]:
    """Download note type package from latest release, with direct URL fallback."""
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    release_error = None

    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': 'AnkiAddon'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())

        for asset in data.get('assets', []):
            if asset.get('name', '').endswith('.apkg'):
                with urllib.request.urlopen(asset['browser_download_url'], timeout=60) as dl_resp:
                    return dl_resp.read(), f"{asset['name']} ({data.get('tag_name', 'latest')})"

        release_error = "No .apkg asset found in latest release."
    except Exception as e:
        release_error = str(e) or repr(e)

    # Direct fallback provided by the template maintainer.
    try:
        with urllib.request.urlopen(DEFAULT_NOTE_TYPE_URL, timeout=60) as dl_resp:
            return dl_resp.read(), os.path.basename(DEFAULT_NOTE_TYPE_URL)
    except Exception as e:
        fallback_error = str(e) or repr(e)
        raise RuntimeError(
            f"Could not download note type from GitHub release or fallback URL. "
            f"Release error: {release_error}. Fallback error: {fallback_error}"
        ) from e


def remove_temp_file(path: str):
    """Best-effort cleanup for temp files; tolerate Windows file locking."""
    if not path:
        return

    for _ in range(5):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except PermissionError:
            time.sleep(0.2)
        except OSError:
            return


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
        <p>This wizard will help you set up the addon in 3 easy steps:</p>
        <ol>
            <li><b>Get your Gemini API Key</b> (free from Google)</li>
            <li><b>Download the Note Type</b> (automatic from GitHub)</li>
            <li><b>Configure your preferences</b></li>
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

        # Step 2: Note Type
        layout.addWidget(QLabel("<hr>"))
        layout.addWidget(QLabel("<h3>Step 2: Download Note Type</h3>"))

        nt_instructions = QLabel("""
        <p>Click the button below to automatically download the latest
        Multiple Choice note type from GitHub.</p>
        """)
        nt_instructions.setWordWrap(True)
        layout.addWidget(nt_instructions)

        download_btn = QPushButton("📥 Download Note Type from GitHub")
        download_btn.clicked.connect(self.download_note_type)
        layout.addWidget(download_btn)

        self.nt_status = QLabel("Status: Not downloaded yet")
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

        self.downloaded_note_type = False
        self.api_tested = False

    def validate_inputs(self):
        """Enable finish button when requirements met"""
        has_api = len(self.api_input.text().strip()) > 0
        self.finish_btn.setEnabled(has_api and self.downloaded_note_type)

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

    def download_note_type(self):
        """Download note type from GitHub"""
        try:
            self.nt_status.setText("Downloading...")
            QApplication.processEvents()

            content, source_label = download_note_type_apkg(DEFAULT_GITHUB_REPO)

            # Save to temp
            fd, path = tempfile.mkstemp(suffix=".apkg")
            try:
                with os.fdopen(fd, 'wb') as tmp:
                    tmp.write(content)

                # Import into Anki
                importer = AnkiPackageImporter(mw.col, path)
                importer.run()
            finally:
                remove_temp_file(path)

            self.nt_status.setText(f"<span style='color: green;'>✓ Downloaded {source_label}</span>")
            self.downloaded_note_type = True
            self.validate_inputs()

        except Exception as e:
            log_error("Note type download", e)
            self.nt_status.setText(f"<span style='color: red;'>❌ Download failed: {str(e)}</span>")

    def finish_setup(self):
        """Save configuration and close"""
        CONFIG["api_key"] = self.api_input.text().strip()
        CONFIG["show_welcome"] = False

        # Try to auto-select the downloaded note type
        models = mw.col.models.all()
        for m in models:
            if "Multiple Choice" in m['name'] or "MCQ" in m['name']:
                CONFIG["note_type_id"] = m['id']
                break

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
        <p><i>Flash models are faster and cheaper, Pro models are more capable.<br>
        Flash-8b is the fastest, Pro is most accurate.</i></p>
        """)
        model_help.setWordWrap(True)
        api_layout.addWidget(model_help)

        self.model_combo = QComboBox()
        self.model_combo.addItems(GEMINI_MODELS)
        self.model_combo.setEditable(True)
        current_model = CONFIG.get("model", "gemini-1.5-flash")
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

        nt_layout.addWidget(QLabel("""
        <p>Download the latest Multiple Choice note type template from GitHub,
        or select an existing note type from your collection.</p>
        """))

        download_section = QGroupBox("Download from GitHub")
        download_layout = QVBoxLayout()
        download_section.setLayout(download_layout)
        nt_layout.addWidget(download_section)

        download_layout.addWidget(QLabel(f"Repository: <b>{CONFIG.get('github_repo', DEFAULT_GITHUB_REPO)}</b>"))

        download_btn = QPushButton("📥 Download Latest Note Type")
        download_btn.clicked.connect(self.download_from_github)
        download_layout.addWidget(download_btn)

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

    def download_from_github(self):
        """Download note type from GitHub"""
        repo = CONFIG.get("github_repo", DEFAULT_GITHUB_REPO)

        mw.progress.start(label="Downloading...", immediate=True)

        try:
            mw.progress.update(label="Downloading note type...")
            content, source_label = download_note_type_apkg(repo)

            # Save to temp
            fd, path = tempfile.mkstemp(suffix=".apkg")
            try:
                with os.fdopen(fd, 'wb') as tmp:
                    tmp.write(content)

                # Import into Anki
                mw.progress.update(label="Importing into Anki...")
                importer = AnkiPackageImporter(mw.col, path)
                importer.run()
            finally:
                remove_temp_file(path)

            # Refresh dropdown
            self.populate_note_types()

            # Auto-select if possible
            for i in range(self.nt_combo.count()):
                if "Multiple Choice" in self.nt_combo.itemText(i):
                    self.nt_combo.setCurrentIndex(i)
                    break

            showInfo(f"✓ Successfully imported '{source_label}'!")

        except urllib.error.HTTPError as e:
            if e.code == 404:
                showWarning(f"Repository not found or no releases available.\n\n"
                            f"URL: https://github.com/{repo}")
            else:
                showWarning(f"HTTP Error {e.code}: {e.read().decode('utf-8', errors='ignore')}")
        except Exception as e:
            log_error("GitHub download", e)
            showWarning(f"Download failed:\n\n{str(e)}")
        finally:
            mw.progress.finish()

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
    return """*** SYSTEM INSTRUCTION: SUBDECK ROUTING ***
You are an Anki CSV generator. Output 5 columns separated by pipes (|).
Format: Subtopic Name|Question|Multiple Choice|Correct Answers|Extra

1. Subtopic: Analyze header. If continuation, use previous topic.
2. Follow USER PROMPT below exactly.

*** USER PROMPT ***
**Objective:** Create high-yield MCQs.
**Priorities:** Classification, Drug Names, MoA, Uses, Side Effects.
**Distractors:** Must be contextually relevant and of similar length/structure.
**Format:**
- HTML <br> for line breaks in choices.
- No Markdown headers.
- Mnemonics in Extra column only.

**Output Rules:**
- One question per line
- Exactly 5 pipe-separated columns
- No extra formatting or commentary
- Include 3-5 questions per image minimum
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
    """Progress dialog with detailed status"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Progress")
        self.setMinimumWidth(500)

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

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)

        self.cancelled = False

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

    def reject(self):
        """Handle cancel"""
        if askUser("Cancel import?\n\nAlready imported cards will be kept."):
            self.cancelled = True
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("Cancelling...")


def run_importer():
    """Main import workflow with comprehensive error handling"""

    # 1. Validate Configuration
    api_key = CONFIG.get("api_key", "").strip()
    model_name = CONFIG.get("model", "gemini-1.5-flash").strip()
    nt_id = CONFIG.get("note_type_id")

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
        progress_dlg.close()
        mw.reset()

    # 5. Show Results
    result_msg = "Import Complete!\n\n"
    result_msg += f"✓ Files processed: {files_processed}/{len(valid_files)}\n"
    result_msg += f"✓ Cards created: {cards_created}\n"

    if files_failed > 0:
        result_msg += f"\n⚠ Files with errors: {files_failed}\n"

    if error_log:
        result_msg += "\n\nView error details?"

        if askUser(result_msg):
            error_details = "\n".join([f"{fname}: {msg}" for fname, msg in error_log[:20]])
            if len(error_log) > 20:
                error_details += f"\n\n... and {len(error_log) - 20} more errors"
            showInfo(f"Error Details:\n\n{error_details}")
    else:
        showInfo(result_msg)

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
        <li>Auto-update from GitHub</li>
    </ul>

    <p><b>Support:</b><br>
    GitHub: <a href="https://github.com/{DEFAULT_GITHUB_REPO}">
    {DEFAULT_GITHUB_REPO}</a></p>

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
                success, msg = test_api_connection(api_key, CONFIG.get("model", "gemini-1.5-flash"))
                if not success:
                    showWarning(f"Gemini API validation failed:\n\n{msg}\n\n"
                                "Please check your settings.")

            QTimer.singleShot(2000, validate)


# Run initialization
init_addon()
