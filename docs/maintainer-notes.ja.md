# Maintainer Notes

この文書は AFM Nanofiber Analyzer の保守者向けメモです。利用者向けの概要、
インストール、起動方法、GUI 説明、データ形式、引用、ライセンスは
`README.md` と `README.ja.md` を参照してください。

ここでは、GitHub 公開後の保守で壊しやすい箇所、ビルド、翻訳、ランチャー、
GUI 間データ契約に関する注意だけをまとめます。

## 保守用環境

開発、ビルド、翻訳準備を行う環境では、標準 Python と専用 `venv` の利用を
推奨します。`requirements.txt` はアプリ実行時の依存関係に限定し、
PyInstaller や翻訳準備用ツールは必要に応じて個別にインストールします。

Python 3.12 を使う場合の例:

```powershell
py -3.12 -m venv ../.venv
..\.venv\Scripts\activate
python -m pip install -U pip
python check.py
python -m pip install -r requirements.txt
python -m pip install pyinstaller babel
```

利用者向けの起動確認では、README に記載された `01_*` / `02_*` / `11_*` /
`12_*` 補助スクリプトを使います。既存の Anaconda `base` 環境へ直接依存関係を
入れる `91_*` / `92_*` スクリプトは互換性確認用であり、新規案内には使いません。

## 補助スクリプト

プロジェクト直下の補助スクリプトは、利用者が環境構築と起動を行うための
入口です。ファイル名や役割を変える場合は、README、配布手順、起動確認手順も
あわせて確認してください。

| ファイル | 用途 |
|---|---|
| `01_setup_venv.bat` | Windows で `.venv` を作成し、pip 更新、`requirements.txt` 更新、依存関係インストールを行う。 |
| `01_setup_venv.sh` | macOS / Linux で `.venv` を作成し、pip 更新、`requirements.txt` 更新、依存関係インストール、実行権限設定を行う。 |
| `02_run_from_venv.bat` | Windows で `.venv\Scripts\python.exe` を使って `Main.py` を起動する。 |
| `02_run_from_venv.sh` | macOS / Linux で `.venv/bin/python` を使って `Main.py` を起動する。 |
| `11_setup_conda_env.bat` | Windows で専用 conda 環境 `afm-analyzer` を作成または再利用し、依存関係をインストールする。 |
| `11_setup_conda_env.sh` | macOS / Linux で専用 conda 環境 `afm-analyzer` を作成または再利用し、依存関係をインストールする。 |
| `12_run_from_conda_env.bat` | Windows で専用 conda 環境 `afm-analyzer` の Python を使って `Main.py` を起動する。 |
| `12_run_from_conda_env.sh` | macOS / Linux で専用 conda 環境 `afm-analyzer` の Python を使って `Main.py` を起動する。 |
| `91_setup_anaconda.bat` / `91_setup_anaconda.sh` | 既存 Anaconda / Miniconda 環境へ直接依存関係を入れる旧方式。新規利用は非推奨。 |
| `92_run_from_anaconda.bat` / `92_run_from_anaconda.sh` | 旧方式の Anaconda / Miniconda Python を使って `Main.py` を起動する。 |

Windows の `.bat` ファイルは、実行されるファイル本体を ASCII のみにしてください。
UTF-8 で保存した日本語 `REM` コメントでも、`cmd.exe` がシステム既定のコードページで
解釈すると文字化けした断片をコマンドとして実行することがあります。`.bat` 内の
コメントは英語 `REM` のみにし、日本語の背景説明はこの文書や README.ja.md に
残します。`chcp 65001` は読み取りタイミングや環境差の影響を完全には避けられないため、
再発防止策としては使わないでください。

## ビルド

Windows 用スタンドアロン配布物は `build.py` で作成します。

```powershell
..\.venv\Scripts\activate
python build.py
```

`build.py` は import 検証、PyInstaller 用 hiddenimports / datas / binaries の
収集、`Main.auto.spec` の生成、PyInstaller 実行、`dist/Main/` への `guis/`、
`lib/`、`locale/`、`assets/` のコピーを行います。

配布時は `dist/Main/` フォルダ全体をコピーします。`Main.exe` だけを取り出すと、
GUI プラグイン、翻訳カタログ、画像アセットなどを参照できません。

## ランチャーとプラグイン

`Main.py` は `guis/` 内の GUI ファイルを AST 解析し、トップレベルの
`PLUGIN_INFO` 辞書を `ast.literal_eval()` で読みます。各 GUI ファイルでは
`PLUGIN_INFO` の値を必ずプレーンな文字列リテラルにし、`_()` や関数呼び出しを
入れないでください。

```python
PLUGIN_INFO = {
    "name": "Plot Profiler",
    "description": "Extract AFM height profiles through an interactive UI.",
}
```

`PLUGIN_INFO["name"]` は英語固定で表示します。`PLUGIN_INFO["description"]` は
GUI ファイル内ではプレーンな文字列のままにし、`Main.py` が AST 解析後に
gettext に通します。`description` を変更した場合は、翻訳カタログ側の
対応する `msgid` も更新してください。
`PLUGIN_INFO["description"]` には、ランチャー上の表示折り返しを調整する目的だけで
`\n` を入れないでください。説明文は自然な文章として保持し、折り返しはランチャー
UI 側に任せます。Python ソース上で文字列リテラルを複数行に分けることは、値に
実際の改行が入らない限り問題ありません。

プラグインの起動は `Main.py` の `--run-plugin` サブコマンド経由で行います。
スプラッシュウィンドウを表示しつつワーカースレッドでプラグインモジュールを
import するため、各プラグインは実際に使うライブラリの分だけ起動コストを
払います。PyInstaller の frozen build では bootloader が `-c` や `-m` を
解釈しないため、このサブコマンド方式を維持してください。特定機能でしか
使わない import の重いライブラリ（lmfit、pandas など）は関数内 import に
保ちます。

## GUI 保守

GUI 間で共通する処理は `lib/ui_tools.py` に集約します。代表的な共有ヘルパーは
`apply_window_size`、`setup_ttk_theme`、`setup_matplotlib_style`、
`save_figure_with_dialog`、`save_csv_with_dialog`、`create_scrolled_text`、
`create_scrolled_treeview`、`drain_ui_queue`、`UnconfirmedEntryMixin`、
`LogMixin`、`ToolTip` です。

解析やファイル読み込みなど時間のかかる処理は、Tk のメインスレッドを止めない
ようにワーカースレッドで実行し、`queue.Queue` を通して結果やログを渡します。
UI 更新はメインスレッド側で `after()` によって定期ポーリングします。共通処理に
できる場合は `lib/ui_tools.py` の `drain_ui_queue` を使います。

新しい GUI プラグインを追加する場合は、`guis/` 配下に置き、トップレベルに
リテラルな `PLUGIN_INFO` を定義し、`main() -> None` と
`if __name__ == "__main__": main()` で起動を保護します。Tk ウィンドウを
import 時に作成しないでください。

## ファイル名と import path

`lib/` 内のモジュール名や public import path を変更する場合は、少なくとも
`lib/` 内の import、`guis/*.py`、`README.md`、`README.ja.md` を確認します。

既存の public 名、ファイル名、プラグイン名、保存済みデータのキー、内部状態文字列は、
互換性に影響する可能性があります。単なる綴り修正でも、保存済みデータや
ランチャーから参照されている場合は互換性問題として扱ってください。

## `.b2z` データ契約

GUI01 は解析対象の入力ファイルごとに、1 つの `<input_stem>.b2z` バンドルと
1 つの `<input_stem>_param.json` を保存します。多数の standalone `.npy`
ファイルを出力する旧方式へ戻さないでください。

GUI01 から GUI04 までで共有する主な `.b2z` キーは次のとおりです。

| キー | 契約 |
|---|---|
| `calibrated` | 背景補正済み AFM 高さ画像。 |
| `binarized` | ナノファイバー二値マスク。 |
| `skeletonized` | 細線化されたファイバー画像。 |
| `bp` | 分岐点マスク。 |
| `ep` | 端点マスク。 |
| `kp` | shape `(2, N)` のキンク点座標。 |
| `dp` | shape `(2, N)` の分解点座標。 |
| `ka` | ラジアン単位のキンク角度。 |

### 既知の制限: 背景補正による 1 画素トリミング

背景補正器（`lib/bg_calibrator.py`）はすべての `bg_method` で出力を入力より
縦横 1 画素小さくします。これは勾配ベースの背景マスク（行・列差分で配列が
1 つ縮む）に由来する歴史的産物であり、科学的な必然ではありません。この結果、

- `calibrated` 以降の全キーの座標系が、トリミング前に保存される任意キー
  `original` に対して 1 画素ずれます。
- 生画像と処理結果を画素単位で整合比較する機能（オーバーレイ表示や
  機械学習用データ化など）は、常にこのずれを考慮する必要があります。

トリミングの廃止は既存全バンドルの形状契約を壊すため、バンドル形式 1.0 の
間は現状を仕様として維持します。フルサイズ出力への復元（トリム端の
パディング等）は、形式 2.0 を切る際の変更候補の筆頭です。コード上の定義は
`lib/bundle_schema.py` のモジュール docstring（Known accepted limitation）を
参照してください。

`.b2z` バンドルのキー、形状、単位、意味を変更する場合は、GUI01 から GUI04
までの連携に影響します。少なくとも次のファイルを同時に確認してください。

- `guis/GUI01_Image_Preprocessor.py`
- `guis/GUI02_PlotProfiler.py`
- `guis/GUI03_Fiber_Height_Histogram.py`
- `guis/GUI04_Tracking_fiber.py`
- `lib/blosc2_io.py`
- `README.md`
- `README.ja.md`

## 翻訳カタログ

ユーザー向け UI 文字列や `PLUGIN_INFO["description"]` を変更した後は、
翻訳カタログを更新します。

```powershell
..\.venv\Scripts\activate
python prepare_translate_catalogs.py
```

このスクリプトは、`pybabel extract`、`PLUGIN_INFO["description"]` の抽出、
`pybabel update`、`#~ obsolete entry` の削除、`pybabel compile` を行います。
`msgstr` は自動入力しません。古い obsolete 翻訳を参照用に残したい場合は、
実行前に Git commit またはバックアップを作成してください。

`messages.po` を手動または AI で編集した後、配布前にカタログをコンパイルします。

```powershell
pybabel compile -d locale
```

コンパイル済みの `.mo` はバージョン管理されており、クローン直後でも翻訳が
機能します。`.po` を編集したら、再生成した `.mo` も一緒にコミットして
ください。`.mo` が `.po` より古い場合は `tests/test_translations.py` が
失敗します。
## コーディングエージェントを使う場合の翻訳依頼例:

```text
locale\English\LC_MESSAGES\messages.po にある、空の msgstr "" に対応する msgid の英訳を記入してください。
locale\Chinese\LC_MESSAGES\messages.po にある、空の msgstr "" に対応する msgid の中国語訳を記入してください。

以下は変更しないでください。
- msgid
- コメント行
- 既に入力済みの msgstr
- ファイル構造
- ヘッダー項目
- #~ で始まる obsolete entry

msgid が複数行の場合も、msgid 側は変更せず、対応する msgstr だけを同じ情報量で翻訳してください。
msgstr "" の直後に翻訳済みの継続行がある項目は空ではないため、変更しないでください。
#, fuzzy が付いた項目は、msgid と msgstr の意味、プレースホルダー、改行を確認し、必要に応じて msgstr を修正してください。
#, fuzzy 行は、訳文を書き直したうえで削除してください。
判断に迷った項目は作業結果の報告に列挙し、訳の妥当性は保守・点検担当者が GUI を実行して確認してください。
表示上の折り返し位置を調整する目的だけで、翻訳済み msgstr の1文の途中に \n を入れないでください。
明示的な \n は、UI 上で意味のある段落区切りや改行が必要な場合だけ使用してください。
```

## `messages.po` 編集時の注意

AI やコーディングエージェントで翻訳を補助する場合は、`msgid`、コメント行、
ファイル構造、ヘッダー項目、`#~` で始まる obsolete entry を変更しないように
指示してください。空の `msgstr ""` だけを埋める作業と、`#, fuzzy` の確認は
分けて行います。

PO syntax では、`msgstr ""` の直後に翻訳済みの文字列継続行があるエントリは
空ではありません。空欄を埋める作業では、そのようなエントリを既存訳として扱い、
変更しないでください。

翻訳済み `msgstr` では、表示上の折り返し位置を調整する目的だけで、1文の途中に
`\n` を入れないでください。適切な折り返し位置は言語ごとに異なるため、折り返しは
UI 側に任せます。明示的な `\n` は、UI 上で意味のある段落区切りや改行が必要な場合
だけ使用してください。

`#, fuzzy` は gettext / Babel が既存の近い訳文を仮流用したことを示す
要確認マークです。翻訳作業では fuzzy 項目を確認し、`msgstr` を必要に応じて
書き直したうえで `#, fuzzy` 行を削除します。`#, fuzzy` が残った項目は
コンパイル時に `.mo` へ含まれず翻訳として扱われないため、
配布前に残さないでください。

確認時は次を照合してください。

- `msgid` と `msgstr` の意味が一致しているか。
- `{g}`、`{p}`、`{m}`、`{path}` などの python-brace-format プレースホルダー名が一致しているか。
- `%s`、`%d` などの python-format プレースホルダーが保持されているか。
- 必要な `\n` が保持されているか。
- UI 表示として自然で、情報量が `msgid` と同等か。

判断に迷った訳は作業結果の報告に列挙し、保守・点検担当者が GUI 上の表示と
文脈を確認します。
