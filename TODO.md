# GitHub・Zenodo・JOSS 投稿に向けたドキュメント TODO

AFM Nanofiber Analyzer を GitHub で公開し、Zenodo でアーカイブし、JOSS
投稿を目指すために用意すべきドキュメントを整理する。

この TODO は、現時点のリポジトリを見た暫定判定を含む（最終更新: 2026-06-22）。

- `あり`: ファイルは存在する。
- `要修正`: ファイルは存在するが、公開・JOSS・Zenodo 向けには内容の修正が必要。
- `未作成`: ファイルが見当たらないため新規作成が必要。
- `要確認`: ファイルはあるが、内容を詳しく確認して公開可否や十分性を判断する必要がある。

## 0. 進捗サマリ（2026-06-22 時点）

初版作成時点から進んだ主な項目:

- `CONTRIBUTING.md`、`README.ja.md` を作成済み。
- JOSS paper を作成済み。配置はリポジトリ直下の `paper.md` / `paper.bib`
  （`paper/` サブフォルダではない）。`Summary` と `Statement of need` を含む。
- CI を `.github/workflows/test.yml` として作成済み（push / pull request で
  Ruff lint + Windows/Linux × Python 新旧マトリクスの pytest を実行）。
- `cli.py` による GUI 非依存のバッチ処理（`process` / `validate` / `measure`
  / `heights` / `export` / `show-params`）を追加済み。README に使用例あり。
- `pyproject.toml` を追加し、editable install（`pip install -e .`）と `[dev]`
  追加依存（pytest, pytest-xdist, Babel, ruff）を定義済み。
- `requirements.lock.txt` を追加し、テスト検証済みの固定バージョンスナップ
  ショットを提供。`check.py --pin` で再ロックする運用を確立。
- `docs/maintainer-notes.ja.md`、`docs/docstring-templates.md` を作成済み。
- 公開前整理対象だった `取説.txt`、`AFM_Nanofiber_Analyzer_日本語仕様書.md`、
  `開発者メモ.md`、`buildold.py` はリポジトリから除去済み。`.lang_preference`、
  `.claude/`、`__pycache__/` は `.gitignore` で除外済み。
- `locale/` は `English` / `Japanese` / `Chinese` の構成で確定。

未着手の主な残課題: README/CITATION のプレースホルダー解消、`CHANGELOG.md`、
`CODE_OF_CONDUCT.md`、`SECURITY.md`、`SUPPORT.md`、`.zenodo.json`、
リリース手順書、`examples/` 整備、各種 `docs/` ユーザー・開発者ガイド。

## 1. 最優先で用意すべき公開用ドキュメント

| 文書 | 現状 | 目的 |
|---|---|---|
| `README.md` | あり・要修正 | GitHub の入口。ユーザー、レビュアー、共同研究者が最初に読む文書。 |
| `README.ja.md` | あり | 日本語ユーザー向けの README。英語版と同期する。 |
| `LICENSE` | あり | 利用・改変・再配布条件を明確にする法的文書。JOSS で必須。著者4名を著作権者として併記。 |
| `CITATION.cff` | あり・要修正 | GitHub の引用ボタン、Zenodo、JOSS 後の引用情報に使うメタデータ。 |
| `requirements.txt` | あり | Python 依存関係の一覧（緩い指定）。固定版は `requirements.lock.txt`。 |
| `requirements.lock.txt` | あり | テスト検証済みの固定バージョンスナップショット。再現インストール用。 |
| `pyproject.toml` | あり | パッケージメタデータ、editable install、`[dev]` 依存、ruff/pytest 設定。 |
| `.gitignore` | あり | 生成物、個人環境、解析一時ファイル、機密ファイルの混入防止。 |

### `README.md` に必要な内容

- [x] ソフトウェアの目的を冒頭で簡潔に説明する。
- [x] AFM ナノファイバー解析で何を自動化・支援するソフトなのかを書く。
- [ ] 対象ユーザーを明示する（README 本文では設計説明が中心で、対象ユーザー
      の記述が薄い。`paper.md` の Statement of need を要約して補う）。
- [x] 主な機能を書く。
      背景補正、セグメンテーション、スケルトン化、キンク検出、プロファイル抽出、高さ分布比較、fiber tracking。
- [x] 対応入力形式を書く（Supported Input Formats 節）。
- [x] 主な出力を書く（Data Format 節: `.b2z`、`_param.json`、CSV、図エクスポート）。
- [x] インストール手順を書く（Installation and Usage 節: venv / conda / Anaconda）。
- [x] 起動方法を書く。
- [x] 最小チュートリアルを書く（CLI バッチ処理 + 起動手順）。
- [x] サンプルデータを使った実行例を書く（`testdata_tunicateCNF` などを使用）。
- [x] `.b2z` バンドルのデータ契約を書く（Data Format 節）。
- [x] GUI01、GUI02、GUI03、GUI04 の役割を説明する（GUI Tools 節）。
- [x] テスト実行方法を書く（Running tests 節）。
- [ ] 既知の制限を書く（明示的な節がまだない）。
- [x] 引用方法を書く（Citation 節）。
- [x] ライセンスを書く（License 節）。
- [ ] 問い合わせ先または Issue の使い方を書く（README 本文には窓口節がない。
      `CONTRIBUTING.md` には記載済みなので、README からリンクする）。

#### 現時点で不十分な点

- [ ] Zenodo DOI badge が `10.5281/zenodo.xxxxxxx` のプレースホルダーのまま（README 冒頭）。
- [ ] clone URL の GitHub URL が `<your-username>` のプレースホルダーのまま（2 か所）。
- [x] Citation の BibTeX 著者名を正式名に更新済み（`CITATION.cff` と一致、README.md / README.ja.md 両方）。
- [x] Authors 欄の略称を正式名に更新済み（README.md / README.ja.md 両方）。
      併せて README.ja.md の BibTeX の `year` を 2026、`url` を実 URL に同期。
- [x] テスト実行方法（Running tests 節を追加済み）。
- [ ] `Statement of need` 相当の説明は `paper.md` に作成済みだが、README 本文は
      設計説明が中心。README にも簡潔な必要性の説明を補うか検討する。
- [x] `locale/` の構造説明が実際の `English` / `Japanese` / `Chinese` と一致。

### `LICENSE` に必要な内容

- [x] OSI 承認ライセンスを使う（MIT）。
- [x] ライセンス本文を改変せずに入れる。
- [x] 著作権者名を書く。
- [x] 年を書く（2026）。
- [x] 共同著作の著作権者表記を確定（著者4名を併記）。

#### 現時点の状況

- [x] 著作権者表記を整理済み（`Copyright (c) 2026 Shingo Kiyoto, Keita Mayumi, Tomoki Ito, Kayoko Kobayashi`）。
- [x] 著者4名を著作権者として併記し、`pyproject.toml` も 4 名（CITATION 順）に統一。
- [x] README / CITATION.cff / `pyproject.toml` / LICENSE の著者情報を一致させた
      （`paper.md` の著者・ORCID は提出前に再確認）。

### `CITATION.cff` に必要な内容

- [x] `cff-version` を書く（`1.2.0`）。
- [x] `message` を書く。
- [x] `title` を書く。
- [x] `abstract` を書く。
- [x] `authors` を正式名、所属、ORCID 付きで書く。
- [x] `version` を書く（`1.0.0`、`pyproject.toml` と一致）。
- [ ] `date-released` を実際のリリース日に合わせる。
- [x] `repository-code` を実際の GitHub URL にする。
- [ ] Zenodo DOI が発行されたら `doi` を更新する。
- [x] `license` を `LICENSE` と一致させる（MIT）。
- [x] 関連ソフトウェアを `references` に入れる（先行 AFM 画像処理リポジトリ）。

#### 現時点で不十分な点

- [ ] `url:` フィールドが `<your-username>` のプレースホルダーのまま
      （`repository-code:` は実 URL に更新済み）。
- [ ] `doi: "10.5281/zenodo.xxxxxxx"` が Zenodo 発行前のプレースホルダーのまま。
- [ ] `date-released: "2026-01-01"` が仮の日付。実リリース日に直す。
- [ ] 著者順、所属、ORCID が最終版として正しいか確認する。
- [ ] Zenodo 連携前に、日本語 YAML コメントがパーサーで問題にならないか確認する
      （YAML 仕様上コメントは許容されるが、連携時に念のため確認）。

### `requirements.txt` / 依存関係に必要な内容

- [x] 実行に必要な依存関係を書く（`requirements.txt`、`pyproject.toml` の `dependencies`）。
- [x] 開発用・ビルド用依存関係を分ける（`pyproject.toml` の `[dev]` extra に集約）。
- [x] 再現可能な固定バージョンを提供する（`requirements.lock.txt`）。
- [x] README のインストール手順と一致させる（緩い `requirements.txt` と lock の両方を案内）。
- [x] CI で同じ依存関係を使う（`.github/workflows/test.yml`）。

#### 現時点で不十分な点

- [x] 固定バージョンは `requirements.lock.txt` で提供（`requirements.txt` は意図的に緩い指定）。
- [x] 未確認の `numpy<2` 制約を外し、`requirements.txt` は制約なしの `numpy` に戻した。
- [x] `pyinstaller` はビルド時に別途インストールする方針を README に明記済み（実行時依存に含めない）。
- [x] `check.py` の運用を確立（`python check.py` で `requirements.txt` 再生成、
      `--verify` で整合チェック、`--pin` で `requirements.lock.txt` 再ロック）。

### `.gitignore` に必要な内容

- [x] Python キャッシュを除外する（`__pycache__/`、`*.py[cod]`）。
- [x] 仮想環境を除外する（`.venv/`、`venv/`、`.conda-env/` など）。
- [x] PyInstaller 生成物を除外する（`build/`、`dist/`、`*.spec`）。
- [x] ローカル設定ファイルを除外する（`.claude/`、`.lang_preference`、`guis/afmpp_settings.json`）。
- [x] 解析の一時出力や巨大出力を除外する（`*.b2z`、`*_param.json`、`*.npy`、`*.json`）。
- [x] 機密データや大容量サンプルを管理する（`Bruker_testdata/*` を除外し代表 1 ファイルのみ追跡）。

#### 確認済みの点

- [x] `__pycache__/` と `.pyc` は `.gitignore` で除外済み（追跡されていない）。
- [x] `.lang_preference` と `.claude/` は `.gitignore` で除外済み。
- [x] 解析出力（`.b2z` / `_param.json` / `.npy` / `.json`）は除外済み。
      golden baseline（`tests/strict_regression_golden.json`）と翻訳 `.mo` は例外で追跡。

## 2. JOSS・オープンソース公開で強く推奨される文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `CONTRIBUTING.md` | あり | Issue、Pull Request、開発環境、テスト、コーディング方針を書く。 |
| `CHANGELOG.md` | 未作成 | リリースごとの変更履歴を記録する。 |
| `CODE_OF_CONDUCT.md` | 未作成 | 公開プロジェクトとしての行動規範を書く。 |
| `SECURITY.md` | 未作成 | 脆弱性や安全性問題の報告先を書く。 |
| `SUPPORT.md` | 未作成 | 質問、バグ報告、研究利用相談の窓口を整理する。 |

### `CONTRIBUTING.md` に必要な内容

- [x] Issue の立て方を書く（Reporting bugs 節）。
- [x] バグ報告に必要な情報を書く（OS、Python バージョン、入力形式、再現手順など）。
- [x] 機能提案の方法を書く（Requesting features 節）。
- [x] 開発環境の作り方を書く（Development setup 節）。
- [x] テストの実行方法を書く（Running the tests 節）。
- [x] Pull Request の流れを書く（Submitting a pull request 節）。
- [ ] GUI プラグイン追加時のルールを書く（詳細は `AGENTS.md` §7。CONTRIBUTING
      から要点参照を補えるか確認）。
- [ ] `.b2z` バンドル契約を壊す変更では事前相談が必要であることを書く
      （`AGENTS.md` §8 に記載。CONTRIBUTING でも触れるか確認）。
- [x] コメント・docstring の英日方針を書く（Coding standards 節 / `AGENTS.md` 参照）。
- [ ] UI 文字列と scientific/reporting strings の翻訳方針を書く（要確認）。

### `CHANGELOG.md` に必要な内容

- [ ] バージョン番号を書く。
- [ ] リリース日を書く。
- [ ] `Added`, `Changed`, `Fixed`, `Removed` などの分類で変更を書く。
- [ ] 解析結果に影響する変更を明記する。
- [ ] `.b2z` 形式に影響する変更を明記する。
- [ ] GUI 操作や出力形式の変更を明記する。

#### 未作成のため必要な理由

- Zenodo で release DOI を作るとき、何が保存された版なのか説明しやすくなる。
- JOSS レビュー中の変更履歴を追いやすくなる。
- 解析結果の再現性に関わる変更を利用者が確認できる。

### `CODE_OF_CONDUCT.md` に必要な内容

- [ ] 参加者に期待する行動を書く。
- [ ] 許容されない行動を書く。
- [ ] 問題報告先を書く。
- [ ] 適用範囲を書く。
- [ ] 対応方針を書く。

#### 未作成のため必要な理由

- 必須ではないが、公開研究ソフトとして外部参加者を受け入れる姿勢を示せる。
- Contributor Covenant などの標準文面を使うと整備しやすい。

### `SECURITY.md` に必要な内容

- [ ] 脆弱性や危険な不具合の報告先を書く。
- [ ] 公開 Issue に書くべきでない情報を説明する。
- [ ] 対応対象バージョンを書く。
- [ ] 解析ファイルを共有するときの注意を書く。

#### 未作成のため必要な理由

- GUI アプリでも、ファイル読み込みや圧縮バンドルを扱うため、安全性報告の窓口を用意しておくとよい。
- 未公開 AFM データを誤って公開 Issue に添付しないよう誘導できる。

### `SUPPORT.md` に必要な内容

- [ ] バグ報告は GitHub Issues に誘導する。
- [ ] 使い方の質問の窓口を書く。
- [ ] 研究データを含むファイルを公開 Issue に添付しないよう注意する。
- [ ] 回答できる範囲とできない範囲を書く。

#### 未作成のため必要な理由

- JOSS 公開後にユーザーがどこへ相談すればよいか明確になる。
- 研究室内連絡と公開 GitHub Issue を分けられる。
- `CONTRIBUTING.md` の "Getting help and support" 節と内容が重複しないよう調整する。

## 3. JOSS 投稿に必要な論文関連文書

JOSS paper はリポジトリ直下に配置済み（`paper/` サブフォルダではない点に注意）。

| 文書 | 現状 | 目的 |
|---|---|---|
| `paper.md` | あり・要確認 | JOSS 投稿本文。`Summary` と `Statement of need` を含む。 |
| `paper.bib` | あり・要確認 | JOSS paper で引用する文献リスト。 |
| 図ファイル | 未作成 | 必要に応じて JOSS paper 用の図を追加する。 |

### `paper.md` に必要な内容

- [x] YAML ヘッダーを書く。
- [x] タイトルを書く。
- [x] 著者、所属、ORCID を書く（YAML ヘッダー内）。
- [x] `Summary` を書く。
- [x] `Statement of need` を書く。
- [ ] 主な機能の説明が十分か確認する。
- [ ] 対象データとワークフローの説明が十分か確認する。
- [ ] 既存ツールとの関係の説明が十分か確認する。
- [ ] 研究上の利用場面の説明が十分か確認する。
- [x] 謝辞を書く（Acknowledgements 節）。
- [ ] AI 支援を使った場合は、必要に応じて開示を書く（`AGENTS.md` §5 参照）。
- [x] `paper.bib` の文献を引用する（References 節）。

#### 確認すべき点

- JOSS 提出前に著者・所属・ORCID が `CITATION.cff` と一致しているか確認する。
- 図が必要なら追加し、`paper.md` から参照する。

### `paper.bib` に必要な内容

- [ ] AFM 関連の基礎文献が十分か確認する。
- [ ] ナノファイバー解析に関する文献が十分か確認する。
- [ ] 画像解析・スケルトン化・セグメンテーション関連文献が十分か確認する。
- [ ] NumPy、SciPy、scikit-image、Matplotlib など主要ライブラリの引用が入っているか確認する。
- [ ] 関連する先行ソフトウェアの引用が入っているか確認する。

## 4. ユーザー向け操作文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `README.ja.md` | あり | 日本語ユーザー向けの導入・操作説明（英語 README と同期）。 |
| `docs/installation.md` | 未作成 | インストール手順を README から分離する場合に使う。 |
| `docs/quickstart.md` | 未作成 | 最短で解析を試す手順を書く。 |
| `docs/gui01_preprocessor.md` | 未作成 | GUI01 の入力、パラメータ、出力を詳しく説明する。 |
| `docs/gui02_plot_profiler.md` | 未作成 | GUI02 のプロファイル抽出操作を説明する。 |
| `docs/gui03_height_histogram.md` | 未作成 | GUI03 のグループ比較と出力を説明する。 |
| `docs/gui04_fiber_tracking.md` | 未作成 | GUI04 の fiber tracking、CSV export、図保存を説明する。 |
| `docs/troubleshooting.md` | 未作成 | よくあるエラーと対処を書く。 |

`README.ja.md` 作成により、当初候補だった `取説.txt` の整理は不要になった
（`取説.txt` はリポジトリから除去済み）。下記の `docs/` 配下のガイドは、
README が長くなりすぎた場合や JOSS レビュアー向けに詳細を分離したい場合に
作成する。現状は README / README.ja に主要手順がまとまっている。

### `docs/installation.md` に必要な内容

- [ ] Windows の venv 手順を書く。
- [ ] macOS/Linux の venv 手順を書く。
- [ ] conda 環境の手順を書く。
- [ ] 推奨しない手順を書く（例: Anaconda base 環境への直接インストール）。
- [ ] Python バージョンを書く。
- [ ] 依存関係のトラブルシューティングを書く。

（注: 現状これらは README の Installation and Usage 節に統合済み。独立文書化は任意。）

### `docs/quickstart.md` に必要な内容

- [ ] サンプルデータの場所を書く（現状 `testdata_tunicateCNF` などがリポジトリにある）。
- [ ] GUI01 で前処理する手順を書く。
- [ ] 生成される `.b2z` と `_param.json` を説明する。
- [ ] GUI02、GUI03、GUI04 でその出力を読む手順を書く。
- [ ] 期待される結果を図または文章で示す。

#### 必要性

- 初回ユーザーと JOSS レビュアーが、数分で動作確認できるようになる。
- 現状 README には CLI のサンプル実行例はあるが、GUI を使った再現可能な
  walkthrough は薄い。

### GUI 別マニュアルに必要な内容

- [ ] 入力ファイル形式を書く。
- [ ] 操作手順を書く。
- [ ] パラメータの意味を書く。
- [ ] 出力ファイルを書く。
- [ ] エラー時の確認点を書く。
- [ ] 解析結果の解釈で注意すべき点を書く。

### `docs/troubleshooting.md` に必要な内容

- [ ] Python が見つからない場合の対処を書く。
- [ ] 依存関係インストール失敗時の対処を書く。
- [ ] Tkinter が起動しない場合の対処を書く。
- [ ] AFM text/CSV が読めない場合の対処を書く。
- [ ] 文字化けや encoding 問題の対処を書く。
- [ ] `.b2z` が読めない場合の対処を書く。
- [ ] 解析結果が空になる場合の確認点を書く。

## 5. 開発者・保守者向け文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `docs/maintainer-notes.ja.md` | あり | 日本語の保守者向けメモ。 |
| `docs/docstring-templates.md` | あり | docstring テンプレート（`AGENTS.md` §3.4 から参照）。 |
| `AGENTS.md` | あり | AI 編集エージェント向けの正準指示ファイル。設計・データ契約・翻訳方針も集約。 |
| `CLAUDE.md` | あり | `AGENTS.md` を import する薄いポインタ。 |
| `docs/developer_guide.md` | 未作成 | 開発環境、設計、テスト、リリース作業を書く。 |
| `docs/data_contract.md` | 未作成（任意） | `.b2z` 契約。コードの `lib/bundle_schema.py` が正準。 |
| `docs/plugin_api.md` | 未作成（任意） | GUI プラグインの作り方。`AGENTS.md` §7 に既出。 |
| `docs/localization.md` | 未作成（任意） | gettext と翻訳対象文字列のルール。`AGENTS.md` §8.8 に既出。 |

設計・データ契約・プラグイン規約・翻訳方針は現状 `AGENTS.md` に集約されている。
`docs/` 配下の開発者ガイドは、外部貢献者向けに `AGENTS.md` から要点を抜き出して
公開用に整える場合に作成する（`AGENTS.md` は AI 編集エージェント向け指示であり、
JOSS ソフトウェア提出物の一部ではない点に注意）。

### `docs/developer_guide.md` に必要な内容

- [ ] 開発環境の作り方を書く。
- [ ] ディレクトリ構造を書く。
- [ ] `Main.py`, `guis/`, `lib/`, `locale/`, `assets/` の役割を書く。
- [ ] テストの追加方法を書く。
- [ ] `check.py` の使い方を書く。
- [ ] `build.py` の使い方を書く。
- [ ] リリース前チェックを書く。
- [ ] PyInstaller ビルドの注意点を書く。

### `docs/data_contract.md` に必要な内容（任意）

- `.b2z` の実行契約はコードの `lib/bundle_schema.py` が正準（`AGENTS.md` §8.2）。
- 文書化する場合は、コードを source of truth として要点を抜粋し、二重管理に
  ならないようにする。

### 既存の AI 指示ファイル・保守メモの扱い

- [x] 公開前整理対象だった `AFM_Nanofiber_Analyzer_日本語仕様書.md` と
      `開発者メモ.md` はリポジトリから除去済み。
- [x] `AGENTS.md` と `CLAUDE.md` は公開リポジトリに含める方針で確定
      （`.gitignore` にも「intentionally version-controlled」と明記）。

## 6. リリース・Zenodo 関連文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `.zenodo.json` | 未作成 | Zenodo に渡す詳細メタデータを指定する。 |
| `RELEASE.md` または `docs/release_process.md` | 未作成 | タグ作成、GitHub release、Zenodo DOI 更新手順を書く。 |
| GitHub Release notes | 未作成 | 各リリースの変更内容を GitHub 上で説明する。 |

### `.zenodo.json` に必要な内容

- [ ] title を書く。
- [ ] upload_type を書く。
- [ ] creators を正式名、所属、ORCID 付きで書く。
- [ ] description を書く。
- [ ] license を書く。
- [ ] keywords を書く。
- [ ] related_identifiers を書く。
- [ ] communities を使う場合は確認する。

#### 必要性

- `CITATION.cff` だけで十分な場合は必須ではない。
- ただし、Zenodo 側の著者・所属・キーワード・関連論文を安定して管理したい場合は有用。

### `docs/release_process.md` に必要な内容

- [ ] リリース前チェックを書く。
- [ ] バージョン番号の決め方を書く（`pyproject.toml` と `CITATION.cff` の `version` を一致させる）。
- [ ] `CITATION.cff` の更新手順を書く。
- [ ] `CHANGELOG.md` の更新手順を書く。
- [ ] Git tag の作り方を書く。
- [ ] GitHub Release の作り方を書く。
- [ ] Zenodo DOI の確認手順を書く。
- [ ] README の DOI badge 更新手順を書く。
- [ ] JOSS レビュー後の最終リリース手順を書く。

## 7. テスト・CI 関連文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `.github/workflows/test.yml` | あり | GitHub Actions で Ruff lint + pytest を実行する。 |
| `tests/` | あり | pytest スイート（afm_io, pipeline, measure, bundle_schema, export, 翻訳, 回帰など）。 |
| `tests/README.md` | 未作成 | テストデータ、fixture、実行範囲を説明する。 |
| `docs/testing.md` | 未作成（任意） | テスト方針と手動確認項目を書く。 |

### `.github/workflows/test.yml` の状況

- [x] push と pull request で実行する。
- [x] Python バージョンを指定する（新旧 2 バージョンのマトリクス）。
- [x] 依存関係をインストールする。
- [x] Ruff による lint を実行する。
- [x] `pytest` を実行する（Windows / Linux マトリクス）。
- [x] GUI を直接起動しない範囲でテストする。
- [ ] `check.py --verify`（import 整合チェック）を CI に組み込むか検討する。

### `tests/README.md` / `docs/testing.md` に必要な内容

- [ ] 自動テストの実行方法を書く（README / CONTRIBUTING に既出。テスト側にも要約があると親切）。
- [ ] GUI の手動確認手順を書く。
- [ ] サンプルデータ（`testdata_*`、`Bruker_testdata`）の扱いを書く。
- [ ] `slow` マーカー付き統合テストの位置づけを書く。
- [ ] どの機能が自動テスト対象か / 手動確認対象かを書く。

## 8. サンプルデータ・チュートリアル関連文書

リポジトリには既にサンプルスキャンがある（`testdata_tunicateCNF`、
`testdata_higherplantTOC`、`Bruker_testdata`）。ただし配布条件や実行手順を
まとめた `examples/` 構成は未整備。

| 文書 | 現状 | 目的 |
|---|---|---|
| `examples/README.md` | 未作成 | サンプルデータと実行例を説明する。 |
| `examples/` | 未作成 | 再配布可能な小さな入力データや期待出力を整理して置く。 |
| `docs/example_workflow.md` | 未作成 | 論文レビュアー向けの再現可能な解析例を書く。 |

### `examples/README.md` に必要な内容

- [ ] サンプルデータの出典を書く。
- [ ] ライセンスまたは再配布条件を書く。
- [ ] ファイル形式を書く。
- [ ] GUI01 から GUI04 までの実行手順を書く。
- [ ] 期待される出力を書く。
- [ ] サンプルデータが実験的結論を主張するものではなく、動作確認用であることを書く。

#### 必要性

- 既に `testdata_*` があるため、出典・再配布条件・実行手順を `examples/README.md`
  などに明文化すれば JOSS レビュアーが動かしやすくなる。

## 9. 公開前に整理すべき既存ファイル

| ファイル | 現状 | 対応方針 |
|---|---|---|
| `取説.txt` | 除去済み | `README.ja.md` を作成済み。対応完了。 |
| `AFM_Nanofiber_Analyzer_日本語仕様書.md` | 除去済み | リポジトリから除去済み。対応完了。 |
| `開発者メモ.md` | 除去済み | リポジトリから除去済み。対応完了。 |
| `buildold.py` | 除去済み | リポジトリから除去済み（`.gitignore` にも記載）。対応完了。 |
| `CLAUDE.md` | あり | 公開する方針で確定（`AGENTS.md` を import する薄いポインタ）。 |
| `AGENTS.md` | あり | 公開する方針で確定（AI 編集エージェント向け正準指示）。 |
| `.claude/` | 除外済み | `.gitignore` で除外済み。 |
| `.lang_preference` | 除外済み | `.gitignore` で除外済み（個人設定）。 |
| `__pycache__/` | 除外済み | `.gitignore` で除外済み。 |

## 10. 残作業の推奨順

1. README と CITATION.cff のプレースホルダーを解消する
   （DOI、`<your-username>` URL、BibTeX 著者名、README Authors 略称）。
2. LICENSE の著作権者表記と共同著作者の扱いを確定し、README / CITATION /
   `pyproject.toml` / `paper.md` の著者情報を一致させる。
3. `CHANGELOG.md` を作成する。
4. `examples/README.md` を作成し、既存 `testdata_*` の出典・再配布条件・
   実行手順を明文化する。
5. README に「既知の制限」と「問い合わせ先 / Issue の使い方」を補い、
   `CONTRIBUTING.md` へリンクする。
6. `CODE_OF_CONDUCT.md`、`SECURITY.md`、`SUPPORT.md` を作成する（標準文面ベース）。
7. JOSS 提出前に `paper.md` / `paper.bib` の内容（既存ツールとの関係、文献の
   網羅性、AI 支援の開示）を確認する。
8. 必要に応じて `.zenodo.json` と `docs/release_process.md` を作成する。
9. GitHub 公開後、初回 release と Zenodo DOI を作成し、DOI を README /
   CITATION.cff に反映する。
10. JOSS レビュー後、最終 release を作成し、Zenodo DOI と JOSS DOI を反映する。
