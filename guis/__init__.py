"""
GUI plugins that `Main.py` launches.
`Main.py` が起動する GUI プラグイン。

Each module here that defines a module-level `PLUGIN_INFO` dictionary is one
plugin; `Main.py` lists it without importing it and starts it on request.
モジュールレベルの `PLUGIN_INFO` 辞書を定義する各モジュールが 1 つのプラグインで
ある。`Main.py` は import せずにそれを一覧に載せ、要求されたときに起動する。
"""
