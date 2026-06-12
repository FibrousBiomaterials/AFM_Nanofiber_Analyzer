# -*- coding: utf-8 -*-
"""
Compatibility shim for the renamed background-calibrator module.
改名された背景補正モジュールの互換シム。

The calibrator implementation lives in `bg_calibrator` under the
instrument-neutral name `BGCalibrator`; the algorithms are general line-scan
AFM corrections, not Shimadzu-specific. This module preserves the historical
import path and class name so existing code, scripts, and saved settings
keep working. New code should import from `lib.bg_calibrator` directly.
補正器の実装は装置非依存の名称 `BGCalibrator` として `bg_calibrator` に
ある。アルゴリズムはラインスキャン AFM 一般の補正であり、島津固有ではない。
本モジュールは従来の import パスとクラス名を維持し、既存コード・スクリプト・
保存済み設定を壊さないためのものである。新規コードは `lib.bg_calibrator`
から直接 import すること。
"""

from .bg_calibrator import BGCalibrator

# Historical alias: the class was developed on Shimadzu SPM-9600 scans and
# was originally named after that instrument.
# 歴史的別名。本クラスは島津 SPM-9600 のスキャンを対象に開発され、当初は
# 装置名を冠していた。
BG_Calibrator_shimadzu = BGCalibrator
