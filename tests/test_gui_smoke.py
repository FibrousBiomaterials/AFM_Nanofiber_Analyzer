# -*- coding: utf-8 -*-
"""
Construction smoke tests for the four GUI plugins.
4 つの GUI プラグインの構築スモークテスト。

Each test builds the plugin's window, lets Tk lay the widgets out, and destroys
it. That is deliberately all it asserts: the widget tree, its labels, and its
layout are free to change, and a test that pinned them down would fail on every
cosmetic edit. What it does catch is the largest class of real GUI regressions
— the window no longer builds at all, because an option name is wrong, an asset
is missing, a callback is misspelled, or a `lib.ui_tools` helper changed shape.
各テストはウィンドウを構築し、Tk にレイアウトさせ、破棄する。検証をこれだけに
留めるのは意図的で、ウィジェット構成・ラベル・レイアウトは自由に変更されるため、
それらを固定するテストは見た目の変更のたびに壊れる。一方でこのテストは、実際に
起こる GUI リグレッションの最大の類型——オプション名の誤り、アセットの欠落、
コールバック名の typo、`lib.ui_tools` ヘルパーのシグネチャ変更などにより
ウィンドウがそもそも構築できない——を確実に捕捉する。
"""

import pytest

from conftest import requires_tk

import guis.GUI01_Image_Preprocessor as gui01
import guis.GUI02_PlotProfiler as gui02
import guis.GUI03_Fiber_Height_Histogram as gui03
import guis.GUI04_Tracking_fiber as gui04

pytestmark = requires_tk


@pytest.fixture
def isolated_gui01_settings(tmp_path, monkeypatch):
    """
    Redirect GUI01's startup settings file into a temporary directory.
    GUI01 の起動時設定ファイルを一時ディレクトリへ退避させる。

    `load_or_create_startup_params` writes `guis/afmpp_settings.json` when it is
    missing, so constructing the app in a test would otherwise create or
    overwrite the developer's own local settings.
    `load_or_create_startup_params` は設定ファイルが無ければ
    `guis/afmpp_settings.json` を作成するため、退避しないとテストが開発者の
    ローカル設定を作成・上書きしてしまう。
    """
    settings = tmp_path / "afmpp_settings.json"
    monkeypatch.setattr(gui01, "_settings_path", lambda: str(settings))
    return settings


def _assert_window_built(app) -> None:
    """Assert that the window exists and actually built a widget tree."""
    assert app.winfo_exists()
    assert app.title()
    assert app.winfo_children(), "the window built no widgets"


def test_gui01_window_builds(tk_app, isolated_gui01_settings):
    _assert_window_built(tk_app(gui01.App))


def test_gui02_window_builds(tk_app):
    _assert_window_built(tk_app(gui02.App))


def test_gui03_window_builds(tk_app):
    _assert_window_built(tk_app(gui03.App))


def test_gui04_window_builds(tk_app):
    _assert_window_built(tk_app(gui04.App))
