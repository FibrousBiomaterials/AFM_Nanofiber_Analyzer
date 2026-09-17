"""
Reusable analysis and I/O modules for AFM Nanofiber Analyzer.
AFM Nanofiber Analyzer の再利用可能な解析・入出力モジュール群。
"""

# Single runtime source of the software version, recorded as provenance
# metadata in .b2z bundles. Keep in sync with [project] version in
# pyproject.toml; tests/test_pipeline.py fails when the two drift apart.
# .b2z バンドルの来歴メタデータに記録される、実行時のソフトウェア
# バージョンの単一情報源。pyproject.toml の [project] version と同期を
# 保つこと。両者がずれると tests/test_pipeline.py が失敗する。
# Between releases this carries a ".devN" suffix (PEP 440), so a bundle written
# by unreleased code is never labelled as the last release (see RELEASING.md).
# リリース間は ".devN" 付きの開発版表記とし、未リリースのコードが書いた
# バンドルが直前のリリース製と記録されないようにする（RELEASING.md 参照）。
__version__ = "2.0.0"
