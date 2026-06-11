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
__version__ = "1.0.0"
