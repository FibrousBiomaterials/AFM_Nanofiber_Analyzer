"""
Central gettext translation helpers for the application.
アプリケーション全体で使う gettext 翻訳ヘルパーを提供する。
"""

import gettext
import sys
from pathlib import Path

# ----------------------------------------------------------------------
# Path resolution
# ----------------------------------------------------------------------
# In frozen PyInstaller builds, use the executable directory as the base.
# PyInstaller の凍結環境では exe と同じディレクトリを基点にする。
# In source mode, this file is at <project>/lib/translator.py,
# so the project root is the parent of this file's directory.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

LOCALE_DIR = BASE_DIR / "locale"

DOMAIN = "messages"


def _discover_supported_languages():
    """
    Return language codes that have gettext message catalogs.
    gettext メッセージカタログを持つ言語コードを返す。

    Returns
    -------
    tuple of str
        Language directory names containing ``LC_MESSAGES/messages.mo`` or
        ``LC_MESSAGES/messages.po``.
        ``LC_MESSAGES/messages.mo`` または ``LC_MESSAGES/messages.po`` を含む
        言語ディレクトリ名。

    Notes
    -----
    Empty locale folders and unrelated folders such as ``__pycache__`` are
    ignored.
    """
    if not LOCALE_DIR.is_dir():
        return ()
    found = []
    for child in sorted(LOCALE_DIR.iterdir()):
        if not child.is_dir():
            continue
        lc_messages = child / "LC_MESSAGES"
        if not lc_messages.is_dir():
            continue
        if (lc_messages / f"{DOMAIN}.mo").exists() or \
           (lc_messages / f"{DOMAIN}.po").exists():
            found.append(child.name)
    return tuple(found)


# Determined by scanning locale/. Fall back to ("en",) so that set_language()
# always has at least one valid code to initialize with.
# locale/ をスキャンして決定する。空ならフォールバックで ("en",) を入れて
# set_language() が常に何らかの値で初期化できるようにしておく。
SUPPORTED = _discover_supported_languages() or ("en",)

# Default language: prefer "English" if available, otherwise the first detected.
# 既定言語: English があれば English、無ければ最初に見つかった言語。
DEFAULT = "English" if "English" in SUPPORTED else SUPPORTED[0]

# ----------------------------------------------------------------------
# Internal state
# ----------------------------------------------------------------------
_current_translation = gettext.NullTranslations()
_current_language_code = DEFAULT


def set_language(lang: str) -> None:
    """
    Switch the active translation language.
    有効な翻訳言語を切り替える。

    Parameters
    ----------
    lang
        Language code to activate. Unsupported codes fall back to ``DEFAULT``.
        有効化する言語コード。未対応コードの場合は ``DEFAULT`` にフォールバックする。

    Returns
    -------
    None
        The module-level translation state is updated in place.
        モジュールレベルの翻訳状態をインプレースで更新する。
    """
    global _current_translation, _current_language_code
    if lang not in SUPPORTED:
        lang = DEFAULT
    mo_path = LOCALE_DIR / lang / "LC_MESSAGES" / f"{DOMAIN}.mo"
    try:
        with mo_path.open("rb") as fp:
            _current_translation = gettext.GNUTranslations(fp)
    except (FileNotFoundError, OSError):
        _current_translation = gettext.NullTranslations()
    _current_language_code = lang


def _(message: str) -> str:
    """
    Translate a source string with the active gettext catalog.
    有効な gettext カタログでソース文字列を翻訳する。

    Parameters
    ----------
    message
        Source string marked for translation.
        翻訳対象としてマークされたソース文字列。

    Returns
    -------
    str
        Translated string, or the original string when no catalog entry exists.
        カタログ項目がない場合は元の文字列を返す翻訳後文字列。
    """
    return _current_translation.gettext(message)


def current_language() -> str:
    """
    Return the currently active language code.
    現在有効な言語コードを返す。

    Returns
    -------
    str
        Active language code.
        有効な言語コード。
    """
    return _current_language_code


def load_saved_language() -> str:
    """
    Load the previously selected language from the preference file.
    設定ファイルから前回選択された言語を読み込む。

    Returns
    -------
    str
        Saved supported language code, or ``DEFAULT`` if loading fails.
        保存済みの対応言語コード。読み込みに失敗した場合は ``DEFAULT``。
    """
    try:
        pref_file = BASE_DIR / ".lang_preference"
        if pref_file.exists():
            code = pref_file.read_text(encoding="utf-8").strip()
            if code in SUPPORTED:
                return code
    except Exception:
        pass
    return DEFAULT


# Restore the saved language when the module is imported.
# モジュールロード時に保存済み言語を復元する。
set_language(load_saved_language())
