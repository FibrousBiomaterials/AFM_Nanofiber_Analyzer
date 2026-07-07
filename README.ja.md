# AFM Nanofiber Analyzer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![tests](https://github.com/FibrousBiomaterials/AFM_Nanofiber_Analyzer/actions/workflows/test.yml/badge.svg)](https://github.com/FibrousBiomaterials/AFM_Nanofiber_Analyzer/actions/workflows/test.yml)

![AFM Nanofiber Analyzer の概要図](assets/afm_symbol.png)

AFM Nanofiber Analyzer は、原子間力顕微鏡 (AFM) の高さ画像を前処理し、
ナノファイバー形態を確認するための tkinter ベースのデスクトップツールです。
プラグインランチャー、前処理パイプライン、プロファイル解析、ヒストグラム比較、
およびパイプライン出力バンドルを確認するファイバー追跡ビューアを提供します。

本ツールは、材料科学・高分子分野の研究者、とりわけセルロースをはじめとする
ナノファイバーを扱う研究者を主な対象とし、多数の AFM スキャンから一貫した
再現性のある形態計測値（長さ、高さ、端点数・キンク数、キンク角）を得ることを
目的としています。汎用の走査型プローブ顕微鏡ソフトウェアは画像レベルの可視化や
平坦化には適していますが、本ワークフローが対象とするファイバー中心のスケルトン
追跡、キンク検出、グループ間の統計比較は提供しません。AFM Nanofiber Analyzer は、
文書化された再現可能なパイプラインと安定したデータ形式でその隙間を埋めます。

## 概要

このアプリケーションは、GUI プラグインと再利用可能な解析モジュールを分離しています。

- `Main.py` は `guis/` 内の GUI プラグインを検出して起動します。
- `guis/` にはユーザーが操作する tkinter ツールが入っています。
- `lib/` には AFM 入出力、背景補正、二値化、スケルトン処理、キンク検出、
  ファイバーコンテナ、バンドル入出力、翻訳、共通 UI ヘルパーが入っています。

GUI01 は解析対象の入力ファイルごとに、圧縮された `.b2z` バンドルを 1 つ
出力します。後段の GUI は、多数の `.npy` サイドカーファイルではなく、
このバンドルを直接読み込みます。

## GUI ツール

| ファイル | ランチャー名 | 用途 |
|---|---|---|
| `guis/GUI01_Image_Preprocessor.py` | Image Preprocessor | AFM の `.txt` エクスポートまたは Gwyddion ネイティブ `.gwy` を読み込み、背景補正、二値化、細線化、キンク関連特徴抽出を行い、`.b2z` バンドルとパラメータ JSON を保存します。各ファイルは固有の物理走査範囲を持ち（入力から自動充填、またはスケール入力欄や CSV マニフェストでファイル単位に設定）、長さ計測を再現できるようバンドルへ保存します。 |
| `guis/GUI02_PlotProfiler.py` | Plot Profiler | 生データ、補正済みデータ、またはバンドル化された AFM 高さデータを読み込み、選択した線分に沿った高さプロファイルを対話的に抽出します。プロファイル距離を再現可能にするため、スケールは記録値（`.b2z`）、ヘッダ（テキスト/CSV）、またはチャンネル範囲（`.gwy`）の走査範囲で既定化します。 |
| `guis/GUI03_Fiber_Height_Histogram.py` | Fiber Height Histogram | ユーザー定義グループごとに、`.b2z` バンドル群の細線化ファイバー画素から高さ分布を比較します。 |
| `guis/GUI04_Tracking_fiber.py` | Fiber Tracker | `.b2z` バンドルを読み込み、追跡済み `Fiber` オブジェクトを再構築し、個別ファイバーの確認、図の出力、ファイバー統計量の CSV 出力を行います。 |

## 主なディレクトリ構成

```text
AFM_Nanofiber_Analyzer/
|-- Main.py
|-- cli.py
|-- babel.cfg
|-- build.py
|-- check.py
|-- prepare_translate_catalogs.py
|-- pyproject.toml
|-- requirements.txt
|-- requirements.lock.txt
|-- run_venv.bat
|-- run_conda.bat
|-- run_venv.sh
|-- run_conda.sh
|-- guis/
|   |-- GUI01_Image_Preprocessor.py
|   |-- GUI02_PlotProfiler.py
|   |-- GUI03_Fiber_Height_Histogram.py
|   |-- GUI04_Tracking_fiber.py
|   `-- __init__.py
|-- lib/
|   |-- afm_io.py
|   |-- bg_calibrator.py
|   |-- bg_calibrator_shimadzu.py
|   |-- blosc2_io.py
|   |-- bundle_schema.py
|   |-- fiber.py
|   |-- fiber_tracking_image.py
|   |-- gwy_io.py
|   |-- imp_tools.py
|   |-- kink_detector.py
|   |-- measure.py
|   |-- pipeline.py
|   |-- processed_image.py
|   |-- segmenter.py
|   |-- skeletonizer.py
|   |-- translator.py
|   |-- ui_tools.py
|   `-- __init__.py
|-- tests/
|-- locale/
|   |-- English/
|   |   `-- LC_MESSAGES/
|   |-- Japanese/
|   |   `-- LC_MESSAGES/
|   `-- Chinese/
|       `-- LC_MESSAGES/
|-- assets/
|   `-- afm_symbol.png
|-- README.md
`-- README.ja.md
```

Windows の `.bat` 補助スクリプトは、意図的に ASCII のみにしています。UTF-8 の
バッチファイルに日本語コメントを書くと、`cmd.exe` がシステム既定のコードページで
誤読し、文字化けした断片をコマンドとして実行することがあります。そのため、
日本語の保守メモは `README.ja.md` などの Markdown 文書に残します。

## 主なモジュール

| モジュール | 主な内容 |
|---|---|
| `lib/afm_io.py` | ヘッダー、列数、エンコーディングを自動検出する AFM テキスト / CSV ローダー。形式の明示指定とレイアウト整合検証に対応。 |
| `lib/bg_calibrator.py` | `inpaint`、`tophat`、`spline1d`、`spline2d` 背景補正方式を持つ `BGCalibrator`。 |
| `lib/bg_calibrator_shimadzu.py` | 従来名 `BG_Calibrator_shimadzu` を import 可能に保つ互換シム。 |
| `lib/blosc2_io.py` | Blosc2 配列保存と `.b2z` TreeStore バンドルの入出力ヘルパー。 |
| `lib/bundle_schema.py` | `.b2z` 契約の実行可能スキーマ。必須キー、配列形状、値域、単位、座標規約、形式バージョンを定義し、`validate_bundle` が書き込み時と読み込み時に強制する。 |
| `lib/fiber.py` | ファイバー形状、高さプロファイル、キンクインデックス、端点インデックスを保持する不変 `Fiber` dataclass。 |
| `lib/fiber_tracking_image.py` | GUI04 が GUI01 のバンドル出力からファイバーを再構築・追跡するための `FiberTrackingImage`。 |
| `lib/gwy_io.py` | ネイティブな複数チャンネル Gwyddion `.gwy` を遅延読み込みし、チャンネル選択、長さチャンネルの nm 換算、走査範囲抽出を行うローダー。 |
| `lib/imp_tools.py` | スケルトン形態処理、端点・分岐点検出、線追跡、経路距離変換のヘルパー。 |
| `lib/kink_detector.py` | 追跡されたスケルトン成分からキンク点を検出する `KinkDetector`。 |
| `lib/measure.py` | `.b2z` バンドルに対する GUI 非依存のファイバー計測。`measure_bundle`、ファイバーごとの `FiberStats`、スケルトン画素高さの収集、および GUI03/GUI04 と `cli.py` が共有する CSV 書き出し。 |
| `lib/pipeline.py` | `ProcParams` パラメータスキーマ、ステージ構築、および GUI01 と `cli.py` が共有する GUI 非依存のパイプライン駆動関数 `process_file`。`.b2z` 契約自体は `lib/bundle_schema.py` にあります。 |
| `lib/processed_image.py` | GUI01 の前処理パイプラインで使う `ProcessedImage` コンテナ。 |
| `lib/segmenter.py` | 背景補正済み AFM 画像からナノファイバー二値マスクを作成する `Segmenter`。 |
| `lib/skeletonizer.py` | 二値マスクを細線化し、枝刈りとスケルトン成分ラベル付けを行う `Skeletonizer`。 |
| `lib/translator.py` | gettext の言語選択ヘルパー。 |
| `lib/ui_tools.py` | GUI プラグインで共有する tkinter、matplotlib、ログ、ダイアログ、出力ヘルパー。 |

## 要件

- Python 3.10 以降
- Windows を主な対象環境としています

Python 依存関係は `requirements.txt` に記載されています。

```text
blosc2
gwyfile
lmfit
matplotlib>=3.10
numpy
opencv-python
pandas
Pillow
scikit-image
scipy
```

`check.py` はソースツリー内の import を走査して `requirements.txt` を再生成できます。
PyInstaller はスタンドアロンビルド専用のツールであり、配布物をビルドする場合に
別途インストールします。

環境を厳密に再現したい場合は、テストで検証済みの全パッケージバージョンを
記録した `requirements.lock.txt` を使用してください:

```powershell
python -m pip install -r requirements.lock.txt
```

lock ファイルのヘッダーには、スナップショットを検証した Python バージョンと
OS が記録されています。同じ環境で使用してください。ほかの対応 Python
バージョンや OS では、pip が互換 wheel を選べるよう `pyproject.toml` または
緩い `requirements.txt` からインストールします。

`check.py` には依存関係の整合性チェックとバージョン固定の機能もあります:

```powershell
python check.py            # 緩い requirements.txt を再生成(従来どおり)
python check.py --verify   # CI 向け検査: コードの import ⇔ pyproject ⇔ 実環境
python check.py --pin      # 全検査とテスト合格後に requirements.lock.txt を再固定
```

`--verify` は、コードで import している依存が `pyproject.toml` に宣言されて
いない場合(およびその逆)、走査された依存が未インストールの場合、`pip check`
がバージョン矛盾を報告した場合に、非ゼロで終了します。`--pin` は同じ検査に
加えて pytest スイートを実行し、すべて合格した場合のみ
`requirements.lock.txt` を書き換えます。これにより lock ファイルは常に
「テストで実際に検証されたバージョンの組み合わせ」を記録します。

## インストールと使い方

補助スクリプトを実行する前に、次のいずれかの Python 環境をインストールしてください。

- Python 3.10 以降: <https://www.python.org/>
- Anaconda または Miniconda:
  <https://www.anaconda.com/download> または
  <https://docs.conda.io/en/latest/miniconda.html>

### 推奨: 専用 venv を使う

リポジトリを clone し、プロジェクトルートへ移動してから、使用 OS に応じた
venv ランチャーを実行します。この方法は、AFM Nanofiber Analyzer の
依存関係を Anaconda などの既存環境から分離できるため推奨です。

```powershell
git clone https://github.com/FibrousBiomaterials/AFM_Nanofiber_Analyzer.git
cd AFM_Nanofiber_Analyzer
```

Windows:

```powershell
.\run_venv.bat
```

macOS または Linux:

```bash
chmod +x run_venv.sh
./run_venv.sh
```

`run_venv` は単一の冪等ランチャーです。初回実行時に `.venv` を作成し、`pip` を
更新したうえで、プロジェクトを編集可能モード(`pip install -e .`)でインストール
します。これにより依存関係はすべて単一の真実の源である `pyproject.toml` から
解決され、`afm-analyzer` / `afm-analyzer-cli` コマンドが登録されます。続けて
`Main.py` を起動し、2 回目以降は完了済みのセットアップを検出して再インストール
せずにその `.venv` から直接起動します。誤操作などで後から `.venv` が壊れた場合は、
次回起動時に自動修復します。インタプリタが失われていればクリーン再構築（壊れた
`.venv` を先に削除）し、セットアップマーカーだけが失われていれば再インストール
します。この判定はファイルの有無だけを見るため、正常時の起動は遅くなりません。
判定をすり抜ける軽微な破損があった場合は、`.venv` フォルダを削除してからランチャー
を再実行すればフル再構築されます。開発者やレビュアーは、ランチャーを使わずに
後述の編集可能インストールのコマンドで同じ環境を再現できます。バージョンを厳密に
固定したい場合は、代わりに `requirements.lock.txt` をインストールしてください
(上記「要件」を参照)。

### Anaconda または Miniconda

既存の Anaconda `base` 環境から直接起動する方法は推奨しません。
既にインストールされている NumPy、Matplotlib、SciPy、scikit-image などの
バイナリ依存パッケージが、このアプリケーションで必要なバージョンと競合する
可能性があります。

Anaconda または Miniconda を使う場合は、conda ランチャーを使ってください。
`run_venv` と同様に単一の冪等ランチャーで、初回実行時にプロジェクトフォルダ内の
`.conda-env/` へ専用の prefix 環境を作成してパッケージをインストールし、2 回目
以降は `base` を変更せずにその環境からアプリケーションを起動します。`run_venv`
と同様に自動修復し、環境のインタプリタが失われていれば `.conda-env` をクリーン
再構築、セットアップマーカーだけが失われていれば再インストールします。フル再構築
したい場合は `.conda-env` フォルダを削除してから再実行してください。

Windows:

```powershell
.\run_conda.bat
```

macOS または Linux:

```bash
chmod +x run_conda.sh
./run_conda.sh
```

### ローカライズ

GUI は、メニュー、ボタン、ダイアログ、ステータスメッセージ、ツールチップなどの
操作用 UI 文字列に Python の `gettext` を使います。翻訳カタログは `locale/` に
保存され、言語はランチャーから選択します。選択したカタログのディレクトリ名は
`.lang_preference` に保存され、保存済みの選択がない場合は英語が既定です。

グラフタイトル、軸ラベル、CSV ヘッダー、出力結果ラベル、データキー、単位など、
科学的再現性に関わる文字列は英語固定です。解析出力が言語設定によって変わらない
ようにするためです。

ユーザー向け文字列やプラグイン説明を変更した後に翻訳カタログを更新するには、
次を実行します。

```powershell
python prepare_translate_catalogs.py
```

このスクリプトは gettext メッセージの抽出、`PLUGIN_INFO["description"]` からの
ランチャー説明文の抽出、カタログ更新、obsolete な `#~` エントリの削除、および
`.mo` へのコンパイルを行います。`msgstr` は自動入力しません。古い obsolete
翻訳を参照用に残したい場合は、事前に Git commit またはバックアップを作成して
ください。

翻訳済み `msgstr` では、表示上の折り返し位置を調整する目的だけで、1文の途中に
`\n` を入れないでください。適切な折り返し位置は言語ごとに異なるため、折り返しは
UI 側に任せます。明示的な改行は、UI 上で意味のある段落区切りや改行が必要な場合
だけ使用してください。

`messages.po` を編集した後、配布前に `#, fuzzy` エントリを確認してください。
fuzzy エントリは Babel が近い既存訳を仮流用したものです。`msgid` と `msgstr` の
意味が一致しているか、`{path}`、`%s`、`%d`、`\n` などのプレースホルダーが
保持されているかを確認します。翻訳を確定した後にだけ `#, fuzzy` 行を削除します。
その後、翻訳カタログをコンパイルします。

```powershell
pybabel compile -d locale
```

コンパイル済みの `.mo` ファイルはバージョン管理されており、クローン直後でも
Babel をインストールせずに翻訳が機能します。`.po` を編集したら、再生成した
`.mo` も一緒にコミットしてください。`.mo` が `.po` より古い場合はテスト
スイートが失敗します。

空の `msgstr` が多い場合は、コーディングアシスタントに下訳を作らせられます。
カタログと言語を 1 つ指定し、次のように制約を与えます。

> `locale\<Language>\LC_MESSAGES\messages.po` にある、空の `msgstr ""` に対応する
> msgid の<言語>訳を記入してください。msgid、コメント行、既に入力済みの msgstr、
> ファイル構造、ヘッダー項目、`#~` で始まる obsolete entry は変更しないでください。
> `msgstr ""` の直後に翻訳済みの継続行がある項目は空ではないため、変更しないで
> ください。`#, fuzzy` が付いた項目は、意味、プレースホルダー（`{path}`、`%s`、
> `%d`）、改行を確認し、必要に応じて msgstr を修正したうえで `#, fuzzy` 行を
> 削除してください。プレースホルダーと必要な `\n` は保持し、msgid と同じ情報量で
> 訳してください。表示上の折り返し調整のためだけに `\n` を入れないでください。
> 判断に迷った項目は報告に列挙し、保守・点検担当者が GUI 上で妥当性を確認します。

AI による下訳は配布前に必ず GUI 上で確認し、その後で上記のとおりカタログを
コンパイルしてください。

### ソースから手動セットアップする場合

```powershell
git clone https://github.com/FibrousBiomaterials/AFM_Nanofiber_Analyzer.git
cd AFM_Nanofiber_Analyzer

py -3.12 -m venv .venv
.\.venv\Scripts\activate

python -m pip install -U pip
python -m pip install -r requirements.txt

python Main.py
```

### 開発用 editable インストール (pip)

開発用インストールのために `pyproject.toml` を同梱しています。editable モードで
インストールすると、全実行時依存が宣言どおりに解決され、コンソールコマンドが
2 つ登録されます。`[dev]` を付けると開発ツール (pytest、pytest-xdist、Babel、
ruff) も同時にインストールされます:

```powershell
python -m pip install -e ".[dev]"

afm-analyzer                          # ランチャー GUI (python Main.py と同じ)
afm-analyzer-cli process data\*.txt   # バッチパイプライン (python cli.py と同じ)
```

editable インストールはチェックアウトからの開発を対象としています。
エンドユーザー向け配布は引き続き後述の PyInstaller バンドルです。

### Windows 用スタンドアロンバンドルをビルドする

再現性のあるバンドルを作るには、テスト検証済みのロックファイルからビルド環境を
用意し、配布バイナリにテストスイート合格時と同じ依存バージョンを埋め込みます。

```powershell
python -m pip install -r requirements.lock.txt
```

ビルドスクリプトを実行する前に PyInstaller をインストールします（PyInstaller は
実行時依存ではなくロックファイルにも記録されません）。

```powershell
python -m pip install pyinstaller
```

```powershell
python build.py
```

ビルドスクリプトは `dist/Main/` に PyInstaller バンドルを生成し、ランチャーに
必要なプラグインとリソースフォルダをコピーします。配布時は `Main.exe` だけでなく、
`dist/Main/` フォルダ全体を配布してください。

## 対応入力フォーマット

`lib/afm_io.py` はテキスト/CSV 形式の高さデータを読み込み、ヘッダ行数・
列数・区切り文字・エンコーディング（UTF-8、cp932/Shift-JIS、保険として latin-1）
を自動判定するため、読み込み設定は不要です。次の 2 レイアウトを認識します
（多列形式の区切り文字はカンマ・空白/タブを自動判定）。

| レイアウト | 代表的な出力元 | 説明 |
|---|---|---|
| 多列形式 | 島津 SPM-9600 | カンマ区切りの値が並び、1 行 = 1 スキャンライン。非正方形スキャンにも対応。 |
| 多列形式 | Gwyddion「Export Text」 | 空白/タブ区切りの行列。`# Width` / `# Height` / `# Value units` のローカライズ済みコメントヘッダ付き。下記参照。 |
| 1 列形式 | Bruker NanoScope | テキストヘッダ行（例: `Height(nm)`）の後に 1 行 1 値が続く。値の総数が平方数である必要があり、`(s, s)` に reshape される。 |

高さ配列は nm 単位で返されます。認識可能な値単位ヘッダがないファイルは、値が
すでに nm であるとみなします。対応する長さ単位を宣言した Gwyddion Export Text
は nm へ換算します。物理スキャンサイズは入力に記録があれば、島津の
`SizeX` / `SizeY`、Gwyddion の `# Width` / `# Height`、またはネイティブ
`.gwy` チャンネルの範囲から読み取り、バンドルへ空間較正として保存します。
スキャンサイズが記録されていない入力（ヘッダを持たない Bruker NanoScope
エクスポート等）は、代わりに GUI／CLI から与えます。

代表入力は `testdata_tunicateCNF/` と `testdata_higherplantTOC/`（多列形式）、
`testdata_Bruker_txt/`（Bruker 1 列形式）、`testdata_Gwyddion_txt/`
（Gwyddion Export Text）、`testdata_Gwyddion_gwy/`（ネイティブ `.gwy`）に
同梱されています。

これらのサンプル AFM データセットは、本プロジェクトの著者らが実験で取得し、
再現可能な入力例として収録しています。著者らは、これらのデータセットを
再配布する権限を有することを確認しています。

### Gwyddion 経由でのその他機種の対応

上記レイアウトに該当しない機種（Asylum Research、JPK、Park Systems、Nanonis、
Olympus など）のファイルは、100 以上のネイティブ形式を読める無償の SPM ツール
[Gwyddion](http://gwyddion.net/) を介して対応します。方法は 2 通りあります。

**ネイティブ `.gwy` ファイル（推奨）。** Gwyddion 自身の `.gwy` ファイルは、手動の
変換工程なしに直接読み込めます。GUI01（フォルダ一括）、GUI02（Plot Profiler）、
`cli.py process` で、テキストスキャンと同じように `.gwy` を選ぶだけです。`.gwy`
コンテナは複数チャンネル（地形・位相・振幅など）を持ちますが、地形/高さチャンネルを
自動選択し、id またはタイトルで上書きもできます。複数チャンネルのファイルでは GUI02
にドロップダウンが現れ、`cli.py process` は `--channel <id|名前>` を受け付けます。
長さ単位を持つチャンネルは SI 単位から nm へ換算し、走査サイズはチャンネルの範囲から
読み取ります。長さ以外のチャンネルを明示選択した場合、値は元単位のまま通るため、
高さ nm を前提とするワークフローや表示には適しません。`.gwy` の読み込みには軽量で
純 Python の `gwyfile` パッケージ（宣言済み依存）が必要ですが、遅延 import のため
テキスト専用のワークフローでは読み込まれません。

**Export Text（`.txt`）。** あるいは Gwyddion でファイルを開き、**File > Save As** で
**「Export Text」**（プレーンテキストのデータ行列）を選ぶと、本ローダーはその `.txt`
を読み込みます。Gwyddion は行列を SI 単位（メートル）で、走査サイズと値の単位を記録
した小さなコメントヘッダ付きで出力し、本ローダーは両方を自動正規化します（高さを nm、
サイズを µm へ）。ヘッダのキー語は Gwyddion の UI 言語で書かれますが、英語
（`# Width`/`# Height`/`# Value units`）と日本語（`# 幅`/`# 高さ`/`# 値の単位`）の
両方を認識します（翻訳語ではなく値の構造で判定するため）。スキャンサイズを保持する
ため、エクスポート時は情報ヘッダを有効のままにしてください。無効の場合は GUI／CLI で
設定します。Bruker の `.spm` バイナリも同様に NanoScope からテキスト出力すれば、
上記の 1 列形式で読み込めます。

背景補正器（`lib/bg_calibrator.py` の `BGCalibrator`）はラインスキャン AFM
一般の背景補正を実装しており、両フォーマットに適用されます。本手法は島津
SPM-9600 のスキャンを対象に開発され、歴史的に `BG_Calibrator_shimadzu` と
命名されていました。従来の import パスとクラス名は互換シム経由で引き続き
利用できます。

## 解析パイプライン

```text
AFM text/CSV  --> afm_io.load_afm_text() --+
                                            |
Gwyddion .gwy --> gwy_io.load_gwy_image() --+
                                            v
                                  GUI01 / process_file
                                            |
                                            |-- BGCalibrator
                                            |-- Segmenter
                                            |-- Skeletonizer
                                            |-- KinkDetector
                                            v
<input_stem>.b2z      compressed TreeStore bundle
<input_stem>_param.json
        |
        +-- GUI02 Plot Profiler
        +-- GUI03 Fiber Height Histogram
        `-- GUI04 Fiber Tracker
```

前処理パラメータは生成される `<input_stem>_param.json` に保存されます。
背景補正、二値化、細線化、キンク検出の設定が含まれ、背景補正方式、しきい値、
枝刈り長、キンク角度しきい値などを記録します。

### コマンドラインでのバッチ処理

同じパイプラインを GUI なしで `cli.py` から実行できます。`cli.py` は GUI01 と
同一のコードパスである `lib.pipeline.process_file` を呼び出すため、同じ入力と
設定に対して CLI と GUI の解析配列・パラメータは一致します。`created_utc` など
実行ごとの来歴情報は当然異なります。スクリプトによるバッチ実行と再現可能な解析に
利用できます。

```powershell
# 既定の解析パラメータを編集可能な JSON テンプレートとして出力する。
python cli.py show-params > my_param.json

# 既定またはカスタマイズしたパラメータでファイルを処理する。
python cli.py process testdata_tunicateCNF\*.txt
python cli.py process scan.txt --params my_param.json --output-dir results --overwrite
```

`process` は入力 1 件につき `.b2z` バンドルと `_param.json` を 1 つずつ書き出し
ます。出力先は `--output-dir` を指定しない限り入力ファイルと同じ場所です。
出力が既に存在する入力は、`--overwrite` を付けない限りスキップされます。
`--save-original` を付けると、元の高さ画像が `original` キーとしてバンドルに
同梱されます。`--strict` を付けると、`--params` ファイル内の未知キーは無視
されずエラーになります。typo したキーが黙って既定値にフォールバックする事故を
防げます。`--format` は入力テキストのレイアウト（`multi-column` /
`single-column`）を明示指定します。自動判定がヘッダ内の数値ブロックに固定
されてしまう場合の回避手段で、確定したレイアウトは常にバンドルのメタデータ
（`input_format`）へ監査用に記録されます。`--scale-um` は物理スキャンサイズ
（X／幅、µm）をバンドルへ記録し、装置ヘッダから読み取った値を上書きします。
`--scale-y-um` で異なる Y（高さ）サイズを与えない限り両軸へ適用されます
（矩形スキャン対応）。省略時はヘッダのスキャンサイズがあればそれを使い、無ければ
スキャンサイズは保存されません。スキャンサイズはファイル単位で扱われるため、
異なるサイズのスキャンが混在するフォルダでも、バッチ共通の 1 値に頼らず正しく
処理できます。

### バンドルの検証

`.b2z` 契約（必須キー、配列形状、マスク値、キンク角の単位、形式バージョン）は
`lib/bundle_schema.py` がコードとして定義しています。パイプラインは保存前に
全バンドルを検証し、計測層は読み込み時に検証します。`validate` は同じ検査を
任意のタイミングで実行します:

```powershell
python cli.py validate results\*.b2z
```

各バンドルは `OK`（形式バージョン、画像サイズ、キンク数、来歴の有無を併記）
または `INVALID`（具体的な契約違反を列挙）として報告されます。いずれかの
バンドルが不適合のとき終了コードが非ゼロになるため、スクリプト化された
ワークフローのガードとして使えます。

### コマンドラインでのファイバー計測

GUI04 が表示するファイバー単位の計測値は `measure` で、GUI03 が使う
スケルトン画素高さは `heights` で取得できます。どちらも GUI と同じ解析層
`lib.measure` を使います。GUI04 で全件をフィルターなしに出力した CSV は、
同じバンドルとスケールに対する `measure` と同じ writer を使うためバイト単位で
一致します。高さフィルターが有効な GUI04 の出力は、意図どおりフィルター後の
ファイバー部分だけを含みます。

```powershell
# ファイバーごとの統計値（長さ、高さ中央値/最大値、端点数、キンク数）。
# --scale-um は任意です。省略時は各バンドルに記録された走査範囲を使います。
# 走査範囲が記録されていない古いバンドルでは明示的に指定してください。
# ピクセルサイズは軸ごとに解決されるため、矩形スキャンでは --scale-y-um を追加します。
python cli.py measure results\*.b2z
python cli.py measure results\*.b2z --scale-um 2.0
python cli.py measure results --scale-um 2.0 --output-dir stats
python cli.py measure results\*.b2z --scale-um 5.0 --scale-y-um 2.5

# スケルトン画素の高さ値（GUI03 の高さヒストグラムの元データ）。
python cli.py heights results --output heights.csv
```

`measure` はバンドル 1 件につき `<stem>_fibers.csv` を 1 つ書き出します。列は
`index`、`length_nm`、`height_median_nm`、`height_max_nm`、`ep_count`、
`kink_count`、`kink_angles_deg`（セミコロン区切りの度数値）です。`heights` は
バンドルごとの要約を表示し、`--output` を付けると縦持ち形式の CSV
（`bundle`、`height_nm`）を書き出して、外部ツールでの再グループ化・再ビニング
に利用できます。フォルダを引数に渡すと、フォルダ直下の全バンドルに展開され
ます。

### テストの実行

テストスイートは pytest を使用し、pytest-xdist による並列実行を前提としています
（`pyproject.toml` に `-n auto` が設定されているため、両パッケージが必要です。
前述の editable `[dev]` インストールでも両方導入されます）。単体テストは小さな
合成入力で実行され、統合テストと厳密回帰テストは同梱の実測スキャンを処理し、
出力を記録済みの基準値と比較します。

```powershell
python -m pip install pytest pytest-xdist
python -m pytest tests/
python -m pytest tests/ -m "not slow"   # 実測スキャンの統合テストをスキップ
```

## データ形式

現在の解析出力は、入力ファイルごとに 1 つの `.b2z` バンドルです。
バンドルは `lib/blosc2_io.py` が `blosc2.TreeStore` を使って書き込みます。
本プロジェクトのコードなしでもバンドルを読めるよう、以下にレイアウトを
文書化しています。また `cli.py export` で標準形式へ変換できます
（本節末尾を参照）。

GUI01 は次の配列キーを書き込みます。

| キー | shape | 内容 |
|---|---|---|
| `calibrated` | `(H, W)` | 背景補正済み AFM 高さ画像。浮動小数点、単位は nm。 |
| `binarized` | `(H, W)` | ナノファイバー二値マスク（非ゼロ = 繊維）。 |
| `skeletonized` | `(H, W)` | 細線化されたファイバー画像（非ゼロ = 中心線）。 |
| `bp` | `(H, W)` | 骨格上の分岐点マスク（非ゼロ = 分岐点）。 |
| `ep` | `(H, W)` | 骨格上の端点マスク（非ゼロ = 端点）。 |
| `kp` | `(2, N)` | キンク点のピクセル座標。座標規約は下記参照。 |
| `dp` | `(2, M)` | 分解点のピクセル座標。座標規約は下記参照。 |
| `ka` | `(N,)` | キンク内角（ラジアン）。`kp` の各列に 1 つ対応。 |
| `original` | `(H+1, W+1)` | 生の高さ画像（nm）。元データ保存を指定した場合のみ存在。 |

1 つのバンドル内の画像系配列はすべて同じ `(H, W)` を持ちます。背景補正器が
各軸 1 画素分トリミングするため、`H` と `W` は生入力サイズより 1 小さく
なります（`original` が存在する場合はそれより 1 小さい値です）。

座標規約: `kp[0]` と `dp[0]` が x（列）インデックス、`kp[1]` と `dp[1]` が
y（行）インデックスです。いずれも `calibrated` 画像上の 0 始まりのピクセル
位置で、例えば `calibrated[kp[1][i], kp[0][i]]` が i 番目のキンクの高さに
なります。

各バンドルはルートメタデータ（blosc2 `vlmeta`）も保持します。

| キー | 内容 |
|---|---|
| `params` | 解析パラメータ辞書。`<input_stem>_param.json` と同一内容。 |
| `version` | バンドル形式バージョン（現在は `"1.0"`）。 |
| `software_version` | バンドルを書き出したアプリケーションのリリース。 |
| `input_file` | 処理した入力ファイルのベース名。 |
| `input_sha256` | 入力ファイル内容の SHA-256 ダイジェスト。 |
| `created_utc` | 処理日時（ISO 8601、UTC）。 |
| `input_format` | 入力の解釈方法。テキスト入力は `kind`、`skiprows`、`n_cols`、`encoding`、ネイティブ `.gwy` は `kind="gwy"` と選択チャンネルの id、タイトル、値軸単位を記録。 |
| `spatial_calibration` | 物理スキャンサイズ。`scan_size_x_um`、`scan_size_y_um`、`source`（`input_header` / `manifest` / `manual`）。スキャンサイズが判明している場合のみ存在します。 |

来歴キー（`software_version`、`input_file`、`input_sha256`、`created_utc`、
`input_format`、`spatial_calibration`）は任意です。旧リリースが書いたバンドル
には存在しないため、読み取り側は必須として扱わないでください。
`spatial_calibration` が存在する場合、`measure` と GUI04 はスケールの既定値を
その記録値とするため、ファイバー長がバンドル単体で再現できます。

GUI01 は解析パラメータとして `<input_stem>_param.json` も書き込みます。
生 AFM 画像は、元の入力ファイルから再読み込みできるため、既定では
バンドル内に複製しません。

### バンドルを標準形式へエクスポートする

`.b2z` はプロジェクト固有のコンテナです。解析結果を本プロジェクト外で
利用する場合は、バンドルを標準形式へエクスポートします。

```powershell
python cli.py export results\*.b2z                # バンドルごとに 1 つの .npz
python cli.py export results\*.b2z --format csv   # 配列キーごとに 1 つの CSV
```

どちらの形式でも、バンドルのメタデータを保持する `<stem>_meta.json` が
併せて出力されます。NumPy `.npz` アーカイブは Python、MATLAB、R、Julia の
標準的なツールで読み込めます。

## GUI プラグインを追加する

1. `guis/` の下に Python ファイルを追加します。
2. ファイル上部付近にリテラルな `PLUGIN_INFO` 辞書を定義します。
3. 型付きの `main() -> None` エントリーポイントを定義します。

例:

```python
PLUGIN_INFO = {
    "name": "My Tool",
    "description": "Short launcher-facing description.",
}


class App(tk.Tk):
    ...


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
```

`Main.py` はプラグインファイルを自動検出します。ランチャーは
`ast.literal_eval()` で `PLUGIN_INFO` を読むため、値はプレーンなリテラルのままに
してください。プラグイン名は英語固定文字列として表示されます。プラグイン説明も
GUI ファイル内ではプレーンなリテラルですが、`Main.py` が AST 解析後に gettext に
通すため、locale カタログで翻訳できます。
`PLUGIN_INFO["description"]` には、ランチャー上の表示折り返しを調整する目的だけで
`\n` を入れないでください。説明文は自然な文章として保持し、折り返しはランチャー
UI 側に任せます。Python ソース上で文字列リテラルを複数行に分けることは、値に
実際の改行が入らない限り問題ありません。

`PLUGIN_INFO["description"]` を変更した場合は、対応する `msgid` を翻訳者が
利用できるように翻訳カタログを更新してください。

`PLUGIN_INFO` には任意の数値キー `order` も定義できます。ランチャーはこの値の
小さい順にボタンを並べ、`order` を持たないプラグインは指定済みのものの後ろに
ファイル名順で並びます。未知の `PLUGIN_INFO` キーは前方互換のため無視されます。
プラグイン契約 — リテラルな `PLUGIN_INFO`、非空の `name` / `description`
文字列、トップレベルの `main()`、`if __name__ == "__main__":` ガード、import
時に GUI を起動しないこと — は `tests/test_plugins.py` が強制するため、契約に
違反したプラグインはランチャー上で静かに劣化する代わりにテストで失敗します。

## 開発用ユーティリティ

- `check.py` は Python import を走査し、`requirements.txt` を書き出します。
  `--verify` はコードの import・`pyproject.toml`・実環境のずれを報告し、
  `--pin` は整合性検査とテストスイートの合格後に
  `requirements.lock.txt` を再生成します。
- `build.py` は import 検証、PyInstaller 用材料の収集、`Main.auto.spec` の作成、
  PyInstaller 実行、プロジェクトリソースフォルダのコピーを行います。
- `prepare_translate_catalogs.py` は gettext カタログを更新し、プラグイン説明を
  抽出し、obsolete な翻訳エントリを削除します。

## 既知の制限

- 認識可能な値単位ヘッダがないテキスト/CSV は nm とみなします。対応する長さ単位
  ヘッダを持つ Gwyddion Export Text は自動換算します。それ以外の単位なし
  エクスポートは読み込み前に変換してください。
- 1 列形式（Bruker NanoScope）のエクスポートは、データを正方形 `(s, s)` 画像へ
  reshape するため、高さ値の総数が平方数である必要があります。
- 長さ計測には、入力メタデータまたは GUI／CLI から物理スキャンサイズを与える
  必要があります。GUI01 は未設定のままでは処理を開始せず、`cli.py measure` は
  バンドル記録値も `--scale-um` も無い場合に明示的に失敗します。GUI02 と GUI04
  は較正未記録の古い入力では現在の編集可能なスケールを保持するため、値を確認して
  必要なら置き換えてください。
- 背景補正と既定パラメータは島津 SPM-9600 のスキャンを対象に開発・調整されて
  います。他の装置にも対応しますが、良好な二値化・細線化のためにパラメータの
  調整が必要になる場合があります。
- GUI ツールは動作する Tk 環境を必要とし、主に Windows で開発・テストされて
  います。CLI とライブラリはプラットフォーム非依存です。
- `.b2z` バンドルはプロジェクト固有のコンテナです。他の環境で結果を読む場合は
  `cli.py export`（NumPy `.npz` または CSV）を使ってください。

## 問い合わせとサポート

- **バグ報告・機能要望:**
  [issue tracker](https://github.com/FibrousBiomaterials/AFM_Nanofiber_Analyzer/issues)
  に issue を作成してください。
- **質問・使い方の相談:** 相談先は
  [CONTRIBUTING.md](CONTRIBUTING.md#getting-help-and-support) を参照してください。
- 問題を共有する際は、未公開の研究データを公開 issue に添付しないでください。
  読み込みの問題は、ファイル形式の説明だけでも多くの場合は再現できます。

## 引用

研究でこのソフトウェアを使用した場合は、次のように引用してください。

```bibtex
@software{afm_nanofiber_analyzer,
  author    = {Kiyoto, Shingo and Mayumi, Keita and Ito, Tomoki and Kobayashi, Kayoko},
  title     = {AFM Nanofiber Analyzer},
  year      = {2026},
  version   = {1.0.0},
  url       = {https://github.com/FibrousBiomaterials/AFM_Nanofiber_Analyzer}
}
```

### 関連論文

本ツールキットが基づく原型スクリプトは、著者らによる以下の研究で使用されました。
これらは本ツールキットが対象とする AFM ナノファイバー解析の例でもあります。

- Ito, T., Daicho, K., Fujisawa, S., Saito, T., & Kobayashi, K. (2022).
  Atomic-scale dents on cellulose nanofibers: the origin of diverse defects in
  sustainable fibrillar materials. *Nanoscale Horizons*, 7, 1186–1191.
  <https://doi.org/10.1039/D2NH00355D>
- Ito, T., Daicho, K., Fujisawa, S., Saito, T., & Kobayashi, K. (2025).
  Defectless and uniform single-crystallite dispersions of sustainable wood
  nanocellulose with a regulated right-handed twist periodicity.
  *Nano Letters*, 25, 6085–6091.
  <https://doi.org/10.1021/acs.nanolett.4c06483>
- Mayumi, K., Ito, T., Kiyoto, S., Wada, M., & Kobayashi, K. (2026).
  Cross-sectional dimensions of tunicate nanocelluloses: broad size
  distribution and their origins. *Cellulose*, 33, 3903–3914.
  <https://doi.org/10.1007/s10570-026-07059-3>

## 著者

| 名前 | 貢献 |
|---|---|
| Shingo Kiyoto | パッケージング、リリース準備、ドキュメント、機能実装、検証 |
| Tomoki Ito | 中核実装（主担当） |
| Keita Mayumi | 機能実装、検証 |
| Kayoko Kobayashi | 着想、ソフトウェア初期実装 |

中核となる原型コードは Tomoki Ito が実装し、現在のソフトウェアはそれを基盤と
しています。

## ライセンス

このプロジェクトは MIT License の下で公開されています。詳細は [LICENSE](LICENSE) を
参照してください。

概要画像 `assets/afm_symbol.png` は ChatGPT（OpenAI）を使用して生成しました。

## 謝辞

背景補正ワークフローには、Shimadzu SPM-9600 AFM データ向けに開発された手法が
含まれています。関連する AFM 画像処理の取り組みは
<https://github.com/terio0819/Image-processing-of-AFM-image> で公開されています。
