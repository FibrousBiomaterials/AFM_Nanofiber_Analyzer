# GitHub・Zenodo・JOSS 投稿に向けたドキュメント TODO

AFM Nanofiber Analyzer を GitHub で公開し、Zenodo でアーカイブし、JOSS
投稿を目指すために用意すべきドキュメントを整理する。

この TODO は、現時点のリポジトリを見た暫定判定を含む（最終更新: 2026-06-23）。

- `あり`: ファイルは存在する。
- `要修正`: ファイルは存在するが、公開・JOSS・Zenodo 向けには内容の修正が必要。
- `未作成`: ファイルが見当たらないため新規作成が必要。
- `見送り`: JOSS 投稿・Zenodo 連携に必須ではないため作成しない。
- `要確認`: ファイルはあるが、内容を詳しく確認して公開可否や十分性を判断する必要がある。

## 0. 進捗サマリ（2026-06-23 時点）

初版作成時点から進んだ主な項目:

- `CONTRIBUTING.md`、`README.ja.md`、`CHANGELOG.md`、`SUPPORT.md` を作成済み。
- JOSS paper を作成済み。配置はリポジトリ直下の `paper.md` / `paper.bib`
  （`paper/` サブフォルダではない）。`Summary`、`Statement of need`、
  `State of the field`、`Software design`、`Research impact statement`、
  `AI usage disclosure` を整備済み（著者検証前提）。`Acknowledgements` は
  実内容の著者執筆に残置。
- CI を `.github/workflows/test.yml` として作成済み（push / pull request で
  Ruff lint + `check.py --verify` + Windows/Linux × Python 新旧マトリクスの
  pytest を実行）。
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
- `locale/` は `English` / `Japanese` / `Chinese` の構成で確定。README /
  README.ja の Directory Structure も実構成に更新済み。

未着手の主な残課題（JOSS 必須／外部情報が要る項目に限定）: `paper.md` の
`Research impact statement` の著者確認、`Acknowledgements` の実内容追加、
JOSS 事前スクリーニング向けの公開開発履歴・release/tag・Issue/PR 運用実績の
確認、CITATION.cff / README の DOI・リリース日プレースホルダー解消
（Zenodo 発行後）、GitHub release と Zenodo DOI の作成。

## 0.1 文書スコープ方針（2026-06-23 決定）

方針: **JOSS 投稿に必須でない文書は原則作成しない**。第三者向けの community
ガイドライン（貢献・問題報告・サポート）は `CONTRIBUTING.md`、`SUPPORT.md`、
README の Getting Help 節で満たすため、追加の周辺文書は必要が生じたときだけ作る。

- **作成・維持する（JOSS 必須、または community 要件を満たす）**: `README.md` /
  `README.ja.md`、`LICENSE`、`CITATION.cff`、`requirements.txt` /
  `requirements.lock.txt`、`pyproject.toml`、`.gitignore`、`paper.md` /
  `paper.bib`、`CONTRIBUTING.md`、`SUPPORT.md`、`CHANGELOG.md`、`tests/` と CI。
- **作成しない（JOSS 必須でない。見送り）**: `CODE_OF_CONDUCT.md`、`SECURITY.md`、
  `.zenodo.json`（CITATION.cff のみで運用）、`docs/release_process.md`、および
  任意 `docs/` ガイド（`installation.md`、`quickstart.md`、各 GUI マニュアル、
  `troubleshooting.md`、`developer_guide.md`、`data_contract.md`、
  `plugin_api.md`、`localization.md`、`testing.md`、`tests/README.md`、
  `examples/` 一式）。これらの内容は README / CONTRIBUTING / AGENTS.md / コードで
  カバーされている。
- 特定の文書が JOSS レビューや運用で実際に必要になった場合のみ、本方針の例外として
  個別に作成する。

## 1. 最優先で用意すべき公開用ドキュメント

| 文書 | 現状 | 目的 |
|---|---|---|
| `README.md` | あり・要修正 | GitHub の入口。ユーザー、レビュアー、共同研究者が最初に読む文書。 |
| `README.ja.md` | あり・要修正 | 日本語ユーザー向けの README。英語版と同期する。 |
| `LICENSE` | あり | 利用・改変・再配布条件を明確にする法的文書。JOSS で必須。著者4名を著作権者として併記。 |
| `CITATION.cff` | あり・要修正 | GitHub の引用ボタン、Zenodo、JOSS 後の引用情報に使うメタデータ。 |
| `requirements.txt` | あり | Python 依存関係の一覧（緩い指定）。固定版は `requirements.lock.txt`。 |
| `requirements.lock.txt` | あり | テスト検証済みの固定バージョンスナップショット。再現インストール用。 |
| `pyproject.toml` | あり | パッケージメタデータ、editable install、`[dev]` 依存、ruff/pytest 設定。 |
| `.gitignore` | あり | 生成物、個人環境、解析一時ファイル、機密ファイルの混入防止。 |

### `README.md` に必要な内容

- [x] ソフトウェアの目的を冒頭で簡潔に説明する。
- [x] AFM ナノファイバー解析で何を自動化・支援するソフトなのかを書く。
- [x] 対象ユーザーを明示する。
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
- [x] 既知の制限を書く（Known Limitations 節）。
- [x] 引用方法を書く（Citation 節）。
- [x] ライセンスを書く（License 節）。
- [x] 問い合わせ先または Issue の使い方を書く（Getting Help and Support 節）。

#### 現時点で不十分な点

- [ ] Zenodo DOI badge が `10.5281/zenodo.xxxxxxx` のプレースホルダーのまま
      （Zenodo 発行後に README / README.ja 両方を更新）。
- [x] `README.ja.md` の clone URL を実 URL（`q9-droid/AFM_Nanofiber_Analyzer`）
      に更新済み（2 か所）。`README.md` 側と一致。
- [x] Citation の BibTeX 著者名を正式名に更新済み（`CITATION.cff` と一致、
      README.md / README.ja.md 両方）。
- [x] Authors 欄の略称を正式名に更新済み（README.md / README.ja.md 両方）。
- [x] README / README.ja の Directory Structure を実構成
      （`locale/English` / `locale/Japanese` / `locale/Chinese`）に更新済み。

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
      （`paper.md` の corresponding author と最終 ORCID は提出前に再確認）。

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
- [ ] Zenodo 連携前に `cff-convert` 等で `CITATION.cff` を検証する。

#### 現時点で不十分な点

- [ ] `doi: "10.5281/zenodo.xxxxxxx"` が Zenodo 発行前のプレースホルダーのまま。
- [ ] `date-released: "2026-01-01"` が仮の日付。実リリース日に直す。
- [ ] 著者順、所属、ORCID が最終版として正しいか著者が確認する。
- [ ] Zenodo 連携前に、日本語 YAML コメントを含む現在のファイルが
      Zenodo / `cff-convert` 系の検証で問題にならないか確認する
      （YAML 仕様上コメントは許容されるが、連携時に念のため確認）。

### `requirements.txt` / 依存関係に必要な内容

- [x] 実行に必要な依存関係を書く（`requirements.txt`、`pyproject.toml` の `dependencies`）。
- [x] 開発用・ビルド用依存関係を分ける（`pyproject.toml` の `[dev]` extra に集約）。
- [x] 再現可能な固定バージョンを提供する（`requirements.lock.txt`）。
- [x] README のインストール手順と一致させる（緩い `requirements.txt` と lock の両方を案内）。
- [x] CI で同じ依存関係を使う（`.github/workflows/test.yml`）。

### `.gitignore` に必要な内容

- [x] Python キャッシュを除外する（`__pycache__/`、`*.py[cod]`）。
- [x] 仮想環境を除外する（`.venv/`、`venv/`、`.conda-env/` など）。
- [x] PyInstaller 生成物を除外する（`build/`、`dist/`、`*.spec`）。
- [x] ローカル設定ファイルを除外する（`.claude/`、`.lang_preference`、`guis/afmpp_settings.json`）。
- [x] 解析の一時出力や巨大出力を除外する（`*.b2z`、`*_param.json`、`*.npy`、`*.json`）。
- [x] 機密データや大容量サンプルを管理する（`Bruker_testdata/*` を除外し代表 1 ファイルのみ追跡）。

## 2. JOSS・オープンソース公開で強く推奨される文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `CONTRIBUTING.md` | あり | Issue、Pull Request、開発環境、テスト、コーディング方針を書く。 |
| `CHANGELOG.md` | あり・要修正 | リリースごとの変更履歴を記録する。 |
| `SUPPORT.md` | あり | 質問、バグ報告、研究利用相談の窓口を整理する。 |

### JOSS 事前スクリーニングで確認される公開開発実績

- [ ] GitHub リポジトリが公開され、ソース閲覧・clone・Issue 作成・変更提案が
      登録不要または通常の無料アカウントで可能であることを確認する。
- [ ] JOSS 提出時点で、公開状態の開発履歴が 6 か月超あることを確認する
      （非公開開発を直前に dump しただけの履歴は不可）。
- [ ] コミット履歴が短期間の集中投入だけでなく、利用・修正・改善の反復を示して
      いることを確認する。
- [ ] 少なくとも 1 つ以上の tagged release を用意する。
- [ ] public Issue / PR / Discussions、または paper 内の研究利用実績により、
      共同開発・外部利用・研究グループ内利用の具体的な証拠を示せるようにする。
- [ ] JOSS submission では、提出者が主要貢献者であること、著者全員が著者リストに
      同意していること、利益相反や関連投稿があれば開示することを確認する。

### `CONTRIBUTING.md` に必要な内容

- [x] Issue の立て方を書く（Reporting bugs 節）。
- [x] バグ報告に必要な情報を書く（OS、Python バージョン、入力形式、再現手順など）。
- [x] 機能提案の方法を書く（Requesting features 節）。
- [x] 開発環境の作り方を書く（Development setup 節）。
- [x] テストの実行方法を書く（Running the tests 節）。
- [x] Pull Request の流れを書く（Submitting a pull request 節）。
- [x] GUI プラグイン追加時のルールを書く。
- [x] `.b2z` バンドル契約を壊す変更では事前相談が必要であることを書く。
- [x] コメント・docstring の英日方針を書く（Coding standards 節 / `AGENTS.md` 参照）。
- [x] UI 文字列と scientific/reporting strings の翻訳方針を書く。

### `CHANGELOG.md` に必要な内容

- [x] バージョン番号を書く（`1.0.0`、`pyproject.toml` と一致）。
- [ ] リリース日を書く（雛形は `TBD`。タグ確定時に実日付へ差し替える）。
- [x] `Added`, `Changed`, `Fixed`, `Removed` などの分類で変更を書く
      （Keep a Changelog 形式の雛形を用意。1.0.0 は Added を記載済み）。
- [ ] 解析結果に影響する変更をリリース時に確認して明記する。
- [ ] `.b2z` 形式に影響する変更をリリース時に確認して明記する。
- [ ] GUI 操作や出力形式の変更をリリース時に確認して明記する。

### `SUPPORT.md` に必要な内容

- [x] バグ報告は GitHub Issues に誘導する。
- [x] 使い方の質問の窓口を書く。
- [x] 研究データを含むファイルを公開 Issue に添付しないよう注意する。
- [x] 回答できる範囲とできない範囲を書く。

## 3. JOSS 投稿に必要な論文関連文書

JOSS paper はリポジトリ直下に配置済み（`paper/` サブフォルダではない点に注意）。

| 文書 | 現状 | 目的 |
|---|---|---|
| `paper.md` | あり・要修正 | JOSS 投稿本文。必須節は揃っているが、著者確認と謝辞が残る。 |
| `paper.bib` | あり・要確認 | JOSS paper で引用する文献リスト。 |

### `paper.md` に必要な内容

- [x] YAML ヘッダーを書く。
- [x] タイトルを書く。
- [x] 著者、所属、ORCID を書く（YAML ヘッダー内）。
- [x] `Summary` を書く。
- [x] `Statement of need` を書く。
- [x] `State of the field` 節を書く。
- [x] `Software design` 節を書く。
- [x] `Research impact statement` 節を書く。
      外部利用を未確認のまま主張せず、リポジトリ内で確認できるサンプルデータ、
      CLI 例、回帰テスト、データ契約、標準形式への export に絞って記載済み。
- [ ] `Research impact statement` の事実関係を著者が最終確認する。
- [x] `AI usage disclosure` 節を書く。
- [x] JOSS paper の本文量を 750-1750 words の目安に収める
      （`Measure-Object -Word` で metadata 込み約 1520 words）。
- [x] 主な機能の説明が十分か確認する。
- [x] 対象データとワークフローの説明が十分か確認する。
- [x] 既存ツールとの関係の説明が十分か確認する。
- [x] 研究上の利用場面の説明を書く。
- [ ] `Acknowledgements` を実内容に差し替える。
      資金提供、施設、協力者を著者が確認して書く。該当がない場合も、提出方針に
      合わせて明示する。
- [ ] JOSS 提出時または最終受理前に、Zenodo 等のソフトウェアアーカイブ DOI を
      paper / submission metadata に反映する。
- [x] `paper.bib` の文献を引用する（References 節）。

#### 確認すべき点

- [x] `paper.md` の著者名、著者順、所属、ORCID を `CITATION.cff`、
      `pyproject.toml`、README と照合する。
      現状のローカルファイル間では著者名と順序が一致している。
- [ ] corresponding author、最終所属、ORCID、著者全員の同意を著者が確認する。
- [ ] 利益相反、関連投稿、JOSS 論文が新しい研究結果そのものを主題にしていないことを
      著者が確認し、必要なら投稿時に開示する。
- [ ] JOSS paper が Open Journals の形式でコンパイルできるか確認する。

### `paper.bib` に必要な内容

- [ ] AFM 関連の基礎文献が十分か確認する。
- [ ] ナノファイバー解析に関する文献が十分か確認する。
- [x] 画像解析・スケルトン化・セグメンテーション関連文献が入っているか確認する。
- [x] NumPy、SciPy、scikit-image、Matplotlib など主要ライブラリの引用が入っているか確認する。
- [x] 関連する先行ソフトウェアの引用が入っているか確認する。
- [ ] 文献に DOI が付与されているか確認する（JOSS はレビュー時に可能な範囲で DOI を求める）。

## 4. ユーザー向け操作文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `README.ja.md` | あり | 日本語ユーザー向けの導入・操作説明（英語 README と同期）。 |

## 5. 開発者・保守者向け文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `docs/maintainer-notes.ja.md` | あり | 日本語の保守者向けメモ。 |
| `docs/docstring-templates.md` | あり | docstring テンプレート（`AGENTS.md` §3.4 から参照）。 |
| `AGENTS.md` | あり | AI 編集エージェント向けの正準指示ファイル。設計・データ契約・翻訳方針も集約。 |
| `CLAUDE.md` | あり | `AGENTS.md` を import する薄いポインタ。 |

## 6. リリース・Zenodo 関連文書

| 文書 | 現状 | 目的 |
|---|---|---|
| GitHub Release notes | 未作成 | GitHub release 作成時に、`CHANGELOG.md` の内容を元に作成する。 |

### Zenodo / GitHub release に必要な作業

- [ ] Zenodo アカウントで GitHub 連携を有効にし、対象 repository を enable する。
- [ ] Git tag を作成する。
- [ ] GitHub Release を作成する。
- [ ] GitHub Release 後、Zenodo が release を処理するまで待ち、失敗時は
      Zenodo 側の error 表示を確認して metadata を修正する。
- [ ] Zenodo record の resource type が Software であること、license と creators が
      正しいこと、DOI が発行されたことを確認する。
- [ ] Zenodo は `.zenodo.json` → CITATION.cff → LICENSE の優先順でメタデータを読む
      （両方あると `.zenodo.json` が全面採用され CITATION.cff は無視される）。
      `.zenodo.json` を置かない方針では CITATION.cff が best-effort 解析され、
      abstract / authors（ORCID・所属を含む）/ keywords / license / title のみ反映
      される（resource type=Software は GitHub 連携の既定で付く）。funding /
      communities / related_identifiers（JOSS paper DOI リンク等）が必要になった
      場合のみ `.zenodo.json` を追加する。release 後に record の著者・ORCID・
      タイトル・ライセンスが CITATION.cff どおり反映されたかを確認する。
- [ ] Zenodo の version DOI と all-versions/concept DOI のどちらを README badge、
      CITATION、JOSS 最終アーカイブ DOI に使うか確認する。
- [ ] README / README.ja の DOI badge 更新手順を書く代わりに、発行後すぐ本文へ反映する。
- [ ] JOSS レビュー後の最終 release を作成し、Zenodo DOI と release version を
      review issue に報告する。

## 7. テスト・CI 関連文書

| 文書 | 現状 | 目的 |
|---|---|---|
| `.github/workflows/test.yml` | あり | GitHub Actions で Ruff lint + pytest を実行する。 |
| `tests/` | あり | pytest スイート（afm_io, pipeline, measure, bundle_schema, export, 翻訳, 回帰など）。 |

### `.github/workflows/test.yml` の状況

- [x] push と pull request で実行する。
- [x] Python バージョンを指定する（新旧 2 バージョンのマトリクス）。
- [x] 依存関係をインストールする。
- [x] Ruff による lint を実行する。
- [x] `check.py --verify`（import / pyproject / 環境の整合チェック）を実行する。
- [x] `pytest` を実行する（Windows / Linux マトリクス）。
- [x] GUI を直接起動しない範囲でテストする。
- [ ] 提出前に `python check.py --verify`、`python -m pytest`、CI が通ることを確認する。

## 8. サンプルデータ・チュートリアル関連文書

リポジトリには既にサンプルスキャンがある（`testdata_tunicateCNF`、
`testdata_higherplantTOC`、`Bruker_testdata`）。`examples/` 構成は §0.1 方針により
見送り。README の CLI 例、JOSS paper の `Research impact statement`、テストスイートで
再現可能性を説明する。

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

方針更新: §0.1 により JOSS 投稿に必須でない文書は見送り。残りは主に JOSS 必須項目と
外部情報（Zenodo DOI・公開履歴・リリース日）に依存する項目に絞られる。

1. `paper.md` の `Research impact statement` の事実関係を著者が確認し、
   `Acknowledgements` を著者が執筆する。
2. JOSS 事前スクリーニングに向けて、GitHub の公開日、6 か月超の公開履歴、
   release/tag、public Issue/PR/Discussions、研究利用実績を確認する（外部・運用）。
3. `paper.bib` に AFM / ナノファイバー解析のドメイン文献を追加すべきか著者が確認する。
4. `paper.md` が JOSS の形式でコンパイルできるか確認する。
5. `CITATION.cff` を `cff-convert` 等で検証する。
6. `CHANGELOG.md` の `TBD`、`CITATION.cff` の `date-released` を実リリース日に直す。
7. GitHub release と Zenodo DOI を作成し、DOI を README / README.ja /
   `CITATION.cff` / `paper.md` / submission metadata に反映する。
8. JOSS submission form から投稿する。
