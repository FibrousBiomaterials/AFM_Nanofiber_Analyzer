# -*- coding: utf-8 -*-
"""
Compatibility shim for the renamed background-calibrator module.
改名された背景補正モジュールの互換シム。

The calibrator implementation lives in `bg_calibrator` under the
instrument-neutral name `BGCalibrator`; the algorithms are general line-scan
AFM corrections, not Shimadzu-specific. This module keeps the import path
and class name ``BG_Calibrator_shimadzu`` available so existing code,
scripts, and saved settings keep working. New code should import from `lib.bg_calibrator` directly.
補正器の実装は装置非依存の名称 `BGCalibrator` として `bg_calibrator` に
ある。アルゴリズムはラインスキャン AFM 一般の補正であり、島津固有ではない。
本モジュールは import パスとクラス名 ``BG_Calibrator_shimadzu`` を利用可能に保ち、既存コード・スクリプト・
保存済み設定を壊さないためのものである。新規コードは `lib.bg_calibrator`
から直接 import すること。
"""

from .bg_calibrator import BGCalibrator

# Alias kept so code that imports the Shimadzu-named class keeps working.
# 島津名のクラスを import するコードが動き続けるよう残す別名。
BG_Calibrator_shimadzu = BGCalibrator
