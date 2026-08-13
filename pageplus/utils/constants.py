from __future__ import annotations

from enum import Enum
from pathlib import Path

from pageplus.utils.appdirs import user_data_dir

# --- App Information ---
APP_NAME = "PagePlus"
APP_AUTHOR = "PagePlus"


class WorkState(str, Enum):
    """
    State of the current data
    """
    ORIGINAL = "original"
    MODIFIED = "modified"


class ProfileLevel(str, Enum):
    """
    Level of function profiling
    """
    stats = "stats"
    params = "params"
    results = "results"
    analytics = "analytics"
    summary = "summary"


# --- Tesseract Language Names ---
TesseractLanguageNames = {
    'eng': 'English',
    'deu': 'German',
    'fra': 'French',
    'spa': 'Spanish',
    'ita': 'Italian',
    'por': 'Portuguese',
    'rus': 'Russian',
    'chi_sim': 'Chinese (Simplified)',
    'chi_tra': 'Chinese (Traditional)',
    'jpn': 'Japanese',
    'kor': 'Korean',
    'ara': 'Arabic',
    'hin': 'Hindi',
    'nld': 'Dutch',
    'swe': 'Swedish',
    'nor': 'Norwegian',
    'dan': 'Danish',
    'fin': 'Finnish',
    'pol': 'Polish',
    'ces': 'Czech',
    'hun': 'Hungarian',
    'ron': 'Romanian',
    'bul': 'Bulgarian',
    'hrv': 'Croatian',
    'slk': 'Slovak',
    'slv': 'Slovenian',
    'est': 'Estonian',
    'lav': 'Latvian',
    'lit': 'Lithuanian',
    'ell': 'Greek',
    'tur': 'Turkish',
    'heb': 'Hebrew',
    'tha': 'Thai',
    'vie': 'Vietnamese',
    'ind': 'Indonesian',
    'msa': 'Malay',
    'tgl': 'Tagalog',
    'cat': 'Catalan',
    'eus': 'Basque',
    'glg': 'Galician',
    'cym': 'Welsh',
    'gle': 'Irish',
    'sco': 'Scots',
    'gla': 'Scottish Gaelic',
    'bre': 'Breton',
    'cor': 'Cornish',
    'oci': 'Occitan',
    'ast': 'Asturian',
    'ext': 'Extremaduran',
    'arg': 'Aragonese',
    'an': 'Aragonese',
    'mwl': 'Mirandese',
    'lad': 'Ladino',
    'scn': 'Sicilian',
    'nap': 'Neapolitan',
    'vec': 'Venetian',
    'lmo': 'Lombard',
    'pms': 'Piedmontese',
    'lij': 'Ligurian',
    'eml': 'Emilian-Romagnol',
    'fur': 'Friulian',
    'lfn': 'Lingua Franca Nova',
    'ido': 'Ido',
    'nov': 'Novial',
    'vol': 'Volapük',
    'epo': 'Esperanto',
    'ina': 'Interlingua',
    'lat': 'Latin',
    'grc': 'Ancient Greek',
    'san': 'Sanskrit',
    'pli': 'Pali',
    'tib': 'Tibetan',
    'bod': 'Tibetan',
    'mon': 'Mongolian',
    'kaz': 'Kazakh',
    'kir': 'Kyrgyz',
    'uzb': 'Uzbek',
    'tgk': 'Tajik',
    'tuk': 'Turkmen',
    'aze': 'Azerbaijani',
    'kat': 'Georgian',
    'hye': 'Armenian',
    'oss': 'Ossetian',
    'abk': 'Abkhazian',
    'che': 'Chechen',
    'ava': 'Avar',
    'kbd': 'Kabardian',
    'ady': 'Adyghe',
    'lez': 'Lezghian',
    'tab': 'Tabasaran',
    'dar': 'Dargwa',
    'lbe': 'Lak',
    'inh': 'Ingush',
    'ce': 'Chechen',
    'krc': 'Karachay-Balkar',
    'kum': 'Kumyk',
    'nog': 'Nogai',
    'bak': 'Bashkir',
    'tat': 'Tatar',
    'chv': 'Chuvash',
    'udm': 'Udmurt',
    'kom': 'Komi',
    'myv': 'Erzya',
    'mdf': 'Moksha',
    'mari': 'Mari'
}


class Languages(str, Enum):
    """Supported languages for spellchecking."""
    en = "en"
    de = "de"
    es = "es"
    fr = "fr"
    pt = "pt"
    ru = "ru"
    ar = "ar"


class OutputFormats(str, Enum):

    """
    Level of function profiling
    """
    txt = "txt"
    page = "page"
    alto = "alto"
    json = "json"


class TextLevel(str, Enum):
    """
    Level of text
    """
    TextRegion = "TextRegion"
    TableRegion = "TableRegion"
    Textline = "Textline"
    Word = "Word"
    Glyph = "Glyph"


class RecognizeLevel(str, Enum):
    """
    Level of text
    """
    Page = "Page"
    TextRegion = "TextRegion"
    TableRegion = "TableRegion"
    Textline = "Textline"


class UpdateElements(str, Enum):
    """
    Elements to update
    """
    TEXT = "Text"
    TAGS = "Tags"


class DrawingsPDF(str, Enum):
    """
    Level of function profiling
    """
    region = "region"
    line = "line"
    baseline = "baseline"
    word = "word"


class PagePlus(str, Enum):
    """
    Pageplus configuration
    """
    SYSTEM = "System"

    def as_prefix(self):
        return f"{self.name.upper()}_"

    def as_prefix_workspace_dir(self):
        return f"{self.name.upper()}_WS_DIR"


class Provider(str, Enum):
    pass


class LLMProvider(Provider):
    OPENAI = "OpenAI"
    OLLAMA = "Ollama"
    GROQ = "Groq"
    AZURE = "Azure"
    DEEPSEEK = "Deepseek"
    MISTRAL_AZURE = "Mistral Azure"
    VERTEX_AI = "Vertex AI"
    PALM = "PaLM"
    GEMINI = "Gemini"
    MISTRAL = "Mistral"
    ANTHROPIC = "Anthropic"
    AWS_SAGEMAKER = "Sagemaker"
    AWS_BEDROCK = "Bedrock"
    ANYSCALE = "Anyscale"
    HUGGINGFACE = "Huggingface"


class Environments(str, Enum):
    """
    Service names are used as prefixes with _ for dotenvs variables
    """
    PAGEPLUS = "PagePlus"
    # METS           = "METS"
    # IIIF           = "IIIF"
    ESCRIPTORIUM = "eScriptorium"
    TRANSKRIBUS = "Transkribus"
    DINGLEHOPPER = "Dinglehopper"
    LLM = "LLM"
    GEMINI = "GEMINI"

    def as_prefix(self):
        return f"{self.name.upper()}_"

    def as_prefix_workspace(self):
        return "PAGEPLUS_WS_"

    def as_prefix_loaded_workspace(self):
        return "PAGEPLUS_LOADED_WS"

    def as_prefix_environment(self):
        return f"{self.name.upper()}_ENVIRONMENT"

    def as_prefix_workstate(self, state: WorkState):
        if state == "original":
            return f"{self.name.upper()}_ORIGINAL"
        else:
            return f"{self.name.upper()}_MODIFIED"


# Converts boolean values to on and off
Bool2OnOff = {True: "on", False: "off"}

MIME_IMAGE_EXTENSIONS = {
    'image/jpeg': '.jpg',
    'image/pjpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/bmp': '.bmp',
    'image/x-windows-bmp': '.bmp',
    'image/x-icon': '.ico',
    'image/vnd.microsoft.icon': '.ico',
    'image/tiff': '.tiff',
    'image/x-tiff': '.tiff',
    'image/svg+xml': '.svg',
    'image/heic': '.heic',
    'image/heif': '.heif',
    'image/avif': '.avif',
    'image/vnd.adobe.photoshop': '.psd',
}


class ImageExtension(str, Enum):
    png = '.png'
    jpg = '.jpg'
    jpeg = '.jpeg'
    tif = '.tif'
    tiff = '.tiff'
    bmp = '.bmp'
    gif = '.gif'
    heic = '.heic'
    heif = '.heif'
    webp = '.webp'


class PcGtsVersion(Enum):
    """Enum for different PAGE XML versions."""
    V2010_01_12 = "2010-01-12"
    V2010_03_19 = "2010-03-19"
    V2013_07_15 = "2013-07-15"
    V2015_07_15 = "2015-07-15"
    V2016_07_15 = "2016-07-15"
    V2017_07_15 = "2017-07-15"
    V2018_07_15 = "2018-07-15"
    V2019_07_15 = "2019-07-15"

    @classmethod
    def get_latest(cls) -> 'PcGtsVersion':
        """Get the latest version."""
        return cls.V2019_07_15


# For more details, see: https://ocr-d.de/en/spec/ocrd_page#textline
VALID_TEXTLINE_ORDER = {"top-to-bottom", "bottom-to-top",
                        "left-to-right", "right-to-left"}

# User Agent for HTTP requests
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# --- Base Directories ---
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]

# --- User-Specific Directories (in user's home folder) ---
USER_DATA_DIR = Path(user_data_dir(APP_NAME, APP_AUTHOR))
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

GUI_STORAGE_DIR = USER_DATA_DIR / "storage"
GUI_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = USER_DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- Static Asset and Resource Directories (part of the package) ---
ASSETS_DIR = PROJECT_ROOT / "assets"
GUIDELINES_DIR = PACKAGE_ROOT / "utils" / "guidelines"

# --- File Paths ---
ENV_FILE = USER_DATA_DIR / ".env"
LOGO_PATH = ASSETS_DIR / 'img' / 'Tight_PagePlus_Logo.png'
LOADING_PATH = ASSETS_DIR / 'img' / 'loading_pageplus.gif'
