# 個別データでの評価

[解析アルゴリズム](algorithms.ja.md) は、解析の各段が何を計算するかを説明する。
このページは、各段が個別のデータで何をしたかをまとめる。対象は、リポジトリに
同梱したスキャンと、答えが分かるように描いた合成スキャンである。コードの既定値の
いくつかはこれらの結果を見て選んでおり、どれがそうかもこのページに書く。

**このページの数値はすべて、それを測ったデータについての記述であり、
アルゴリズムの性質ではない。** 同梱スキャンは 3<!--m:kink_reference.scans--> 枚で、試料は 2<!--n:count--> 種である。高等植物 TOC と
Bruker NDTOC のスキャンは同じ分散液を測ったもので、後者は Bruker のデータを読めるか
試すために取った。合成スキャンは、決まった繊維と探針の形で描いている。どちらも、
別の試料・別の装置・別の走査サイズで解析がどう振る舞うかは教えない。ここに
示す結果は、確かめる価値のある振る舞いの種類を示すにすぎない。自分の画像で
それが成り立つかは、自分の画像を見て判断する。

## データと数値の管理

| データ | 内容 | コード |
|---|---|---|
| 同梱スキャン | チュニケート CNF（`testdata_tunicateCNF`）、高等植物 TOC（`testdata_higherplantTOC`）、Bruker NDTOC（`testdata_Bruker_txt`）の各スキャン。`testdata_artificial` の 2<!--n:count--> つの試料はチュニケートのスキャンの切り抜きなので使わない | `scripts/kink_reference_score.py` の `SCANS` |
| 目視基準 | 同梱スキャンの高さ画像に、AI コーディングエージェント（Claude Code）が付けたキンクの印。繊維ごとに高さ画像を拡大した切り出しを見て付けており、画像には検出器の出力を描いていない。ただし一部の繊維については、当時の検出器がどこにキンクを置くかを事前に知っていた。明瞭なキンク 53<!--m:kink_reference.clear_marks--> 件 | `scripts/kink_reference_score.py` |
| 合成データ一式 | 中心線とコーナーの位置が既知の合成スキャン。画素 2<!--c:scripts/synthetic_suite.py::NMPX--> nm、見かけ幅 $W$ = 8<!--c:scripts/synthetic_suite.py::W--> px | `scripts/synthetic_suite.py` |
| キンク規則の掃引 | 見かけ幅と画素ノイズを変えて描いた、折れ・直線・円弧・正弦波の合成繊維 | `scripts/kink_rule_sweep.py` |

数値はすべて、本文に名前を書いた `scripts/measure_docs.py` の実験が出したもので
あり、表示されない印を持つ。`scripts/check_doc_numbers.py` がその印を
`tests/doc_measurements.json` の記録と照合する。実験が走ったコードの計算内容が
変わると、実験をやり直すまでこの検査は通らない（AGENTS.md §8.15）。

## 1. 背景補正

[解析アルゴリズム](algorithms.ja.md) §1 を参照。

### 1.1 同梱スキャンの傾きと皿状成分

| スキャン | 平面の傾き（nm/px） | マスクした繊維 1<!--n:count--> 本分の落差（nm） | 皿状成分の山谷（nm） | スケルトン下の高さの中央値（nm） |
|---|---|---|---|---|
| チュニケート CNF | 0.23<!--m:bg_stats.tunicate.plane_slope_nm_per_px--> | 3.8<!--m:bg_stats.tunicate.drop_across_hole_nm--> | 15.2<!--m:bg_stats.tunicate.quadratic_p2p_nm--> | 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> |
| 高等植物 TOC | 0.001<!--m:bg_stats.hplantTOC.plane_slope_nm_per_px--> | 0.01<!--m:bg_stats.hplantTOC.drop_across_hole_nm--> | 1.7<!--m:bg_stats.hplantTOC.quadratic_p2p_nm--> | 1.7<!--m:bg_stats.hplantTOC.skeleton_height_median_nm--> |
| Bruker NDTOC | 0.003<!--m:bg_stats.NDTOC.plane_slope_nm_per_px--> | 0.04<!--m:bg_stats.NDTOC.drop_across_hole_nm--> | 21.9<!--m:bg_stats.NDTOC.quadratic_p2p_nm--> | 2.1<!--m:bg_stats.NDTOC.skeleton_height_median_nm--> |

平面の傾きは生の高さに当てた最小二乗平面の傾き、落差はその傾きに膨張後の繊維
マスクの幅の中央値を掛けたもの、皿状成分は平面を除いた後に当てた 2<!--n:definition--> 次曲面の
2<!--n:definition--> 次の項の山谷、高さは既定のスケルトンの下にある補正後の高さの中央値である
（実験 bg_stats）。チュニケートのスキャンでは、中央値 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> nm の高さしかない
繊維 1<!--n:count--> 本分のマスクを横切る間に、背景が 3.8<!--m:bg_stats.tunicate.drop_across_hole_nm--> nm 落ちる。高等植物と Bruker の
スキャンは平面としては水平だが、Bruker のスキャンは皿状成分だけで 21.9<!--m:bg_stats.NDTOC.quadratic_p2p_nm--> nm に
及ぶ。背景補正のトレンド曲面を平面ではなく 2<!--n:definition--> 次曲面にしたのは、最後のような
スキャンがあるためである。

### 1.2 デトレンドの有無による充填の精度

チュニケートのスキャンの繊維の無い背景に、21<!--m:bg_fill.hole_size_px--> px 四方の穴を 13<!--m:bg_fill.holes--> 個開けて
調べると（実験 bg_fill）、充填値がそこで実際に測られた高さから外れる量は、
デトレンドしない場合は最近傍伝播で 2.4<!--m:bg_fill.none.nearest.fill_error_median_nm--> nm、inpainting で 1.7<!--m:bg_fill.none.inpaint.fill_error_median_nm--> nm、2<!--n:definition--> 次の
トレンドを除いた後はそれぞれ 0.31<!--m:bg_fill.quadratic.nearest.fill_error_median_nm--> nm と 0.25<!--m:bg_fill.quadratic.inpaint.fill_error_median_nm--> nm であった（各穴での最大の外れの、
穴全体での中央値）。これらの穴では、精度を決めていたのは充填法ではなく
デトレンドであり、平面でも 2<!--n:definition--> 次曲面とほぼ同じ結果であった（最近傍の充填で
0.31<!--m:bg_fill.plane.nearest.fill_error_median_nm--> nm と 0.31<!--m:bg_fill.quadratic.nearest.fill_error_median_nm--> nm）。

### 1.3 1.0.0 までの充填方式

デトレンドしない 1.0.0 までの inpainting は、上のチュニケートの穴で本当の背景
から 1.7<!--m:bg_fill.none.inpaint.fill_error_median_nm--> nm 外れた。1.0.0 のリリースの背景補正（タグ `v1.0.0` から実行）を、
0.24<!--m:bg_legacy_halo.slope_nm_per_px--> nm/px の平面の上に高さ 8<!--m:bg_legacy_halo.fiber_height_nm--> nm の繊維を 1<!--n:count--> 本置いた合成走査にかけると
（実験 bg_legacy_halo）、繊維の脇の補正後の背景は −0.76<!--m:bg_legacy_halo.v1_0_0.beside_min_nm-->〜+0.77<!--m:bg_legacy_halo.v1_0_0.beside_max_nm--> nm となり、
二値化しきい値の既定 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm を超えた。現在のコードではそこは
−0.21<!--m:bg_legacy_halo.current.beside_min_nm-->〜+0.18<!--m:bg_legacy_halo.current.beside_max_nm--> nm である。

### 1.4 縁での `tophat`

同梱スキャンで最も急な平面の傾き（0.23<!--m:bg_stats.tunicate.plane_slope_nm_per_px--> nm/px、§1.1）より少し急な 0.24<!--m:tophat_border.slope_nm_per_px--> nm/px の斜面に、
直径 25<!--c:lib/pipeline.py::ProcParams.tophat_se_size--> px の要素で生の高さに opening をかけると、上り側の端から 12<!--n:definition--> px
以内に高さ**3.1<!--m:tophat_border.raw.uphill_band_max_nm--> nm** の帯が残る。二値化しきい値 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm を大きく超える
値である。デトレンドした高さに opening をかけると 0.29<!--m:tophat_border.detrended.uphill_band_max_nm--> nm になる
（実験 tophat_border）。

### 1.5 `spline1d` の向き

各テスト入力を、`trendfill` と、`'x'` と `'y'` の 2<!--n:count--> つの向きの `spline1d` で補正した。
ほかはすべて既定値である（実験 spline1d_axis）。背景（3<!--n:count--> つの二値化マスクを合わせた
範囲から 5<!--n:definition--> px より離れた画素）で、行ごとの中央値のばらつき（標準偏差、nm）と、
列ごとの中央値のばらつきを表に示す。前者は横縞があると大きくなり、後者は縦縞が
あると大きくなる。

| 入力 | 行、`trendfill` | 行、`'x'` | 行、`'y'` | 列、`trendfill` | 列、`'x'` | 列、`'y'` |
|---|---|---|---|---|---|---|
| チュニケート CNF | 0.010<!--m:spline1d_axis.tunicate.trendfill.row_median_std_nm--> | 0.007<!--m:spline1d_axis.tunicate.x.row_median_std_nm--> | 0.075<!--m:spline1d_axis.tunicate.y.row_median_std_nm--> | 0.011<!--m:spline1d_axis.tunicate.trendfill.column_median_std_nm--> | 0.017<!--m:spline1d_axis.tunicate.x.column_median_std_nm--> | 0.015<!--m:spline1d_axis.tunicate.y.column_median_std_nm--> |
| 高等植物 TOC | 0.292<!--m:spline1d_axis.hplantTOC.trendfill.row_median_std_nm--> | 0.006<!--m:spline1d_axis.hplantTOC.x.row_median_std_nm--> | 0.313<!--m:spline1d_axis.hplantTOC.y.row_median_std_nm--> | 0.005<!--m:spline1d_axis.hplantTOC.trendfill.column_median_std_nm--> | 0.006<!--m:spline1d_axis.hplantTOC.x.column_median_std_nm--> | 0.009<!--m:spline1d_axis.hplantTOC.y.column_median_std_nm--> |
| Bruker NDTOC | 0.019<!--m:spline1d_axis.NDTOC.trendfill.row_median_std_nm--> | 0.019<!--m:spline1d_axis.NDTOC.x.row_median_std_nm--> | 0.306<!--m:spline1d_axis.NDTOC.y.row_median_std_nm--> | 0.015<!--m:spline1d_axis.NDTOC.trendfill.column_median_std_nm--> | 0.015<!--m:spline1d_axis.NDTOC.x.column_median_std_nm--> | 0.036<!--m:spline1d_axis.NDTOC.y.column_median_std_nm--> |

`'y'` では、行ごとのばらつきがどの入力でも `trendfill` より大きかった。補正後の画像を
描くと、`'y'` では、チュニケート、Bruker、高等植物の入力で、画像全体に明るい横帯と
暗い横帯ができ、高等植物のスキャンの走査線のグリッチも残る。`'x'` では、高等植物の
スキャンでそのグリッチが消え、チュニケートのスキャンで `trendfill` が残す横の
筋も消える。ただし、チュニケートのスキャンでは、縦に近い向きに走る
繊維の右側に、`trendfill` より目に見えて深い暗い縁ができる。この入力では、
`'x'` の列ごとのばらつきが `trendfill` よりはっきり大きく、高等植物と Bruker の
スキャンではほぼ同じである。

縦縞で確かめるため、各テスト入力を 90<!--n:definition--> 度回して（`np.rot90`。走査ラインが列になり、
走査ラインごとのずれが縦縞になる）、同じ比較をした（実験 spline1d_axis_rotated）。
表は、回した入力での列ごとの中央値のばらつきである。

| 入力（回したもの） | 列、`trendfill` | 列、`'x'` | 列、`'y'` |
|---|---|---|---|
| チュニケート CNF | 0.069<!--m:spline1d_axis_rotated.tunicate.trendfill.column_median_std_nm--> | 0.125<!--m:spline1d_axis_rotated.tunicate.x.column_median_std_nm--> | 0.072<!--m:spline1d_axis_rotated.tunicate.y.column_median_std_nm--> |
| 高等植物 TOC | 0.040<!--m:spline1d_axis_rotated.hplantTOC.trendfill.column_median_std_nm--> | 0.074<!--m:spline1d_axis_rotated.hplantTOC.x.column_median_std_nm--> | 0.040<!--m:spline1d_axis_rotated.hplantTOC.y.column_median_std_nm--> |
| Bruker NDTOC | 0.046<!--m:spline1d_axis_rotated.NDTOC.trendfill.column_median_std_nm--> | 0.261<!--m:spline1d_axis_rotated.NDTOC.x.column_median_std_nm--> | 0.047<!--m:spline1d_axis_rotated.NDTOC.y.column_median_std_nm--> |

高等植物のスキャンを除く 2<!--n:count--> つの入力では、回すと、`trendfill` も含めてどの方式でも
ばらつきが大きくなった（最初の表と比べる）。そのため、この表の数値からは `'y'` の
効き目を切り分けられない。描くと、高等植物のスキャンの走査線のグリッチは、回した画像に
`'y'` を使っても明るい縦の帯として残り、回さない画像に `'x'` を使ったときのようには
消えない。この帯は、回した画像では二値化で繊維と判定されるので、ばらつきを測る背景から
外れ、表の値には入っていない。回したチュニケートのスキャンでは、`trendfill` でも `'y'` でも、
画像全体に細い縦縞が残る。回したこれらのテスト入力では、`'y'` は、回さない画像で `'x'` が
消すグリッチを消さなかった。

### 1.6 X 方向だけのならし

各テスト入力を既定の `trendfill` で補正し、背景の Savitzky–Golay 平滑化を、コードの
とおり X 方向だけにかけた場合と、X 方向の後に Y 方向にもかけた場合とで比べた（実験
savgol_axis）。表は、背景（2<!--n:count--> つの二値化マスクを合わせた範囲から 5<!--n:definition--> px より離れた
画素）で、行ごとの中央値のばらつき（標準偏差、nm）を示す。横縞があると大きくなる。

| 入力 | 行、X のみ | 行、X と Y |
|---|---|---|
| チュニケート CNF | 0.010<!--m:savgol_axis.tunicate.x_only.row_median_std_nm--> | 0.069<!--m:savgol_axis.tunicate.x_and_y.row_median_std_nm--> |
| 高等植物 TOC | 0.292<!--m:savgol_axis.hplantTOC.x_only.row_median_std_nm--> | 0.297<!--m:savgol_axis.hplantTOC.x_and_y.row_median_std_nm--> |
| Bruker NDTOC | 0.015<!--m:savgol_axis.NDTOC.x_only.row_median_std_nm--> | 0.046<!--m:savgol_axis.NDTOC.x_and_y.row_median_std_nm--> |
Y 方向にもならすと、どの入力でも行ごとのばらつきが大きくなった。補正後の画像を
描くと、両方向にならした画像では、チュニケートと高等植物のスキャンに、
X 方向だけのときには無い横方向の筋が全体に出る。Bruker のスキャンは、どちらでも
ほとんど同じに見える。

### 1.7 `spline1d` がトレンドを足し戻す順番

`spline1d` はトレンドを Savitzky–Golay 平滑化の前に足し戻し、`trendfill` は後に足し
戻す。各テスト入力を、両方の順番の `spline1d` で補正した（実験 spline1d_trend_order）。
表は、補正後の高さのいちばん大きい違い（nm）である。

| 入力 | いちばん大きい違い (nm) |
|---|---|
| チュニケート CNF | 0.006<!--m:spline1d_trend_order.tunicate.max_difference_nm--> |
| 高等植物 TOC | 0.000<!--m:spline1d_trend_order.hplantTOC.max_difference_nm--> |
| Bruker NDTOC | 0.000<!--m:spline1d_trend_order.NDTOC.max_difference_nm--> |
平滑化は線形なので、2<!--n:count--> つの順番の違いは、トレンドそのものとそれをならしたものの差
だけになり、トレンドが X 方向に大きく曲がっている所ほど大きい。どの入力でも、違いは
二値化のしきい値 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm よりずっと小さい。

### 1.8 繊維が多くの画素にまたがる走査

背景補正の方式が使う長さはすべて画素数である（[解析アルゴリズム](algorithms.ja.md) §1）。
そのため、多くの画素にまたがる繊維は、一部が背景として引かれうる。同梱スキャンの
繊維は少ない画素にしかまたがらないので、これは同梱スキャンでは見えない。そこで、
同梱スキャンから、同じ繊維をより細かい画素で撮った走査を作った（実験
zoomed_background）。各同梱スキャンについて、既定の補正後の画像を標準偏差 1<!--n:value tried--> px の
ガウス関数でぼかしたものを基準の高さとし、既定の解析が引いた背景を背景とする。
基準は元の画素サイズでの既定の解析そのものなので、下の「残った高さ」が測るのは、
画素を細かくしたときにそれに比べて失われる高さであり、既定の解析自体の誤差では
ない。この実験は高さの絶対的な精度を測っていない。それは §1.9 で合成繊維について測る。
スケルトン画素を最も多く含む 256<!--c:scripts/measure_docs.py::ZOOM_TILE--> px の切り出し 2<!--n:count--> 枚を
各拡大率で補間して拡大する。撮る範囲は同じまま、画素だけが細かくなる。そこに元の
スキャンと同じ大きさの白色ノイズ（0.027<!--m:zoomed_background.tunicate.noise_nm-->〜0.064<!--m:zoomed_background.NDTOC.noise_nm--> nm）を加え、各方式を既定値で
4<!--n:count--> 段すべてに通す。元の画素サイズでの繊維の見かけ幅は 7.6<!--m:zoomed_background.hplantTOC.width_px-->〜8.6<!--m:zoomed_background.NDTOC.width_px--> px なので、
拡大率 $k$ では約 $k$ 倍の画素にまたがる。「残った高さ」は、既定のスケルトンの点で
補正後の高さを基準の高さで割った値の中央値で、ここでは切り出しごとの範囲を示す。

| 拡大率 | trendfill | spline1d | tophat |
|---|---|---|---|
| 1<!--n:value tried--> | 0.97〜1.00<!--m:zoomed_background.trendfill.x1.kept_range--> | 0.99〜1.01<!--m:zoomed_background.spline1d.x1.kept_range--> | 0.92〜0.98<!--m:zoomed_background.tophat.x1.kept_range--> |
| 1.5<!--n:value tried--> | 0.61〜1.00<!--m:zoomed_background.trendfill.x1.5.kept_range--> | 0.89〜1.00<!--m:zoomed_background.spline1d.x1.5.kept_range--> | 0.83〜0.95<!--m:zoomed_background.tophat.x1.5.kept_range--> |
| 2<!--n:value tried--> | 0.32〜1.00<!--m:zoomed_background.trendfill.x2.kept_range--> | 0.63〜1.00<!--m:zoomed_background.spline1d.x2.kept_range--> | 0.64〜0.83<!--m:zoomed_background.tophat.x2.kept_range--> |
| 3<!--n:value tried--> | 0.13〜0.96<!--m:zoomed_background.trendfill.x3.kept_range--> | 0.27〜0.99<!--m:zoomed_background.spline1d.x3.kept_range--> | 0.31〜0.49<!--m:zoomed_background.tophat.x3.kept_range--> |
| 4<!--n:value tried--> | 0.08〜0.18<!--m:zoomed_background.trendfill.x4.kept_range--> | 0.13〜0.93<!--m:zoomed_background.spline1d.x4.kept_range--> | 0.17〜0.28<!--m:zoomed_background.tophat.x4.kept_range--> |

すべての実行で `background_warnings`（`lib/pipeline.py`）を確かめ、勧める設定を伴う
警告が出た実行は、その設定で解析し直した。

| 拡大率 | 実行数 | 残った高さ 0.9<!--n:definition--> 未満 | うち警告なし | 警告あり | 警告ありで 0.97<!--n:definition--> 以上残った |
|---|---|---|---|---|---|
| 1<!--n:value tried--> | 18<!--m:zoomed_background.x1.runs--> | 0<!--m:zoomed_background.x1.below_90--> | 0<!--m:zoomed_background.x1.below_90_unwarned--> | 3<!--m:zoomed_background.x1.warned--> | 2<!--m:zoomed_background.x1.warned_above_97--> |
| 1.5<!--n:value tried--> | 18<!--m:zoomed_background.x1.5.runs--> | 7<!--m:zoomed_background.x1.5.below_90--> | 1<!--m:zoomed_background.x1.5.below_90_unwarned--> | 11<!--m:zoomed_background.x1.5.warned--> | 1<!--m:zoomed_background.x1.5.warned_above_97--> |
| 2<!--n:value tried--> | 18<!--m:zoomed_background.x2.runs--> | 12<!--m:zoomed_background.x2.below_90--> | 0<!--m:zoomed_background.x2.below_90_unwarned--> | 13<!--m:zoomed_background.x2.warned--> | 0<!--m:zoomed_background.x2.warned_above_97--> |
| 3<!--n:value tried--> | 18<!--m:zoomed_background.x3.runs--> | 15<!--m:zoomed_background.x3.below_90--> | 3<!--m:zoomed_background.x3.below_90_unwarned--> | 14<!--m:zoomed_background.x3.warned--> | 1<!--m:zoomed_background.x3.warned_above_97--> |
| 4<!--n:value tried--> | 18<!--m:zoomed_background.x4.runs--> | 17<!--m:zoomed_background.x4.below_90--> | 3<!--m:zoomed_background.x4.below_90_unwarned--> | 15<!--m:zoomed_background.x4.warned--> | 0<!--m:zoomed_background.x4.warned_above_97--> |

繊維の幅を測れなかったという警告には、従う設定が無い。警告が出た 56<!--m:zoomed_background.warned--> 回のうち 28<!--m:zoomed_background.warned_without_advice--> 回は
その警告だけだった。それ以外の警告が出た実行を勧めどおりに解析し直すと、高さの
0.51〜1.01<!--m:zoomed_background.followed.kept_range--> が残り、背景の誤差の 95<!--n:definition--> パーセンタイルは最大 0.24<!--m:zoomed_background.followed.bg95_max--> nm で、4<!--m:zoomed_background.followed.still_warned--> 回は再び警告が
出た。最も低い 0.51<!--m:zoomed_background.x4.followed_kept_range[0]--> は、拡大率 4<!--n:value tried--> で勧める設定を伴った唯一の実行である。高さの 0.9<!--n:definition--> 未満
しか残らなかった実行のうち、警告が出なかったのは、拡大率 1.5<!--n:value tried--> で 1<!--m:zoomed_background.x1.5.below_90_unwarned--> 回、3<!--n:value tried--> で 3<!--m:zoomed_background.x3.below_90_unwarned--> 回、
4<!--n:value tried--> で 3<!--m:zoomed_background.x4.below_90_unwarned--> 回である。見かけ幅から予測する警告と、補正後の画像を測る警告を分けた結果は
§1.10 にある。

### 1.9 高さが既知の合成繊維

同梱スキャンには繊維の高さが既知のものが無いので、高さが既知の直線繊維を描いて
解析した（実験 synthetic_height）。直径 $D$ = 2<!--n:value tried-->、4<!--n:value tried-->、8<!--n:value tried--> nm の平行な円柱 3<!--n:count--> 本を、半径 15<!--c:scripts/synthetic_suite.py::TIP--> nm の
球状の探針先端で撮ったものとし、320<!--n:value tried--> × 320<!--n:value tried--> px の走査に 1<!--n:value tried-->、2<!--n:value tried-->、5<!--n:value tried-->、10<!--n:value tried--> nm の画素で描いた。
合成データ一式と同じ傾斜・粗さ・走査線ノイズと、0.05<!--n:value tried--> または 0.2<!--n:value tried--> nm の画素ノイズを
加えた。各円柱を探針で撮った断面は、走査が表面を標本化するのと同じく、各画素の中心で
評価した。各繊維の中央 80<!--n:definition--> % で次の 3<!--n:count--> つを読み、$D$ で割る。画素格子が示せる
高さ（繊維だけの画像の、軸に最も近い画素の値）、背景補正がその画素で取り除いた
高さ（繊維だけの画像から補正後の画像を引いた値の中央値）、報告される高さ（追跡した
繊維の高さ標本の中央値）である。`trendfill`、ノイズ 0.05<!--n:value tried--> nm での結果は次のとおり。

| 画素サイズ | $D$ | $W$ | 画素格子が示す高さ | 取り除かれた高さ | 報告される高さ |
|---|---|---|---|---|---|
| 1<!--n:value tried--> nm | 2<!--n:value tried--> nm | 11.1<!--m:synthetic_height.px1.d2.w_px--> px | 1.00<!--m:synthetic_height.px1.d2.n0.05.peak--> | 0.13<!--m:synthetic_height.trendfill.px1.d2.n0.05.bg_loss--> | 0.94<!--m:synthetic_height.trendfill.px1.d2.n0.05.height--> |
| 1<!--n:value tried--> nm | 4<!--n:value tried--> nm | 16.0<!--m:synthetic_height.px1.d4.w_px--> px | 1.00<!--m:synthetic_height.px1.d4.n0.05.peak--> | 0.53<!--m:synthetic_height.trendfill.px1.d4.n0.05.bg_loss--> | – |
| 1<!--n:value tried--> nm | 8<!--n:value tried--> nm | 23.3<!--m:synthetic_height.px1.d8.w_px--> px | 1.00<!--m:synthetic_height.px1.d8.n0.05.peak--> | 0.84<!--m:synthetic_height.trendfill.px1.d8.n0.05.bg_loss--> | – |
| 2<!--n:value tried--> nm | 2<!--n:value tried--> nm | 5.6<!--m:synthetic_height.px2.d2.w_px--> px | 0.99<!--m:synthetic_height.px2.d2.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px2.d2.n0.05.bg_loss--> | 1.02<!--m:synthetic_height.trendfill.px2.d2.n0.05.height--> |
| 2<!--n:value tried--> nm | 4<!--n:value tried--> nm | 8.0<!--m:synthetic_height.px2.d4.w_px--> px | 1.00<!--m:synthetic_height.px2.d4.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px2.d4.n0.05.bg_loss--> | 1.02<!--m:synthetic_height.trendfill.px2.d4.n0.05.height--> |
| 2<!--n:value tried--> nm | 8<!--n:value tried--> nm | 11.7<!--m:synthetic_height.px2.d8.w_px--> px | 1.00<!--m:synthetic_height.px2.d8.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px2.d8.n0.05.bg_loss--> | 1.01<!--m:synthetic_height.trendfill.px2.d8.n0.05.height--> |
| 5<!--n:value tried--> nm | 2<!--n:value tried--> nm | 2.2<!--m:synthetic_height.px5.d2.w_px--> px | 0.96<!--m:synthetic_height.px5.d2.n0.05.peak--> | 0.01<!--m:synthetic_height.trendfill.px5.d2.n0.05.bg_loss--> | 0.96<!--m:synthetic_height.trendfill.px5.d2.n0.05.height--> |
| 5<!--n:value tried--> nm | 4<!--n:value tried--> nm | 3.2<!--m:synthetic_height.px5.d4.w_px--> px | 0.98<!--m:synthetic_height.px5.d4.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px5.d4.n0.05.bg_loss--> | 0.99<!--m:synthetic_height.trendfill.px5.d4.n0.05.height--> |
| 5<!--n:value tried--> nm | 8<!--n:value tried--> nm | 4.7<!--m:synthetic_height.px5.d8.w_px--> px | 0.99<!--m:synthetic_height.px5.d8.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px5.d8.n0.05.bg_loss--> | 1.00<!--m:synthetic_height.trendfill.px5.d8.n0.05.height--> |
| 10<!--n:value tried--> nm | 2<!--n:value tried--> nm | 1.1<!--m:synthetic_height.px10.d2.w_px--> px | 0.85<!--m:synthetic_height.px10.d2.n0.05.peak--> | 0.01<!--m:synthetic_height.trendfill.px10.d2.n0.05.bg_loss--> | – |
| 10<!--n:value tried--> nm | 4<!--n:value tried--> nm | 1.6<!--m:synthetic_height.px10.d4.w_px--> px | 0.93<!--m:synthetic_height.px10.d4.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px10.d4.n0.05.bg_loss--> | 0.89<!--m:synthetic_height.trendfill.px10.d4.n0.05.height--> |
| 10<!--n:value tried--> nm | 8<!--n:value tried--> nm | 2.3<!--m:synthetic_height.px10.d8.w_px--> px | 0.97<!--m:synthetic_height.px10.d8.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px10.d8.n0.05.bg_loss--> | 0.97<!--m:synthetic_height.trendfill.px10.d8.n0.05.height--> |

「–」は、追跡した線が繊維に沿っておらず、その高さ標本が繊維の高さにならない実行で
ある。画素 1<!--n:value tried--> nm で $D$ = 4<!--n:value tried--> と 8<!--n:value tried--> nm では、補正後の繊維は中がくり抜かれ、追跡した線は
繊維の中で輪を描くか繊維を外れる。画素 10<!--n:value tried--> nm で 2<!--n:value tried--> nm の繊維は、補正後の画像には
見えているが、長さの 0.09<!--m:synthetic_height.trendfill.px10.d2.n0.05.traced--> しか追跡されなかった（いずれも補正後の画像で確認した）。

3<!--n:count--> 方式・2<!--n:count--> つのノイズ水準を通して見ると次のとおりである。画素 2<!--n:value tried--> nm では繊維が 5.6<!--m:synthetic_height.px2.d2.w_px-->〜11.7<!--m:synthetic_height.px2.d8.w_px--> px に
またがり（同梱スキャンの繊維は 7.6<!--m:zoomed_background.hplantTOC.width_px-->〜8.6<!--m:zoomed_background.NDTOC.width_px--> px、§1.8）、補正が取り除いた高さは −0.01<!--m:synthetic_height.px2.removed_range[0]--> から
0.03<!--m:synthetic_height.px2.removed_range[1]--> の間、報告される高さは 0.98〜1.05<!--m:synthetic_height.px2.height_range--> だった。画素 5<!--n:value tried--> nm と 10<!--n:value tried--> nm では、補正が取り除いた
高さは最大 0.01<!--m:synthetic_height.coarse.removed_max--> である。そこで高さを制限するのは画素格子で、繊維の細い頂上が
画素の中心のあいだに落ちるため、5<!--n:value tried--> nm では 0.96〜0.99<!--m:synthetic_height.px5.peak_range-->、10<!--n:value tried--> nm では 0.85〜0.97<!--m:synthetic_height.px10.peak_range--> しか
示せない。画素 1<!--n:value tried--> nm では、どの方式も繊維の一部を取り除いた（$D$ にわたる範囲、ノイズ
0.05<!--n:value tried--> nm と 0.2<!--n:value tried--> nm）。`trendfill` は 0.13〜0.84<!--m:synthetic_height.px1.trendfill.n0.05.removed_range--> と 0.70〜0.95<!--m:synthetic_height.px1.trendfill.n0.2.removed_range-->、`tophat` は 0.07〜0.53<!--m:synthetic_height.px1.tophat.n0.05.removed_range--> と
0.10〜0.55<!--m:synthetic_height.px1.tophat.n0.2.removed_range-->、`spline1d` は 0.01〜0.46<!--m:synthetic_height.px1.spline1d.n0.05.removed_range--> と 0.38〜0.90<!--m:synthetic_height.px1.spline1d.n0.2.removed_range--> である。これらの実行での
`background_warnings` の成績は §1.10 にある。

### 1.10 予測による背景の警告と実測による背景の警告

`background_warnings`（`lib/pipeline.py`）の警告には 2<!--n:count--> 種類ある。3<!--n:count--> つは見かけ幅を
§1.8 の限界と比べ、高さの損失を予測する。`element_small`、`flank_step_low`、
`width_unchecked` である。残る 2<!--n:count--> つは補正後の画像を測る。`relief_absorbed` は、繊維
マスクの上で、入力が示した起伏の 0.1<!--c:lib/pipeline.py::_MAX_ABSORBED_FRACTION--> 以上が、マスクの脇（マスクから見かけ幅の 2<!--c:lib/pipeline.py::_ABSORBED_RING_WIDTHS--> 倍
以内、幅の 3<!--c:lib/pipeline.py::_ABSORBED_SMOOTH_WIDTHS--> 倍で平均）の背景より高い背景として引かれたときに出る。
`width_unmeasured` は、大半の成分で見かけ幅を測れず、他の検査をどれも行えなかった
ときに出る。2<!--n:count--> つの長さと限界は下の実行を見て選んだので、これらの実行は独立した
検証ではなく開発用のデータである。

高さの 0.1<!--n:definition--> より多くを失った実行を「損失あり」、0.03<!--n:definition--> 未満しか失わなかった実行を
「健全」と数える。

| 実行 | 損失あり | 健全 | 予測: 捉えた | 予測: 健全で出た | 実測: 捉えた | 実測: 健全で出た | いずれか: 捉えた | いずれか: 健全で出た |
|---|---|---|---|---|---|---|---|---|
| 高さが既知の繊維、23<!--n:value tried--> 度（§1.9） | 14<!--m:synthetic_height.lossy--> | 54<!--m:synthetic_height.sound--> | 7<!--m:synthetic_height.predicted.caught--> | 13<!--m:synthetic_height.predicted.false--> | 13<!--m:synthetic_height.measured.caught--> | 0<!--m:synthetic_height.measured.false--> | 14<!--m:synthetic_height.any.caught--> | 13<!--m:synthetic_height.any.false--> |
| 同じ繊維、ノイズ 0.05<!--n:value tried--> nm、4<!--n:count--> 方向 | 19<!--m:synthetic_height_orientation.lossy--> | 110<!--m:synthetic_height_orientation.sound--> | 7<!--m:synthetic_height_orientation.predicted.caught--> | 21<!--m:synthetic_height_orientation.predicted.false--> | 18<!--m:synthetic_height_orientation.measured.caught--> | 1<!--m:synthetic_height_orientation.measured.false--> | 19<!--m:synthetic_height_orientation.any.caught--> | 22<!--m:synthetic_height_orientation.any.false--> |
| 同梱スキャンの拡大画像（§1.8） | 51<!--m:zoomed_background.tally.lossy--> | 27<!--m:zoomed_background.tally.sound--> | 19<!--m:zoomed_background.tally.predicted.caught--> | 3<!--m:zoomed_background.tally.predicted.false--> | 43<!--m:zoomed_background.tally.measured.caught--> | 1<!--m:zoomed_background.tally.measured.false--> | 44<!--m:zoomed_background.tally.any.caught--> | 4<!--m:zoomed_background.tally.any.false--> |

4<!--n:count--> 方向は、走査線に対して 0<!--n:value tried-->、23<!--n:value tried-->、45<!--n:value tried-->、90<!--n:value tried--> 度である（実験 synthetic_height_orientation）。そこで
実測による警告が出た健全な実行は 1<!--m:synthetic_height_orientation.measured.false_axis_parallel--> 回で、繊維は画像の軸に平行である。画素 1<!--n:value tried--> nm で
90<!--n:value tried--> 度、`spline1d` の実行で、幅を測れなかったという警告であった。描いてみると、補正後の
繊維は高さを保っているが、追跡した線がその中で輪や断片に崩れている。したがって、幅を
測れなかったという警告はそこでも正しく、ただ問題は補正の後で起きている。

### 1.11 `tophat` での走査線ごとの段差

`tophat` が取り除く走査線どうしの高さの段差は、`trendfill` より少ない。隣り合う
走査線の段差を、最小二乗の平面を引いたあと、各行の画素のうち低い方の 60<!--n:definition--> % で
行ごとの中央値を取り（繊維を含めないため）、隣り合う行の中央値の差の絶対値の中央値
として測った（実験 line_steps）。

| 走査 | 生 | `trendfill` | `tophat` |
|---|---|---|---|
| 高等植物 TOC | 0.020<!--m:line_steps.hplantTOC.raw_nm--> nm | 0.004<!--m:line_steps.hplantTOC.trendfill_nm--> nm | 0.018<!--m:line_steps.hplantTOC.tophat_nm--> nm |
| ホヤ CNF | 0.044<!--m:line_steps.tunicate.raw_nm--> nm | 0.005<!--m:line_steps.tunicate.trendfill_nm--> nm | 0.013<!--m:line_steps.tunicate.tophat_nm--> nm |
| Bruker NDTOC | 0.042<!--m:line_steps.NDTOC.raw_nm--> nm | 0.007<!--m:line_steps.NDTOC.trendfill_nm--> nm | 0.020<!--m:line_steps.NDTOC.tophat_nm--> nm |

生の段差のうち、`trendfill` は 0.11<!--m:line_steps.trendfill.over_raw_range[0]-->〜0.20<!--m:line_steps.trendfill.over_raw_range[1]-->、`tophat` は 0.30<!--m:line_steps.tophat.over_raw_range[0]-->〜0.93<!--m:line_steps.tophat.over_raw_range[1]--> を残し、`tophat` は
`trendfill` の 2.7<!--m:line_steps.tophat_over_trendfill_range[0]-->〜4.6<!--m:line_steps.tophat_over_trendfill_range[1]--> 倍を残した。背景にコントラストを合わせて描くと、3<!--n:count--> 枚とも
`tophat` の画像には生の走査の横縞が残っており、ホヤのスキャンを横切る暗い帯は
`trendfill` では消え、`tophat` では残る。`background_warnings` は `trendfill` や
`spline1d` が繊維の高さを失うときに `tophat` を勧める（§1.8）。その勧めに従うと、
繊維の高さは保たれる代わりにこれらの縞が残る。

### 1.12 走査軸に沿う細い繊維

`noise_detect_factor` 画素より細く走査軸に沿って走る繊維に背景の繊維マスクが付くのは、
その短い印がなす物体の大きさによってだけであり（[解析アルゴリズム](algorithms.ja.md) §1.3
、`trendfill` の手順 1<!--n:label-->）、1<!--n:count--> 本の走査線でてっぺんが平らに見えるかどうかは、繊維の軸が
画素格子のどこに来るかで決まる。そこで、走査線に対して 0<!--n:value tried-->、1<!--n:value tried-->、3<!--n:value tried-->、10<!--n:value tried-->、23<!--n:value tried-->、45<!--n:value tried-->、90<!--n:value tried-->° の
角度で直線の繊維を描き、それぞれ軸を 2<!--n:count--> 画素の境目、そこから 1/4 画素ずれた位置、
画素の中心に置いた（実験 narrow_axis_fibers）。各走査には、半径 15<!--n:value tried--> nm の球状の
先端で膨張させた円柱から点標本化した繊維を 3<!--n:count--> 本、平面の傾きと画素ノイズ 0.05<!--n:value tried--> nm
または 0.2<!--n:value tried--> nm を加えた 320<!--n:value tried--> × 320<!--n:value tried--> 画素の上に置いた。円柱は、画素 5<!--n:value tried--> nm で直径 4<!--n:value tried--> nm と
8<!--n:value tried--> nm（見かけの幅 3.2<!--m:narrow_axis_fibers.px5.d4.width_px--> 画素と 4.7<!--m:narrow_axis_fibers.px5.d8.width_px--> 画素）、画素 2<!--n:value tried--> nm で直径 2<!--n:value tried--> nm（5.6<!--m:narrow_axis_fibers.px2.d2.width_px--> 画素）である。
すべての角度・位置・繊維・ノイズで、繊維マスクは、それを使う 2<!--n:count--> つの方法のどちらでも
繊維の軸上の画素の 1.00<!--m:narrow_axis_fibers.mask_min--> 以上を覆い、軸上の補正後の高さの中央値は、真の高さの
`trendfill` で 0.985<!--m:narrow_axis_fibers.trendfill.height_min--> 以上、`spline1d` で 0.950<!--m:narrow_axis_fibers.spline1d.height_min--> 以上であった。

## 2. 二値化

[解析アルゴリズム](algorithms.ja.md) §2 を参照。

### 2.1 直線性フィルタのエッジマップ

1.0.0 までは、外接矩形内のマスク全体からエッジマップを作っていた。同梱
スキャン 3<!--m:hough_edge_map.identical--> 枚すべてで、最終的な二値化マスクはどちらでもビット単位で一致する
（実験 hough_edge_map）。

### 2.2 リッジ回収

チュニケートの走査では、二値化マスクから 10<!--n:value tried--> px 以上離れた画素の
99.8<!--m:ridge_hysteresis.ridge.far_below_low_percent--> % が、リッジ応答のヒステリシスの低い側のレベルを下回る（実験
ridge_hysteresis）。

### 2.3 Closing

closing は、厚さ 3<!--n:value tried--> px 以上のマスク成分どうしを 2<!--m:closing_gaps.thick3.largest_gap_joined_px--> px までの隙間越しに
つなぐが、厚さ 1<!--n:value tried--> px の線どうしはつながない（試した 3<!--n:count--> 通りの隙間で
0<!--m:closing_gaps.thick1.gaps_joined--> 件。実験 closing_gaps）。

### 2.4 局所しきい値

ほかはすべて既定値のまま、全体のしきい値だけで二値化すると、マスクは次のように
変わる（実験 local_threshold）。マスクの平均の幅は、最終的なマスクの面積を最終的な
スケルトンの長さで割ったものである。2<!--n:count--> つの高さは中央値で、3<!--n:definition--> px 以内でいちばん
高い高さに対する百分率である。

| スキャン | マスクの平均の幅、全体のみ → 両方 (px) | マスクのかたまりの数 | 最終スケルトンの分岐点 | 局所しきい値が落とす画素 / 残す画素の高さ (%) |
|---|---|---|---|---|
| チュニケート CNF | 15.6<!--m:local_threshold.tunicate.global.mask_width_px--> → 10.1<!--m:local_threshold.tunicate.both.mask_width_px--> | 1<!--m:local_threshold.tunicate.global.mask_components--> → 11<!--m:local_threshold.tunicate.both.mask_components--> | 69<!--m:local_threshold.tunicate.global.branch_points--> → 33<!--m:local_threshold.tunicate.both.branch_points--> | 25<!--m:local_threshold.tunicate.removed_percent_of_crest--> / 83<!--m:local_threshold.tunicate.kept_percent_of_crest--> |
| 高等植物 TOC | 12.6<!--m:local_threshold.hplantTOC.global.mask_width_px--> → 8.9<!--m:local_threshold.hplantTOC.both.mask_width_px--> | 8<!--m:local_threshold.hplantTOC.global.mask_components--> → 8<!--m:local_threshold.hplantTOC.both.mask_components--> | 6<!--m:local_threshold.hplantTOC.global.branch_points--> → 5<!--m:local_threshold.hplantTOC.both.branch_points--> | 34<!--m:local_threshold.hplantTOC.removed_percent_of_crest--> / 75<!--m:local_threshold.hplantTOC.kept_percent_of_crest--> |
| Bruker NDTOC | 12.9<!--m:local_threshold.NDTOC.global.mask_width_px--> → 9.5<!--m:local_threshold.NDTOC.both.mask_width_px--> | 22<!--m:local_threshold.NDTOC.global.mask_components--> → 24<!--m:local_threshold.NDTOC.both.mask_components--> | 156<!--m:local_threshold.NDTOC.global.branch_points--> → 75<!--m:local_threshold.NDTOC.both.branch_points--> | 35<!--m:local_threshold.NDTOC.removed_percent_of_crest--> / 72<!--m:local_threshold.NDTOC.kept_percent_of_crest--> |

同梱スキャン 3<!--m:kink_reference.scans--> 枚すべての高さ画像に重ねて描くと、局所しきい値が落とす画素は、繊維の斜面の下のほうである。繊維が 1<!--n:count--> 本だけで離れている場所では、
マスクが細くなるだけである。次に書くつながりが見られたのは、繊維が近くを並んで
走るか、背景に凹凸のある、チュニケートと Bruker のスキャンである。全体のしきい値だけでは、近くを並んで走る
2<!--n:count--> 本の繊維が斜面どうしでつながって 1<!--n:count--> つのかたまりになり、スケルトンがその間を
通った。チュニケートのスキャンでは、網目全体がひとつのかたまりになった。Bruker の
スキャンでは、背景のミミズ状の凹凸が繊維の斜面に触れて繊維のマスクとつながり、
スケルトンに横枝を残した。局所しきい値を加えると、そうした凹凸は繊維から離れ、
二値化の後段のフィルタで取り除かれた。

### 2.5 直線性フィルタ

3<!--m:linearity_filter.inputs--> 個のテスト入力（実験 linearity_filter）で、$s_{	ext{ratio}}$ は最大 5.16<!--m:linearity_filter.s_ratio_max--> に
なり、$s_{	ext{ratio}} > 1$ となったかたまりは 154<!--m:linearity_filter.s_ratio_above_one--> 個あった。フィルタが消したかたまりのうち、
最大の差し渡しが `h_length` に届くものは 161<!--m:linearity_filter.removed_reaching_h_length--> 個で、すべてを補正後の高さ画像に
重ねて描き、目で判断した。ほとんどは背景の凹凸、粒子、高等植物のスキャンの
走査線のグリッチであったが、2<!--m:linearity_filter.removed_fiber_pieces--> 個は本物の繊維の片であった。チュニケートの
スキャンで画像の端に届く曲がった短い片と、Bruker のスキャンで画像の端に切られた繊維の
端である。

行の向きに走る合成の帯（面積 865<!--m:linearity_filter.band.horizontal.area--> 画素）では、囲む長方形で切り出した画像の
中に Canny が見つけた輪郭は、フィルタが付ける 1<!--n:literal in the quoted code--> 画素の余白ありで 264<!--m:linearity_filter.band.horizontal.edge_pixels--> 画素、
余白なしで 14<!--m:linearity_filter.band.horizontal.edge_pixels_unpadded--> 画素（すべて丸い両端）であった。点数は 1.39<!--m:linearity_filter.band.horizontal.s_ratio--> で、帯は残った。
同じ帯を 45<!--n:definition--> 度に傾けると（面積 620<!--m:linearity_filter.band.diagonal.area--> 画素）、輪郭は 364<!--m:linearity_filter.band.diagonal.edge_pixels--> 画素
（余白なしで 356<!--m:linearity_filter.band.diagonal.edge_pixels_unpadded--> 画素）、点数は 1.81<!--m:linearity_filter.band.diagonal.s_ratio--> で、帯は残った。

Bruker スキャン上の、1000<!--n:literal in the quoted code--> px 未満ではっきり見える繊維のうち最もまっすぐな 2<!--n:count--> 本を
（実験 linearity_axis_fibers）、走査したままの向きと、走査全体を回して各繊維のかたまりの
主軸が列に沿うようにした向き、さらに 90<!--n:definition--> 度回して行に沿うようにした向きで解析した。
5<!--n:label--> 列目は、輪郭のうち囲む長方形の辺の上にある画素の数で、Canny がこれを見つけられるのは
余白があるからである。フィルタが検査した場合は、どれも残した。

| 繊維 | 向き | 面積 (px) | 輪郭の画素 | うち長方形の辺の上 | $s_{	ext{ratio}}$ |
|---|---|---|---|---|---|
| 1<!--n:label--> 本目 | 走査したまま、主軸 91.1<!--m:linearity_axis_fibers.a.original_axis_deg--> 度 | 871<!--m:linearity_axis_fibers.a.original.area--> | 300<!--m:linearity_axis_fibers.a.original.outline_px--> | 22<!--m:linearity_axis_fibers.a.original.outline_on_box_sides_px--> | 2.52<!--m:linearity_axis_fibers.a.original.s_ratio--> |
| 2<!--n:label--> 本目 | 走査したまま、主軸 63.4<!--m:linearity_axis_fibers.b.original_axis_deg--> 度 | 482<!--m:linearity_axis_fibers.b.original.area--> | 177<!--m:linearity_axis_fibers.b.original.outline_px--> | 18<!--m:linearity_axis_fibers.b.original.outline_on_box_sides_px--> | 1.28<!--m:linearity_axis_fibers.b.original.s_ratio--> |
| 2<!--n:label--> 本目 | 列に沿う向き | 574<!--m:linearity_axis_fibers.b.columns.area--> | 247<!--m:linearity_axis_fibers.b.columns.outline_px--> | 36<!--m:linearity_axis_fibers.b.columns.outline_on_box_sides_px--> | 1.83<!--m:linearity_axis_fibers.b.columns.s_ratio--> |
| 2<!--n:label--> 本目 | 行に沿う向き | 685<!--m:linearity_axis_fibers.b.rows.area--> | 339<!--m:linearity_axis_fibers.b.rows.outline_px--> | 19<!--m:linearity_axis_fibers.b.rows.outline_on_box_sides_px--> | 3.16<!--m:linearity_axis_fibers.b.rows.s_ratio--> |

1<!--n:label--> 本目は、回すと脇の背景の凹凸とつながり、かたまりは 1349<!--m:linearity_axis_fibers.a.columns.area--> px と 1367<!--m:linearity_axis_fibers.a.rows.area--> px になった。
フィルタはこの大きさを検査しない。どちらの繊維も、どの向きでも最終の二値化マスクに
残った（補正後の画像で確認した）。対象は 1<!--n:count--> 枚のスキャンの 2<!--n:count--> 本である。

まっすぐな形の判定が、それでも角度にどれだけ左右されるかを、両端の丸い合成の棒で
測った。0<!--n:value tried--> 度から 90<!--n:value tried--> 度まで 5<!--n:value tried--> 度ごとに、それぞれ画素以下の位置をランダムに
3<!--n:value tried--> 通りずらして描き、1<!--n:count--> 本ずつフィルタに通した（実験 linearity_rotated_rods）。表は、各棒の
57<!--m:linearity_rotated_rods.placements--> 通りの置き方のうち、残った数である。

| 幅 (px) | 長さ 16<!--n:value tried--> px | 20<!--n:value tried--> | 22<!--n:value tried--> | 24<!--n:value tried--> | 26<!--n:value tried--> | 28<!--n:value tried--> | 32<!--n:value tried--> | 40<!--n:value tried--> |
|---|---|---|---|---|---|---|---|---|
| 3<!--n:value tried--> | 0<!--m:linearity_rotated_rods.w3.l16.kept--> | 20<!--m:linearity_rotated_rods.w3.l20.kept--> | 46<!--m:linearity_rotated_rods.w3.l22.kept--> | 57<!--m:linearity_rotated_rods.w3.l24.kept--> | 57<!--m:linearity_rotated_rods.w3.l26.kept--> | 57<!--m:linearity_rotated_rods.w3.l28.kept--> | 57<!--m:linearity_rotated_rods.w3.l32.kept--> | 57<!--m:linearity_rotated_rods.w3.l40.kept--> |
| 5<!--n:value tried--> | 0<!--m:linearity_rotated_rods.w5.l16.kept--> | 12<!--m:linearity_rotated_rods.w5.l20.kept--> | 37<!--m:linearity_rotated_rods.w5.l22.kept--> | 52<!--m:linearity_rotated_rods.w5.l24.kept--> | 56<!--m:linearity_rotated_rods.w5.l26.kept--> | 57<!--m:linearity_rotated_rods.w5.l28.kept--> | 57<!--m:linearity_rotated_rods.w5.l32.kept--> | 57<!--m:linearity_rotated_rods.w5.l40.kept--> |
| 7<!--n:value tried--> | 0<!--m:linearity_rotated_rods.w7.l16.kept--> | 8<!--m:linearity_rotated_rods.w7.l20.kept--> | 22<!--m:linearity_rotated_rods.w7.l22.kept--> | 50<!--m:linearity_rotated_rods.w7.l24.kept--> | 56<!--m:linearity_rotated_rods.w7.l26.kept--> | 57<!--m:linearity_rotated_rods.w7.l28.kept--> | 57<!--m:linearity_rotated_rods.w7.l32.kept--> | 57<!--m:linearity_rotated_rods.w7.l40.kept--> |
| 9<!--n:value tried--> | 0<!--m:linearity_rotated_rods.w9.l16.kept--> | 5<!--m:linearity_rotated_rods.w9.l20.kept--> | 11<!--m:linearity_rotated_rods.w9.l22.kept--> | 30<!--m:linearity_rotated_rods.w9.l24.kept--> | 52<!--m:linearity_rotated_rods.w9.l26.kept--> | 57<!--m:linearity_rotated_rods.w9.l28.kept--> | 57<!--m:linearity_rotated_rods.w9.l32.kept--> | 57<!--m:linearity_rotated_rods.w9.l40.kept--> |

棒は、幅 3<!--n:value tried--> px では長さ 24<!--m:linearity_rotated_rods.w3.shortest_always_kept--> px から、ほかの幅では 28<!--m:linearity_rotated_rods.w9.shortest_always_kept--> px から、どの置き方でも
残り、長さ 16<!--m:linearity_rotated_rods.w9.longest_never_kept--> px ではどの置き方でも残らなかった。その間の長さでは、残るかどうかが
角度と置き方で変わった。

### 2.6 直線性フィルタが検査しないかたまり

直線性フィルタは、面積 1000<!--n:literal in the quoted code--> 画素以上のかたまりを検査せずに残す。各テスト入力を、
コードのとおりの場合と、すべてのかたまりを検査する場合とでフィルタにかけた（実験
linearity_large_exemption。両方の実行時間も記録している）。

| 入力 | 1000<!--n:literal in the quoted code--> px 以上のかたまり | そのうち検査すると消えるもの |
|---|---|---|
| チュニケート CNF | 9<!--m:linearity_large_exemption.tunicate.large_components--> | 0<!--m:linearity_large_exemption.tunicate.large_removed_if_tested--> |
| 高等植物 TOC | 4<!--m:linearity_large_exemption.hplantTOC.large_components--> | 0<!--m:linearity_large_exemption.hplantTOC.large_removed_if_tested--> |
| Bruker NDTOC | 15<!--m:linearity_large_exemption.NDTOC.large_components--> | 0<!--m:linearity_large_exemption.NDTOC.large_removed_if_tested--> |
どの入力でも、大きなかたまりを検査して消えるものは無かった。一方、検査すると
フィルタの時間は数倍になり、チュニケートのスキャンでは十倍を超えた。大きな
切り出しの Hough 変換は時間がかかるからである。ただし、大きな汚れのかたまりのような、
線の形をしていない大きなものも、検査されずに残る。

## 3. 細線化

[解析アルゴリズム](algorithms.ja.md) §3 を参照。

### 3.1 画像端での細線化

同梱スキャンでは、端を複製しない場合、画像の外へ抜けるトラックの最後の
5<!--n:definition--> 点が、法線方向に測って高さの稜線から中央値で 3.9<!--m:border_drift.plain.end_median_px--> px 離れており、繊維の
中ほどの 0.9<!--m:border_drift.plain.middle_median_px--> px と対比される。複製すると、端の点は稜線から 1.1<!--m:border_drift.padded.end_median_px--> px になる
（実験 border_drift）。12<!--c:lib/skeletonizer.py::DEFAULT_BORDER_PAD--> px の縁帯より内側のスケルトンは、同梱スキャン
3<!--m:border_padding.identical_inside_band--> 枚すべてで本補正の有無によらず完全に一致した（実験 border_padding）。ただし
これは保証ではない。

### 3.2 `bp_height` と繊維の高さ

既定の `bp_height` 10<!--c:lib/pipeline.py::ProcParams.bp_height--> nm は、どの同梱スキャンでもスケルトン下の高さの
中央値（1.7<!--m:bg_stats.hplantTOC.skeleton_height_median_nm-->〜7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> nm、§1.1）より高い。最初のスケルトンの分岐点の高さ
（実験 branch_pruning）は、チュニケートのスキャンでは中央値 9.2<!--m:branch_pruning.tunicate.bp_height_median_nm--> nm で、分岐点の
41<!--m:branch_pruning.tunicate.bp_at_or_above_percent--> % が `bp_height` に届く。ほかのスキャンではひとつも届かない（中央値は高等植物の
スキャンで 1.8<!--m:branch_pruning.hplantTOC.bp_height_median_nm--> nm、Bruker のスキャンで 2.0<!--m:branch_pruning.NDTOC.bp_height_median_nm--> nm）。そこではすべての分岐点が「低い」になり、高さによる区別は何もしない。

チュニケートの高さ画像に重ねて描くと、`bp_height` 以上の分岐点は、2<!--n:count--> 本の繊維が
交差する場所か、1<!--n:count--> 本がもう 1<!--n:count--> 本に合流する場所にある。重なった 2<!--n:count--> 本の繊維の高さが
足し合わされる場所である。それより低い分岐点にも、交差や合流が含まれる。たとえば
スキャンの下部の絡まりにある、細い繊維どうしの交差である。そのため、このスキャン
では、分岐点が低いことは偽の枝であることの印にならない。

高さで決める枝刈りは、最終的なスケルトンをほとんど変えない。この処理を外すと、
変わるスケルトンの画素は、チュニケートのスキャンで 8077<!--m:branch_pruning.tunicate.final_pixels--> 画素のうち 1<!--m:branch_pruning.tunicate.skipped.final_changed_pixels--> 画素、
高等植物のスキャンで 1908<!--m:branch_pruning.hplantTOC.final_pixels--> 画素のうち 10<!--m:branch_pruning.hplantTOC.skipped.final_changed_pixels--> 画素、Bruker のスキャンで 9195<!--m:branch_pruning.NDTOC.final_pixels--> 画素のうち
194<!--m:branch_pruning.NDTOC.skipped.final_changed_pixels--> 画素である。すべての分岐点を「低い」として扱っても、
チュニケートのスキャンで変わる画素は 0<!--m:branch_pruning.tunicate.all_low.final_changed_pixels--> である。この処理が刈る短い腕は、
[解析アルゴリズム](algorithms.ja.md) §3.5 のとげ刈りが、長さだけで判断してもう一度
刈るからである。とげ刈りを止めると、この処理を外したときに変わる画素は、同じ 3<!--n:count--> 枚の
スキャンでそれぞれ 133<!--m:branch_pruning.tunicate.spurs_off.skipped.final_changed_pixels-->、154<!--m:branch_pruning.hplantTOC.spurs_off.skipped.final_changed_pixels-->、966<!--m:branch_pruning.NDTOC.spurs_off.skipped.final_changed_pixels--> 画素になる。

### 3.3 ループの囲み

同梱スキャンでは、マスク内部の穴が残すループ 1<!--n:count--> つが、その輪の上に分岐点を
1<!--m:loop_candidates.all.branch_points_range[0]-->〜4<!--m:loop_candidates.all.branch_points_range[1]--> 個作る。充填の大きさの条件を満たす 19<!--m:loop_candidates.candidates--> 個の囲みを高さ画像で
目視すると、8<!--m:loop_candidates.fiber.count--> 個は繊維の内側に、9<!--m:loop_candidates.crossing.count--> 個は交差にあり、tunicate のスキャンの
1<!--m:loop_candidates.gap.count--> 個は、別々の 2<!--n:count--> 本の繊維が囲む細長い隙間であった。2<!--n:count--> 本は溝をはさんで並び、
両端で接している。残る 1<!--m:loop_candidates.particle.count--> 個は Bruker のスキャンで、淡い筋の端にある粒子の内側にある。内部の高さの中央値は、どの囲みでも周囲リッジの中央値の
83<!--m:loop_candidates.all.ratio_percent_range[0]-->〜105<!--m:loop_candidates.all.ratio_percent_range[1]--> % であり、隙間の 83<!--m:loop_candidates.gap.ratio_percent_range[0]--> % もこの範囲に、繊維の内側にあるループのアーティファクトの
ひとつのすぐ上に入る（実験 loop_candidates）。そのため、この比の
しきい値では、ループのアーティファクトをすべて塗りつぶしつつ隙間だけを残すことは
できない。実際に隙間も塗りつぶされ、描いてみると、2<!--n:count--> 本の繊維は溝の中を通る
1<!--n:count--> 本の線にまとめられていた。そうした隙間は、合成画像でも作った（§3.4）。

### 3.4 2 本の繊維が囲む細長い隙間

まっすぐな 2<!--n:count--> 本の繊維がレンズ形の隙間をはさんで分かれ、また合わさる合成画像
24<!--m:loop_sliver.scans--> 枚（断面は高さ 4<!--n:value tried--> nm、標準偏差 1.5<!--n:value tried-->・2<!--n:value tried-->・3<!--n:value tried--> px のガウス形、隙間の幅は 4<!--n:value tried-->〜12<!--n:value tried--> px。
実験 loop_sliver）では、`collapse_skeleton_loops` が調べる大きさの囲みが 4<!--m:loop_sliver.candidates--> 個できた。
内側の高さの中央値は、周りの尾根の 63<!--m:loop_sliver.ratio_percent_range[0]-->〜98<!--m:loop_sliver.ratio_percent_range[1]--> % であった。近い 2<!--n:count--> 本の繊維の斜面が
重なるからである。そのため 4<!--m:loop_sliver.filled--> 個とも 0.3<!--c:lib/skeletonizer.py::DEFAULT_LOOP_HEIGHT_RATIO--> のチェックを通って塗りつぶされ、描いて
みると、2<!--n:count--> 本の繊維は隙間の真ん中を通る 1<!--n:count--> 本の線にまとめられていた。隙間がもっと
広いと、囲みが `max_loop_area` より大きくなり、2<!--n:count--> 本のまま残った。これらの画像では、
このチェックが塗りつぶしを止めたことは 1<!--n:count--> 度も無かった。

### 3.5 2 つの刈り取りの端の幅

枝刈り（解析アルゴリズムの §3.3）は、画像の端から `branch_length`（12<!--c:lib/pipeline.py::ProcParams.branch_length--> px）以内の端点を
調べず、とげ刈り（同 §3.5）は、端から 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px 以内の腕を刈らない。各テスト入力を、片方の
幅を相手の値に変えて 1<!--n:count--> つずつ細線化した（実験 border_margins）。

| 入力 | 枝刈りを 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px にしたとき変わった画素 | 端からの最大の距離 (px) | とげ刈りを 12<!--c:lib/pipeline.py::ProcParams.branch_length--> px にしたとき変わった画素 | 端からの最大の距離 (px) |
|---|---|---|---|---|
| チュニケート CNF | 0<!--m:border_margins.tunicate.branch_margin_2.changed_px--> | 0<!--m:border_margins.tunicate.branch_margin_2.farthest_from_border_px--> | 8<!--m:border_margins.tunicate.spur_margin_wide.changed_px--> | 12<!--m:border_margins.tunicate.spur_margin_wide.farthest_from_border_px--> |
| 高等植物 TOC | 0<!--m:border_margins.hplantTOC.branch_margin_2.changed_px--> | 0<!--m:border_margins.hplantTOC.branch_margin_2.farthest_from_border_px--> | 0<!--m:border_margins.hplantTOC.spur_margin_wide.changed_px--> | 0<!--m:border_margins.hplantTOC.spur_margin_wide.farthest_from_border_px--> |
| Bruker NDTOC | 8<!--m:border_margins.NDTOC.branch_margin_2.changed_px--> | 7<!--m:border_margins.NDTOC.branch_margin_2.farthest_from_border_px--> | 21<!--m:border_margins.NDTOC.spur_margin_wide.changed_px--> | 13<!--m:border_margins.NDTOC.spur_margin_wide.farthest_from_border_px--> |
描いてみると、枝刈りの幅を狭めると、端へ向かう短い腕が刈られた。とげ刈りの幅を
広げると、コードでは刈られる、端のすぐそばの短いとげが残った。どちらの場合も、
変化は端に沿った帯の中に収まる。2<!--n:count--> つの幅が違う理由は見つからなかった。

### 3.6 分岐点探索の斜め Y カーネル

`imp_tools.branchedPoints` は骨格をヒットオアミスのカーネルと照合する。その
1<!--n:count--> つである斜め Y カーネルは、9<!--n:definition--> マスのうち 4<!--n:definition--> マスを任意として、軸に沿ったカーネルが
取りこぼす角度の Y 分岐を拾う。各テスト入力の既定の骨格で（実験 diagonal_ybranch）、
113<!--m:diagonal_ybranch.all.branch_points--> 個の分岐点のうち 52<!--m:diagonal_ybranch.all.only_diagonal_y--> 個はこのカーネルだけが見つけた。チュニケートのスキャンでは
33<!--m:diagonal_ybranch.tunicate.branch_points--> 個中 15<!--m:diagonal_ybranch.tunicate.only_diagonal_y--> 個、高等植物 TOC のスキャンでは 5<!--m:diagonal_ybranch.hplantTOC.branch_points--> 個中 3<!--m:diagonal_ybranch.hplantTOC.only_diagonal_y--> 個、Bruker のスキャンでは 75<!--m:diagonal_ybranch.NDTOC.branch_points--> 個中 34<!--m:diagonal_ybranch.NDTOC.only_diagonal_y--> 個
である。このカーネルだけが見つけた画素は、どれも
8<!--n:definition--> 連結の骨格近傍を 3<!--n:definition--> つ以上持ち（それより少ない画素: 0<!--m:diagonal_ybranch.all.only_diagonal_y_below_3_neighbours--> 個）、近傍が 2<!--n:definition--> つである
骨格の素直な区間には 1<!--n:count--> つも無い。

## 4. 中心線とキンク

[解析アルゴリズム](algorithms.ja.md) §4 を参照。

### 4.1 Y 字分岐の下のまっすぐな繊維

同梱の高等植物 TOC スキャンでは、Y 字分岐の下で、実際には折れていない繊維の
スケルトンを、以前の折れ線規則が 118<!--m:y_branch_kink.old_rule_angle_deg--> 度の「キンク」と読んでいた。中心線上で
判定する現在の規則がその 1<!--n:count--> 幅以内に報告するキンクは 0<!--m:y_branch_kink.current_kinks_within_one_width--> 件である（実験
y_branch_kink）。

### 4.2 半値中点と 1/4 幅を選んだ理由

既定の中心線 `"half_max_025w"` は、この節と次の節の比較から選んだ。

**なぜ半値中点か。** すぐ思いつく代替案は各断面の頂点（最大値の位置）だが、
断面が異方的なフィブリルは、ねじれに伴って最も高い縁を左右交互に向ける。合成
データ一式のねじれリボン 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> 本（直線の軸に沿った 4<!--n:value tried-->×2<!--n:value tried-->〜16<!--n:value tried-->×3<!--n:value tried--> nm の
長方形断面、探針 10<!--c:scripts/synthetic_suite.py::RIBBON_TIP_NM--> nm で描画）では、測った 3<!--n:count--> 本の線（既定の線、1/4 高さの
中点、頂点）のうち頂点が 4<!--m:synthetic_centerline.ribbons.crest_farthest_of_three--> 本で軸から最も離れた。頂点の横方向のずれの二乗平均平方根は
既定の線の 0.99<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->〜1.48<!--m:synthetic_centerline.ribbons.crest_over_default_range[1]--> 倍で、例外は 0.99<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]--> 倍の、150<!--n:value tried--> nm ごとにねじれる 10<!--n:value tried-->×3<!--n:value tried--> nm の
リボン（一式の中で最も短いねじれ周期）であった。またキンク規則が、円形の
対照繊維を含むリボンの走査 6<!--m:synthetic_centerline.ribbons.count--> 枚で報告したキンクは 0<!--m:synthetic_centerline.ribbons.kinks_reported--> 件であった（実験
synthetic_centerline）。半値より低いレベルが一様に良かったわけではない。1/4 高さの
中点はリボン 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> 本中 4<!--m:synthetic_centerline.ribbons.quarter_closer_than_default--> 本で既定の線より軸に近かったが、細い円形の対照繊維
では背景の凹凸に最大 3.6<!--m:synthetic_centerline.G_circle_d3.max_nm.quarter_max--> nm 引き寄せられた。

**探針の先端。** 揺れが探針によってどう変わるかを、次のように確かめた。
リボンのうち 3<!--n:count--> 本（16<!--n:value tried-->×3<!--n:value tried-->、10<!--n:value tried-->×3<!--n:value tried-->、6<!--n:value tried-->×2<!--n:value tried--> nm、ねじれの周期 300<!--n:value tried--> nm）を、雑音・傾き・
凹凸なしで描き、先端半径 0<!--n:value tried-->（膨張なし）、10<!--n:value tried-->、40<!--n:value tried--> nm の球状の探針で膨張させて、
真の軸の画素トラックの上に各中心線を置いた（実験 ribbon_tip_swing）。表は、トラックの
中ほどでの軸からの横方向のずれの二乗平均平方根（nm）である。

| リボン (nm) | 先端半径 (nm) | 既定の線 | 1/4 高さの中点 | 重心 | 頂点 |
|---|---|---|---|---|---|
| 16<!--n:value tried-->×3<!--n:value tried--> | 0<!--n:value tried--> | 1.48<!--m:ribbon_tip_swing.16x3.R0.half_max_025w.rms_nm--> | 0.69<!--m:ribbon_tip_swing.16x3.R0.quarter_max.rms_nm--> | 1.11<!--m:ribbon_tip_swing.16x3.R0.centroid.rms_nm--> | 2.99<!--m:ribbon_tip_swing.16x3.R0.crest.rms_nm--> |
| 16<!--n:value tried-->×3<!--n:value tried--> | 10<!--n:value tried--> | 3.40<!--m:ribbon_tip_swing.16x3.R10.half_max_025w.rms_nm--> | 2.37<!--m:ribbon_tip_swing.16x3.R10.quarter_max.rms_nm--> | 2.88<!--m:ribbon_tip_swing.16x3.R10.centroid.rms_nm--> | 4.49<!--m:ribbon_tip_swing.16x3.R10.crest.rms_nm--> |
| 16<!--n:value tried-->×3<!--n:value tried--> | 40<!--n:value tried--> | 3.31<!--m:ribbon_tip_swing.16x3.R40.half_max_025w.rms_nm--> | 3.24<!--m:ribbon_tip_swing.16x3.R40.quarter_max.rms_nm--> | 3.23<!--m:ribbon_tip_swing.16x3.R40.centroid.rms_nm--> | 3.24<!--m:ribbon_tip_swing.16x3.R40.crest.rms_nm--> |
| 10<!--n:value tried-->×3<!--n:value tried--> | 0<!--n:value tried--> | 0.74<!--m:ribbon_tip_swing.10x3.R0.half_max_025w.rms_nm--> | 0.45<!--m:ribbon_tip_swing.10x3.R0.quarter_max.rms_nm--> | 0.66<!--m:ribbon_tip_swing.10x3.R0.centroid.rms_nm--> | 1.82<!--m:ribbon_tip_swing.10x3.R0.crest.rms_nm--> |
| 10<!--n:value tried-->×3<!--n:value tried--> | 10<!--n:value tried--> | 1.97<!--m:ribbon_tip_swing.10x3.R10.half_max_025w.rms_nm--> | 1.54<!--m:ribbon_tip_swing.10x3.R10.quarter_max.rms_nm--> | 1.75<!--m:ribbon_tip_swing.10x3.R10.centroid.rms_nm--> | 2.67<!--m:ribbon_tip_swing.10x3.R10.crest.rms_nm--> |
| 10<!--n:value tried-->×3<!--n:value tried--> | 40<!--n:value tried--> | 2.05<!--m:ribbon_tip_swing.10x3.R40.half_max_025w.rms_nm--> | 1.96<!--m:ribbon_tip_swing.10x3.R40.quarter_max.rms_nm--> | 1.99<!--m:ribbon_tip_swing.10x3.R40.centroid.rms_nm--> | 2.08<!--m:ribbon_tip_swing.10x3.R40.crest.rms_nm--> |
| 6<!--n:value tried-->×2<!--n:value tried--> | 0<!--n:value tried--> | 0.48<!--m:ribbon_tip_swing.6x2.R0.half_max_025w.rms_nm--> | 0.37<!--m:ribbon_tip_swing.6x2.R0.quarter_max.rms_nm--> | 0.43<!--m:ribbon_tip_swing.6x2.R0.centroid.rms_nm--> | 0.83<!--m:ribbon_tip_swing.6x2.R0.crest.rms_nm--> |
| 6<!--n:value tried-->×2<!--n:value tried--> | 10<!--n:value tried--> | 1.25<!--m:ribbon_tip_swing.6x2.R10.half_max_025w.rms_nm--> | 1.06<!--m:ribbon_tip_swing.6x2.R10.quarter_max.rms_nm--> | 1.16<!--m:ribbon_tip_swing.6x2.R10.centroid.rms_nm--> | 1.64<!--m:ribbon_tip_swing.6x2.R10.crest.rms_nm--> |
| 6<!--n:value tried-->×2<!--n:value tried--> | 40<!--n:value tried--> | 1.32<!--m:ribbon_tip_swing.6x2.R40.half_max_025w.rms_nm--> | 1.27<!--m:ribbon_tip_swing.6x2.R40.quarter_max.rms_nm--> | 1.29<!--m:ribbon_tip_swing.6x2.R40.centroid.rms_nm--> | 1.37<!--m:ribbon_tip_swing.6x2.R40.crest.rms_nm--> |

頂点に比べると、既定の線のずれは、膨張なしで 0.41<!--m:ribbon_tip_swing.R0.default_over_crest_range[0]-->〜0.58<!--m:ribbon_tip_swing.R0.default_over_crest_range[1]--> 倍、先端半径 10<!--n:value tried--> nm で
0.74<!--m:ribbon_tip_swing.R10.default_over_crest_range[0]-->〜0.76<!--m:ribbon_tip_swing.R10.default_over_crest_range[1]--> 倍、40<!--n:value tried--> nm で 0.97<!--m:ribbon_tip_swing.R40.default_over_crest_range[0]-->〜1.02<!--m:ribbon_tip_swing.R40.default_over_crest_range[1]--> 倍であった。40<!--n:value tried--> nm では、既定の線、1/4 高さの
中点、重心のずれは、どれも頂点の 0.93<!--m:ribbon_tip_swing.R40.height_lines_over_crest_range[0]-->〜1.02<!--m:ribbon_tip_swing.R40.height_lines_over_crest_range[1]--> 倍になった。試したこの 3<!--n:count--> 本のリボンと 3<!--n:count--> つの先端半径では、探針の先端が
太いほど、この 3<!--n:count--> つの線の揺れは頂点の揺れに近づいた。

**なぜ 1/4 幅か。** 平滑化の幅は、2<!--n:count--> つの特徴がどこまで近づくと中心線がそれらを
1<!--n:count--> つに均してしまうかを決める。合成データ一式の同じ向きのコーナー対で調べた。
8<!--m:synthetic_centerline.pairs--> 枚の走査のそれぞれに、1〜3<!--n:value tried--> $W$ 離れた 60<!--n:value tried--> 度のコーナーが 2<!--n:count--> つある。

| 枠とオフセットの平滑化 | 1<!--n:count--> つの折れと判定された組 | コーナー頂点から中心線までの距離（中央値。間隔ごとの範囲） | 真の中心線までの距離（中央値） |
|---|---|---|---|
| $W/2$ | 8<!--m:synthetic_centerline.pairs--> 組中 2<!--m:synthetic_centerline.pairs_w2.merged_pairs--> 組 | 0.94<!--m:synthetic_centerline.pairs_w2.vertex_median_px_range[0]-->〜1.13<!--m:synthetic_centerline.pairs_w2.vertex_median_px_range[1]--> px | 0.11<!--m:synthetic_centerline.pairs_w2.centerline_median_px--> px |
| $W/4$（既定） | 8<!--m:synthetic_centerline.pairs--> 組中 1<!--m:synthetic_centerline.pairs_w4.merged_pairs--> 組 | 0.59<!--m:synthetic_centerline.pairs_w4.vertex_median_px_range[0]-->〜0.89<!--m:synthetic_centerline.pairs_w4.vertex_median_px_range[1]--> px | 0.11<!--m:synthetic_centerline.pairs_w4.centerline_median_px--> px |

**既知の中心線に対する精度。** 合成データ一式の A〜F 群の走査 60<!--m:synthetic_centerline.scans_af--> 枚（球状の探針で
描画。コーナー、ジグザグ、コーナー対、端に近いコーナー、直線、円弧、蛇行、交差、
分岐）で比べた結果は次のとおりである。

| | 真の中心線までの距離（中央値） | 同 95<!--n:definition--> パーセンタイル | 輪郭長の誤差（スキャン群ごとの範囲） |
|---|---|---|---|
| 半値中点の中心線 | 0.11<!--m:synthetic_centerline.half_max_025w.median_px--> px | 0.37<!--m:synthetic_centerline.half_max_025w.p95_px--> px | −0.5<!--m:synthetic_centerline.half_max_025w.length_error_percent_range[0]-->〜+2.3<!--m:synthetic_centerline.half_max_025w.length_error_percent_range[1]--> % |
| スケルトントラック（補正済みチェーンコード長） | 0.29<!--m:synthetic_centerline.skeleton_track.median_px--> px | 0.90<!--m:synthetic_centerline.skeleton_track.p95_px--> px | −0.5<!--m:synthetic_centerline.skeleton_track.length_error_percent_range[0]-->〜+3.8<!--m:synthetic_centerline.skeleton_track.length_error_percent_range[1]--> % |

輪郭長の誤差は、計測した中心線の両端に最も近い真の中心線上の点どうしの間で測って
いるので、端で増えたり減ったりする長さを含まない。それは §4.14 で測った。

これらは中心線とキンク規則を選んだときの場面である（`scripts/synthetic_suite.py`）。
したがって §4.4 の目視基準と同じく、独立した検証ではなく開発用のデータである。

### 4.3 選べる中心線の比較

表を読むときは 2<!--n:count--> 点に注意してほしい。

- **距離の中央値**は、合成データ一式の A〜F 群の群ごとに求めた、真の中心線まで
  の距離の中央値（nm）であり、欄には群全体での範囲を示す（実験
  synthetic_centerline）。
- **実スキャン**は、目視基準に対し超過回転規則で採点した結果で、「検出 /
  見落とし / どの印とも一致しない折れ」の件数である。印から 1〜2<!--n:definition--> 幅ずれた検出
  （§4.4 の表の「印から 1〜2<!--n:definition--> 幅ずれて検出」）と、1<!--n:count--> つの検出が 2<!--n:count--> つの印に
  またがった「統合」はこの表に含めていないので、検出と見落としの和は 53<!--m:kink_reference.clear_marks--> に
  なるとは限らない。採点したのは 3<!--n:count--> 種類だけである。

| `centerline_method` | 距離の中央値（nm） | 実スキャン | 備考 |
|---|---|---|---|
| `"half_max_025w"`（既定） | 0.22<!--m:synthetic_centerline.half_max_025w.group_median_nm_range[0]-->〜0.24<!--m:synthetic_centerline.half_max_025w.group_median_nm_range[1]--> | 50<!--m:kink_reference.default.found--> / 3<!--m:kink_reference.default.missed--> / 64<!--m:kink_reference.default.false--> | |
| `"half_max_05w"` | 0.19<!--m:synthetic_centerline.half_max_05w.group_median_nm_range[0]-->〜0.26<!--m:synthetic_centerline.half_max_05w.group_median_nm_range[1]--> | 48<!--m:kink_reference.hm05.found--> / 4<!--m:kink_reference.hm05.missed--> / 44<!--m:kink_reference.hm05.false--> | 採点した 3<!--n:count--> 種類の中で一致しない折れが最も少ない。ただし合成の同じ向きのコーナー対 8<!--m:synthetic_centerline.pairs--> 組中 2<!--m:synthetic_centerline.pairs_w2.merged_pairs--> 組で 2<!--n:count--> つのコーナーを 1<!--n:count--> つにまとめ（既定は 1<!--m:synthetic_centerline.pairs_w4.merged_pairs--> 組）、平滑化をわずかに強めると見落としが 10〜12<!--m:kink_reference.hm05_stronger.missed_range--> 件に増えた。 |
| `"skeleton_pixels"` | 0.54<!--m:synthetic_centerline.skeleton_pixels.group_median_nm_range[0]-->〜0.64<!--m:synthetic_centerline.skeleton_pixels.group_median_nm_range[1]--> | 52<!--m:kink_reference.skeleton_pixels.found--> / 1<!--m:kink_reference.skeleton_pixels.missed--> / 135<!--m:kink_reference.skeleton_pixels.false--> | 階段状のギザつきと分岐部での振れを折れとして読んでしまう。 |
| `"smoothed_skeleton_05w"`、`"smoothed_skeleton_1w"` | 0.37<!--m:synthetic_centerline.smoothed_skeleton_05w.group_median_nm_range[0]-->〜0.51<!--m:synthetic_centerline.smoothed_skeleton_05w.group_median_nm_range[1]--> / 0.44<!--m:synthetic_centerline.smoothed_skeleton_1w.group_median_nm_range[0]-->〜0.95<!--m:synthetic_centerline.smoothed_skeleton_1w.group_median_nm_range[1]--> | 採点なし | |
| `"quarter_max"` | 0.20<!--m:synthetic_centerline.quarter_max.group_median_nm_range[0]-->〜0.25<!--m:synthetic_centerline.quarter_max.group_median_nm_range[1]--> | 採点なし | ねじれリボン 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> 本中 4<!--m:synthetic_centerline.ribbons.quarter_closer_than_default--> 本で既定より軸に近いが、細い円形の対照繊維では背景の凹凸に最大 3.6<!--m:synthetic_centerline.G_circle_d3.max_nm.quarter_max--> nm 引き寄せられた。 |
| `"centroid"` | 0.32<!--m:synthetic_centerline.centroid.group_median_nm_range[0]-->〜0.39<!--m:synthetic_centerline.centroid.group_median_nm_range[1]--> | 採点なし | |
| `"crest"` | 0.43<!--m:synthetic_centerline.crest.group_median_nm_range[0]-->〜0.48<!--m:synthetic_centerline.crest.group_median_nm_range[1]--> | 採点なし | ねじれリボン 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> 本中 4<!--m:synthetic_centerline.ribbons.crest_farthest_of_three--> 本で軸から最も離れた（既定の 0.99<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->〜1.48<!--m:synthetic_centerline.ribbons.crest_over_default_range[1]--> 倍）。 |

### 4.4 目視基準との比較

「一致なし」は、どの印とも一致しない報告された折れの件数で、以下で誤検出と
呼ぶのはこれである。

| 規則 | 検出 | 印から 1〜2<!--n:definition--> 幅ずれて検出 | 見落とし | 一致なし |
|---|---|---|---|---|
| 超過回転規則（中心線上） | 50<!--m:kink_reference.default.found--> | 0<!--m:kink_reference.default.displaced--> | 3<!--m:kink_reference.default.missed--> | 64<!--m:kink_reference.default.false--> |
| 以前の折れ線規則（スケルトントラック上） | 42<!--m:kink_reference.old_rule.found--> | 3<!--m:kink_reference.old_rule.displaced--> | 8<!--m:kink_reference.old_rule.missed--> | 76<!--m:kink_reference.old_rule.false--> |

以前の規則の行は、同じ画像の追跡済みスケルトントラックに、形式 1.0<!--n:bundle format version--> の
バンドルのために残してある `KinkDetector.kinks_and_decomposed_from_track`
（`kink_decompose_px` = 3<!--c:lib/pipeline.py::ProcParams.kink_decompose_px--> px、`kinkangle_deg` = 150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg--> 度）を適用して採点した。

基準が曖昧な折れまたは合流点とした印から $W$ 以内の報告された折れは、検出にも
一致なしにも数えない。超過回転規則が報告した 139<!--m:kink_reference.default.detections--> 件の折れのうち、25<!--m:kink_reference.default.exempt--> 件がこれにあたる。
規則の行を走査ごとに分けると次のとおりである。

| 走査 | 印を付けた明瞭なキンク | 報告された折れ | 検出 | 見落とし | 一致なし | 曖昧・合流の印のそば |
|---|---|---|---|---|---|---|
| 高等植物 TOC | 3<!--m:kink_reference.default.hplantTOC.ref--> | 6<!--m:kink_reference.default.hplantTOC.detections--> | 3<!--m:kink_reference.default.hplantTOC.found--> | 0<!--m:kink_reference.default.hplantTOC.missed--> | 3<!--m:kink_reference.default.hplantTOC.false--> | 0<!--m:kink_reference.default.hplantTOC.exempt--> |
| ホヤ CNF | 44<!--m:kink_reference.default.tunicate.ref--> | 68<!--m:kink_reference.default.tunicate.detections--> | 42<!--m:kink_reference.default.tunicate.found--> | 2<!--m:kink_reference.default.tunicate.missed--> | 15<!--m:kink_reference.default.tunicate.false--> | 11<!--m:kink_reference.default.tunicate.exempt--> |
| Bruker NDTOC | 6<!--m:kink_reference.default.NDTOC.ref--> | 65<!--m:kink_reference.default.NDTOC.detections--> | 5<!--m:kink_reference.default.NDTOC.found--> | 1<!--m:kink_reference.default.NDTOC.missed--> | 46<!--m:kink_reference.default.NDTOC.false--> | 14<!--m:kink_reference.default.NDTOC.exempt--> |

高等植物 TOC と Bruker NDTOC の走査は同じ分散液を撮ったものである。基準が明瞭な
キンクを 3<!--m:kink_reference.default.hplantTOC.ref--> 件と 6<!--m:kink_reference.default.NDTOC.ref--> 件印したのに対し、規則はそれぞれ 6<!--m:kink_reference.default.hplantTOC.detections--> 件と 65<!--m:kink_reference.default.NDTOC.detections--> 件の折れを報告した。

規則の長さは、$W$ が画像の分解能であることから決めた $W$ の倍数であり、この基準に
対して最適化はしていない。ただし規則と中心線は、候補の中からこの基準での成績によって
選んだ。したがってこの基準は独立した検証ではなく開発用のデータであり、評価用に
取り分けたスキャンでの採点は行っていない。どれか 1<!--n:count--> つを隣の値に変えると、検出
できた明瞭なキンクは 48〜52<!--m:kink_reference.sens_all.found_range--> 件、一致なしは 48〜83<!--m:kink_reference.sens_all.false_range--> 件の範囲で動いた（既定は
それぞれ 50<!--m:kink_reference.default.found--> 件と 64<!--m:kink_reference.default.false--> 件）。検出が最も減ったのは平滑化を強める側で、向きの
平滑化 0.35<!--n:value tried--> W で 48<!--m:kink_reference.sens_heading_0.35.found--> 件、中心線の平滑化 ×1.4<!--n:value tried--> で 49<!--m:kink_reference.sens_line_x1.4.found--> 件であった。

| 長さ | 既定値 | 試した隣の値 |
|---|---|---|
| 中心線の平滑化 | W/4 | ×0.6<!--n:value tried-->、×1.4<!--n:value tried--> |
| 窓の半長 $c$ | 0.75<!--c:lib/kink_detector.py::_CORE_WIDTHS--> W | 0.6<!--n:value tried--> W、0.9<!--n:value tried--> W |
| 脇の長さ $f$ | 1.0<!--c:lib/kink_detector.py::_FLANK_WIDTHS--> W | 0.75<!--n:value tried--> W、1.5<!--n:value tried--> W |
| 向きの平滑化 $\sigma$ | 0.25<!--c:lib/kink_detector.py::_HEADING_SIGMA_WIDTHS--> W | 0.15<!--n:value tried--> W、0.35<!--n:value tried--> W |
| 端の範囲 | 1.5<!--c:lib/kink_detector.py::END_MARGIN_WIDTHS--> W | 1.0<!--n:value tried--> W、2.0<!--n:value tried--> W |
| 抑制半径 | 0.75<!--c:lib/kink_detector.py::_SUPPRESS_WIDTHS--> W | 0.5<!--n:value tried--> W、1.0<!--n:value tried--> W |

窓の回転そのものの極大から取る候補を除くと、明瞭な基準キンクの検出は
50<!--m:turn_maxima.with.found--> 件から 47<!--m:turn_maxima.without.found--> 件に減り、一致しない折れは 64<!--m:turn_maxima.with.false--> 件から 48<!--m:turn_maxima.without.false--> 件に減った（実験
turn_maxima）。

### 4.5 キンクとして保存する角度

鋭い合成コーナーでは、探針と中心線が頂点を丸めるため、超過回転は実際より
小さく読まれた。

| コーナーの回転角 | 読まれた超過回転 |
|---|---|
| 40<!--n:value tried--> 度 | 35〜39<!--m:synthetic_kinks.corner40.excess_read_range_deg--> 度 |
| 60<!--n:value tried--> 度 | 55〜56<!--m:synthetic_kinks.corner60.excess_read_range_deg--> 度 |
| 90<!--n:value tried--> 度 | 83〜84<!--m:synthetic_kinks.corner90.excess_read_range_deg--> 度 |
| 120<!--n:value tried--> 度 | 100〜101<!--m:synthetic_kinks.corner120.excess_read_range_deg--> 度 |

このため、しきい値をわずかに上回る折れが下回って読まれることがある。テスト
スイートで 33.5<!--m:test_suite_bend.drawn_turn_deg--> 度に描いた折れは 26.5<!--m:test_suite_bend.read_excess_deg--> 度と読まれる（実験 test_suite_bend）。
キンクとして保存する角度を、180<!--n:definition--> 度から超過回転を引いた値ではなく腕から読むのは
このためである。10<!--c:scripts/kink_rule_sweep.py::TIP_RADIUS_NM--> nm の探針で描画した内角 120<!--n:example-->・140<!--n:example-->・145<!--n:example--> 度の合成
コーナーでは、見つかったコーナーについて、3<!--c:scripts/kink_rule_sweep.py::len(NOISES_NM)--> つのノイズ水準をまとめた角度の
誤差の中央値は次のとおりであった。

| 見かけ幅 | 腕のなす角 | 180<!--n:definition--> 度 − 超過回転 |
|---|---|---|
| 3.5<!--m:kink_rule_sweep.W5.measured_width_px--> px | 0.6<!--m:kink_rule_sweep.W5.arm_error_deg--> 度 | 1.7<!--m:kink_rule_sweep.W5.excess_error_deg--> 度 |
| 5.75<!--m:kink_rule_sweep.W8.measured_width_px--> px | 2.0<!--m:kink_rule_sweep.W8.arm_error_deg--> 度 | 2.4<!--m:kink_rule_sweep.W8.excess_error_deg--> 度 |
| 11.5<!--m:kink_rule_sweep.W16.measured_width_px--> px | 2.35<!--m:kink_rule_sweep.W16.arm_error_deg--> 度 | 2.1<!--m:kink_rule_sweep.W16.excess_error_deg--> 度 |

11.5<!--m:kink_rule_sweep.W16.measured_width_px--> px では、超過回転の方が誤差が小さかった。

### 4.6 合成形状での結果

- 合成ジグザグでは、1.5〜3<!--n:value tried--> $W$ 離れたコーナーはすべて見つかった
  （30<!--m:synthetic_kinks.zigzag_1.5W_up.clear--> 件中 30<!--m:synthetic_kinks.zigzag_1.5W_up.found--> 件）が、1<!--n:value tried--> $W$ 離れたコーナーは 10<!--m:synthetic_kinks.zigzag1W.clear--> 件中 4<!--m:synthetic_kinks.zigzag1W.found--> 件に
  とどまった。
- 直線の繊維（2<!--m:synthetic_kinks.straight.scans--> 枚で 0<!--m:synthetic_kinks.straight.reported--> 件）、半径 3〜10<!--n:value tried--> $W$ の円弧（6<!--m:synthetic_kinks.arcs.scans--> 枚で 0<!--m:synthetic_kinks.arcs.reported--> 件）、
  交差と分岐（10<!--m:synthetic_kinks.crossings_branches.scans--> 枚で 0<!--m:synthetic_kinks.crossings_branches.reported--> 件）、ねじれリボン（6<!--m:synthetic_centerline.ribbons.count--> 枚で 0<!--m:synthetic_centerline.ribbons.kinks_reported--> 件）では、折れを
  報告しなかった。
- 40<!--n:value tried--> 度以上の孤立したコーナーはすべて見つけた（8<!--m:synthetic_kinks.corners_40_up.clear--> 件中 8<!--m:synthetic_kinks.corners_40_up.found--> 件）。
- 最小曲率半径が 1.6〜1.8<!--m:synthetic_kinks.sines.tightest_radius_w_range--> $W$ の正弦波状の蛇行 4<!--m:synthetic_kinks.sines.scans--> 枚では、11<!--m:synthetic_kinks.sines.reported--> 件の折れを
  報告した。半径が約 $2.9\,W$ を下回ると窓の中だけで 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v--> 度を超えて回り、
  曲率が急に変わる場所では脇の回転でそれを打ち消しきれないためである。
- 以前の折れ線規則は、同じ円弧と蛇行で 31<!--m:synthetic_kinks.old_rule.arcs_sines_reported--> 件を報告した（実験 synthetic_kinks）。

### 4.7 中心線ごとのノイズ床

ノイズ床を既定で無効にしているのは、誤検出と本物のキンクを分けられなかった
ためである。目視基準で採点した結果（`scripts/kink_reference_score.py`）は次の
とおりである。

| ノイズ床の倍数 | 失った明瞭なキンク | 減った誤検出 |
|---|---|---|
| 3<!--n:value tried--> | 3<!--m:kink_reference.noise3.lost--> | 7<!--m:kink_reference.noise3.fewer_false--> |
| 4<!--n:value tried--> | 5<!--m:kink_reference.noise4.lost--> | 9<!--m:kink_reference.noise4.fewer_false--> |

これらのスキャンの誤検出は、丸みのある曲がり、絡まり、交差の近くの折れ、淡い筋の
上の折れ、それに超過回転がしきい値を
わずかに上回るだけの浅い折れであって、ノイズではない。64<!--m:kink_reference.default.false--> 件のうち 27<!--m:kink_reference.default.false_excess_30_40--> 件は超過回転が 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v-->〜40<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|190 - v--> 度である。そのうち
12<!--m:kink_reference.default.false_arm_turn_below_threshold--> 件は、腕から読んだ回転（180<!--n:definition--> 度 − `ka`）が 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v--> 度を下回る。腕の角度は
判定に使う超過回転とは別に測るためである。また強く折れ曲がった繊維では、その
繊維自身のキンクがノイズ床を押し上げる。失われた明瞭なキンクはそうした繊維に
あった。合成データの掃引では、ノイズ床が直線・円弧・正弦波の繊維の偽の折れを変えたのは、
最も細かい画素サイズと最も強いノイズの条件（幅 11.5<!--m:kink_rule_sweep.W16.measured_width_px--> px、画素ノイズ 0.30<!--n:value tried--> nm）だけで、
1<!--n:definition--> µm あたり 5.6<!--m:kink_rule_sweep.W16.n0.30.base.fp_per_um--> から 3.6<!--m:kink_rule_sweep.W16.n0.30.k3.fp_per_um--> に減らした。その条件で、報告してはならない 165<!--n:example--> 度の
曲がりに報告した折れは変えなかった（ノイズ床なしで 4<!--m:kink_rule_sweep.W16.n0.30.base.kink165_reported-->、ありで 4<!--m:kink_rule_sweep.W16.n0.30.k3.kink165_reported-->）。見つかる
コーナーはどの条件でも変えなかった。たとえば最も粗い画素サイズと最も強いノイズの条件
では、ノイズ床なしで 4<!--m:kink_rule_sweep.W3.n0.30.base.kinked_found-->、ありで 4<!--m:kink_rule_sweep.W3.n0.30.k3.kinked_found--> つ見つかった（§4.8）。

### 4.8 掃引で規則が働いた範囲

ここでの見かけ幅は、合成画像の設計値ではなく、各設定の直線の繊維でパイプラインが
実際に測った $W$ である。各コーナーは 3<!--c:scripts/kink_rule_sweep.py::len(NOISES_NM)--> つのノイズ水準と 2<!--c:scripts/kink_rule_sweep.py::len(SEEDS)--> つのシードで
描き、角度と幅ごとに 6<!--m:kink_rule_sweep.W5.kink120.cases--> 枚である。

- 3.5<!--m:kink_rule_sweep.W5.measured_width_px--> px では、すべてのコーナーが見つかった（6<!--m:kink_rule_sweep.W5.kink145.cases--> 枚中 6<!--m:kink_rule_sweep.W5.kink120.found-->・6<!--m:kink_rule_sweep.W5.kink140.found-->・6<!--m:kink_rule_sweep.W5.kink145.found--> 枚）。
- 5.75<!--m:kink_rule_sweep.W8.measured_width_px--> px では、すべてのコーナーが見つかった（6<!--m:kink_rule_sweep.W8.kink140.cases--> 枚中 6<!--m:kink_rule_sweep.W8.kink120.found-->・6<!--m:kink_rule_sweep.W8.kink140.found-->・6<!--m:kink_rule_sweep.W8.kink145.found--> 枚）。
- 11.5<!--m:kink_rule_sweep.W16.measured_width_px--> px では、各角度とも 6<!--m:kink_rule_sweep.W16.kink140.cases--> 枚中 5<!--m:kink_rule_sweep.W16.kink120.found-->・5<!--m:kink_rule_sweep.W16.kink140.found-->・5<!--m:kink_rule_sweep.W16.kink145.found--> 枚であった。画素ノイズ 0.15<!--n:value tried--> nm
  まではすべて見つかり、0.30<!--n:value tried--> nm では 2<!--c:scripts/kink_rule_sweep.py::len(SEEDS)--> 枚中 1<!--m:kink_rule_sweep.W16.n0.30.kink120.found--> 枚であった。このノイズでは、描いて
  みると、生の走査では途切れていないほぼ水平な腕の高さの大部分を背景補正が取り除いた。
  そのうち 1<!--n:count--> 枚では、繊維マスクが腕の一部しか覆わず、マスクした画素を最寄りの
  マスク外の画素（腕そのものの上にある）で埋めたため、腕の高さのほぼすべてが背景に
  入った。腕が沿って走る走査線の方向の平滑化はそれを背景に残したが、走査を
  90<!--n:value tried--> 度回すと、同じ平滑化がその大部分を背景から取り除いた。この走査には
  `background_warnings` が警告を出していた（`flank_step_low` と `relief_absorbed`）。
  追跡はその腕を多数の断片に分け、偽の折れがその腕に集まった。同じ設定の直線・
  円弧・正弦波の繊維では、規則は 1<!--n:definition--> µm あたり 5.6<!--m:kink_rule_sweep.W16.n0.30.base.fp_per_um--> 件の偽の折れを報告した。
- 細かい方の 3<!--n:count--> つの画素サイズでは、画素ノイズ 0.15<!--n:value tried--> nm までの直線・円弧・蛇行に
  偽陽性は無く、165<!--n:example--> 度の曲がりにも無かった。
- 掃引で最も粗い画素サイズ（5.2<!--c:scripts/kink_rule_sweep.py::APPARENT_WIDTH_NM|v / 3--> nm。繊維が占める画素は 3.5<!--m:kink_rule_sweep.W5.measured_width_px--> px の設定より
  少ない）では、幅は 2<!--c:lib/centerline.py::_MIN_WIDTH_PX--> px 未満と測られて 2<!--m:kink_rule_sweep.W3.measured_width_px--> px に引き上げられた。120<!--n:example--> 度の
  コーナーは 6<!--m:kink_rule_sweep.W3.kink120.cases--> 枚中 6<!--m:kink_rule_sweep.W3.kink120.found--> 枚、145<!--n:example--> 度は 5<!--m:kink_rule_sweep.W3.kink145.found--> 枚、140<!--n:example--> 度は 5<!--m:kink_rule_sweep.W3.kink140.found--> 枚で見つかった。描いてみると、
  140<!--n:example--> 度の 6<!--n:count--> 枚はどれもコーナーを途切れずに追跡しており、そこで規則が報告した
  ほかの折れは斜めの腕の端にある。幅が 2<!--m:kink_rule_sweep.W3.measured_width_px--> px なので、判定しないのは
  トラック端から 3<!--x:1.5 * 2--> px 以内の折れだけである。直線・円弧・正弦波の繊維には、どのノイズの
  水準でも 1<!--n:definition--> µm あたり 0.0<!--m:kink_rule_sweep.W3.n0.15.base.fp_per_um-->〜1.0<!--m:kink_rule_sweep.W3.n0.05.base.fp_per_um--> 件の偽の折れを報告し、165<!--n:example--> 度の曲がりには
  0.30<!--n:value tried--> nm で 1<!--m:kink_rule_sweep.W3.n0.30.base.kink165_reported--> 件報告した。

### 4.9 端の範囲

実データの同梱スキャン 3<!--n:count--> 枚では、トラック端の 43<!--m:track_ends.hplantTOC.near_branch_percent-->〜64<!--m:track_ends.tunicate.near_branch_percent--> % が分岐点から
3<!--n:definition--> px 以内にある（実験 track_ends）。トラックの端の多くは繊維の本当の終端では
なく、交差での切断である。

端の範囲を $1.0\,W$ にすると、同梱スキャンの誤検出は 64<!--m:kink_reference.default.false--> 件から 83<!--m:kink_reference.sens_end_1.false--> 件に
増え、明瞭なキンクの検出は 1<!--n:count--> 件も増えなかった。$2.0\,W$ にすると誤検出は
48<!--m:kink_reference.sens_end_2.false--> 件に減り、明瞭なキンクの検出は同じ 50<!--m:kink_reference.sens_end_2.found--> 件であった。端から 1.5<!--n:value tried--> $W$ の
合成コーナーは、既定で 2<!--m:synthetic_kinks.end_cases_per_distance--> 件中 1<!--m:synthetic_kinks.margin_default.end1.5W.corners_judged--> 件、$2.0\,W$ で 0<!--m:synthetic_kinks.margin_2W.end1.5W.corners_judged--> 件を判定した。端から 2<!--n:value tried--> $W$ の
合成コーナーは、既定で 2<!--m:synthetic_kinks.end_cases_per_distance--> 件中 1<!--m:synthetic_kinks.margin_default.end2W.corners_judged--> 件、$2.0\,W$ で 1<!--m:synthetic_kinks.margin_2W.end2W.corners_judged--> 件を判定した。描いてみると、
各組のうちどちらの範囲でも判定しなかった走査では、短い腕の追跡が繊維の端より手前で
終わり、コーナーがトラック端から $1.5\,W$ 以内に入っている。同梱スキャンで判定しな
かった 48<!--m:kink_reference.default.unjudged--> 件の折れには、明瞭な基準キンクに当たるものは無かった。

### 4.10 頂点高さと中心線上の高さ

各テスト入力の、追跡できるスケルトンのつながった部分すべてについて、既定の中心線を
`KinkDetector` と同じやり方で置き（実験 crest_height）、信頼できる点で、頂点高さと、
中心線の位置で読んだ補正後の高さとを比べた。

| 入力 | 差の中央値 (nm) | 差の 90<!--n:definition--> パーセンタイル (nm) | 中央値、頂点高さに対する % | 90<!--n:definition--> パーセンタイル、頂点高さに対する % |
|---|---|---|---|---|
| チュニケート CNF | 0.070<!--m:crest_height.tunicate.median_nm--> | 0.211<!--m:crest_height.tunicate.p90_nm--> | 0.940<!--m:crest_height.tunicate.median_percent--> | 2.602<!--m:crest_height.tunicate.p90_percent--> |
| 高等植物 TOC | 0.013<!--m:crest_height.hplantTOC.median_nm--> | 0.076<!--m:crest_height.hplantTOC.p90_nm--> | 0.809<!--m:crest_height.hplantTOC.median_percent--> | 4.439<!--m:crest_height.hplantTOC.p90_percent--> |
| Bruker NDTOC | 0.025<!--m:crest_height.NDTOC.median_nm--> | 0.129<!--m:crest_height.NDTOC.p90_nm--> | 1.260<!--m:crest_height.NDTOC.median_percent--> | 7.270<!--m:crest_height.NDTOC.p90_percent--> |
頂点高さが中心線上の高さより低いことは、1<!--n:count--> 度も無かった。したがって、中心線の
位置で高さを読むと、繊維は低く出る。差は表のとおり小さいが、いつも低く出る向きで
ある。左右が非対称な断面では、半値の中点が頂点の横にずれるからである。

### 4.11 切り口の近くの高さ

各テスト入力の、長さ 5<!--n:definition--> W 以上のトラックについて、既定の中心線に沿って、端の近くの
頂点高さをそのトラックの頂点高さの中央値で割り、交差で切れた端（分岐点から 3<!--n:definition--> px
以内）と自由な端とに分けて中央値をとった（実験 cut_end_skirt）。

| 入力 | 切り口の数 | 切り口での比 | 1.05<!--n:definition--> 以下に戻るまでの距離 (W) | 自由な端での比 |
|---|---|---|---|---|
| チュニケート CNF | 45<!--m:cut_end_skirt.tunicate.cut_ends--> | 1.43<!--m:cut_end_skirt.tunicate.cut.ratio_at_end--> | 0.75<!--m:cut_end_skirt.tunicate.cut.back_within_widths--> | 1.03<!--m:cut_end_skirt.tunicate.free.ratio_at_end--> |
| 高等植物 TOC | 7<!--m:cut_end_skirt.hplantTOC.cut_ends--> | 1.26<!--m:cut_end_skirt.hplantTOC.cut.ratio_at_end--> | 1.00<!--m:cut_end_skirt.hplantTOC.cut.back_within_widths--> | 0.99<!--m:cut_end_skirt.hplantTOC.free.ratio_at_end--> |
| Bruker NDTOC | 83<!--m:cut_end_skirt.NDTOC.cut_ends--> | 1.27<!--m:cut_end_skirt.NDTOC.cut.ratio_at_end--> | 0.50<!--m:cut_end_skirt.NDTOC.cut.back_within_widths--> | 0.70<!--m:cut_end_skirt.NDTOC.free.ratio_at_end--> |

距離ごとの変化を描くと、切り口では高さが繊維自身の高さより持ち上がり、幅ひとつ分
ほどのうちに戻る。自由な端には、この持ち上がりが無い。交差での相手繊維の裾が、
分岐点で消した画素の先まで届いているからである。

### 4.12 断面の幅の上限

`centerline._refine` は、半値全幅が 1.5<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS--> W 以下の断面だけをこの繊維のものとみなす。
上限は断面の各半分には課さない。代わりに頂点から各半分を 0.75<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS|v / 2--> W 以内に制限すると
（実験 section_width_limit）、自身の断面で位置を決めた中心線の点の割合は、どの
テスト入力でも下がり、上がった入力は無かった。

| 入力 | 点 | 位置を決めた点、全幅 (%) | 位置を決めた点、各半分 (%) |
|---|---|---|---|
| チュニケート CNF | 7919<!--m:section_width_limit.tunicate.points--> | 88.1<!--m:section_width_limit.tunicate.reliable_full_percent--> | 84.0<!--m:section_width_limit.tunicate.reliable_half_percent--> |
| 高等植物 TOC | 1883<!--m:section_width_limit.hplantTOC.points--> | 92.5<!--m:section_width_limit.hplantTOC.reliable_full_percent--> | 88.1<!--m:section_width_limit.hplantTOC.reliable_half_percent--> |
| Bruker NDTOC | 8788<!--m:section_width_limit.NDTOC.points--> | 81.7<!--m:section_width_limit.NDTOC.reliable_full_percent--> | 75.6<!--m:section_width_limit.NDTOC.reliable_half_percent--> |

チュニケートのスキャンで最も多くの点を失う繊維（920<!--m:section_width_limit.tunicate.most_lost.points--> 点中 134<!--m:section_width_limit.tunicate.most_lost.lost--> 点）を、補正後の
高さ画像に断面とともに描いた。失う点は、角から右端までの直線区間である。この
区間は他の繊維に 1<!--n:count--> 回交差されるだけの 1<!--n:count--> 本の繊維で、断面は単峰だが頂点が中央から少し
ずれている。そのため全幅は 1.5<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS--> W 以内に収まるのに、片側の半分が 0.75<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS|v / 2--> W を超える。

### 4.13 まっすぐな繊維の曲率

`measure.fiber_mean_curvature` は符号なしの曲率を平均するので、まっすぐな繊維でも
0<!--n:comparison--> より大きい値になる。高さ 2<!--n:condition--> nm、半値全幅 20<!--n:condition--> nm のガウス断面で、長さ
1200<!--n:condition--> nm、行に対して 20<!--n:condition-->° 傾いたまっすぐな合成繊維を、3<!--n:count--> 通りの画素サイズと
3<!--n:count--> 通りのガウス高さノイズで描き（ノイズは各 5<!--n:condition--> 回）、軸の画素トラックに置いた
既定の中心線で平均曲率を求めた（実験 curvature_noise_floor、rad/µm、5<!--n:condition--> 回の平均）。

| 画素 (nm) | ノイズ 0<!--n:condition--> nm | ノイズ 0.05<!--n:condition--> nm | ノイズ 0.15<!--n:condition--> nm |
|---|---|---|---|
| 2<!--n:condition--> | 0.03<!--m:curvature_noise_floor.px2.noise0.mean--> | 0.06<!--m:curvature_noise_floor.px2.noise0.05.mean--> | 0.16<!--m:curvature_noise_floor.px2.noise0.15.mean--> |
| 5<!--n:condition--> | 0.29<!--m:curvature_noise_floor.px5.noise0.mean--> | 0.27<!--m:curvature_noise_floor.px5.noise0.05.mean--> | 0.35<!--m:curvature_noise_floor.px5.noise0.15.mean--> |
| 10<!--n:condition--> | 0.64<!--m:curvature_noise_floor.px10.noise0.mean--> | 0.66<!--m:curvature_noise_floor.px10.noise0.05.mean--> | 0.82<!--m:curvature_noise_floor.px10.noise0.15.mean--> |

ノイズが無いときの値は画素の格子から来る。真の軸に対して描くと、画素 5<!--n:condition-->・10<!--n:condition--> nm
では中心線にスケルトントラックの階段の周期で揺れが残っており、繊維がまたぐ画素が
少ない 10<!--n:condition--> nm のほうが大きい。2<!--n:condition--> nm では横方向のずれはずっと小さい（W は画素
2<!--n:condition-->・5<!--n:condition-->・10<!--n:condition--> nm でそれぞれ 9.5<!--m:curvature_noise_floor.px2.width_px-->・3.75<!--m:curvature_noise_floor.px5.width_px-->・2.00<!--m:curvature_noise_floor.px10.width_px--> px）。0.15<!--n:condition--> nm のノイズはどの画素サイズでも
平均を上げ、0.05<!--n:condition--> nm のノイズは画素 2<!--n:condition-->・10<!--n:condition--> nm では上げ、5<!--n:condition--> nm ではわずかに下げた。どちらも画素サイズに依存するので、異なる画素サイズで撮像した群の間の
曲率の差には、撮像条件の違いが含まれる。GUI03 は、曲率で比べるバンドルの画素サイズが
違うときに警告する。

### 4.14 繊維の自由端での長さ

端が輪郭長に加えたり差し引いたりする長さを、走査の内側に収まった長さ
600<!--c:scripts/measure_docs.py::END_LOSS_LENGTH_NM--> nm の直線の繊維 1<!--n:count--> 本で測った。端は角ばったものと、20<!--n:value tried--> nm かけて直径の 0.3<!--n:value tried--> まで
細くなるものの 2<!--n:count--> 通りである（実験 end_loss。直径 3<!--n:value tried--> nm の円柱を先端半径 10<!--n:value tried--> nm の
探針で描き、背景はキンクの掃引と同じものに画素ノイズ 0.05<!--n:value tried--> nm を加え、設定ごとに
シード 3<!--c:scripts/measure_docs.py::len(END_LOSS_SEEDS)--> つ）。計測した中心線の各端を真の軸に投影した。不足量が正なら計測した
中心線が真の端の手前で止まり、負なら真の端を越えて伸びている。どの走査でも繊維は
1<!--n:count--> 本につながって追跡された（18<!--m:end_loss.runs--> 枚中 18<!--m:end_loss.single_fiber_runs--> 枚）。

| 画素サイズ | 端 | 端 1<!--n:count--> つあたりの不足量 | 見かけ幅単位 | 輪郭長の誤差 |
|---|---|---|---|---|
| 1<!--n:value tried--> nm | 角ばった端 | −0.5<!--m:end_loss.px1.taper0.end_deficit_nm_range[0]-->〜+0.5<!--m:end_loss.px1.taper0.end_deficit_nm_range[1]--> nm | −0.04<!--m:end_loss.px1.taper0.end_deficit_w_range[0]-->〜+0.04<!--m:end_loss.px1.taper0.end_deficit_w_range[1]--> | +0.07<!--m:end_loss.px1.taper0.length_error_percent_range[0]-->〜+0.33<!--m:end_loss.px1.taper0.length_error_percent_range[1]--> % |
| 1<!--n:value tried--> nm | 細くなる端 | −5.4<!--m:end_loss.px1.taper20.end_deficit_nm_range[0]-->〜+0.9<!--m:end_loss.px1.taper20.end_deficit_nm_range[1]--> nm | −0.49<!--m:end_loss.px1.taper20.end_deficit_w_range[0]-->〜+0.08<!--m:end_loss.px1.taper20.end_deficit_w_range[1]--> | +0.03<!--m:end_loss.px1.taper20.length_error_percent_range[0]-->〜+1.62<!--m:end_loss.px1.taper20.length_error_percent_range[1]--> % |
| 2<!--n:value tried--> nm | 角ばった端 | −0.8<!--m:end_loss.px2.taper0.end_deficit_nm_range[0]-->〜+0.2<!--m:end_loss.px2.taper0.end_deficit_nm_range[1]--> nm | −0.07<!--m:end_loss.px2.taper0.end_deficit_w_range[0]-->〜+0.02<!--m:end_loss.px2.taper0.end_deficit_w_range[1]--> | +0.25<!--m:end_loss.px2.taper0.length_error_percent_range[0]-->〜+0.34<!--m:end_loss.px2.taper0.length_error_percent_range[1]--> % |
| 2<!--n:value tried--> nm | 細くなる端 | −2.6<!--m:end_loss.px2.taper20.end_deficit_nm_range[0]-->〜+1.3<!--m:end_loss.px2.taper20.end_deficit_nm_range[1]--> nm | −0.24<!--m:end_loss.px2.taper20.end_deficit_w_range[0]-->〜+0.12<!--m:end_loss.px2.taper20.end_deficit_w_range[1]--> | +0.03<!--m:end_loss.px2.taper20.length_error_percent_range[0]-->〜+0.74<!--m:end_loss.px2.taper20.length_error_percent_range[1]--> % |
| 4<!--n:value tried--> nm | 角ばった端 | −3.3<!--m:end_loss.px4.taper0.end_deficit_nm_range[0]-->〜+0.5<!--m:end_loss.px4.taper0.end_deficit_nm_range[1]--> nm | −0.30<!--m:end_loss.px4.taper0.end_deficit_w_range[0]-->〜+0.05<!--m:end_loss.px4.taper0.end_deficit_w_range[1]--> | +0.47<!--m:end_loss.px4.taper0.length_error_percent_range[0]-->〜+1.13<!--m:end_loss.px4.taper0.length_error_percent_range[1]--> % |
| 4<!--n:value tried--> nm | 細くなる端 | +1.1<!--m:end_loss.px4.taper20.end_deficit_nm_range[0]-->〜+9.3<!--m:end_loss.px4.taper20.end_deficit_nm_range[1]--> nm | +0.10<!--m:end_loss.px4.taper20.end_deficit_w_range[0]-->〜+0.85<!--m:end_loss.px4.taper20.end_deficit_w_range[1]--> | −1.67<!--m:end_loss.px4.taper20.length_error_percent_range[0]-->〜−0.91<!--m:end_loss.px4.taper20.length_error_percent_range[1]--> % |

描いてみると、画素 1<!--n:value tried--> nm では、細くなる端の計測した中心線は、繊維の端を越えて、
探針がその周りに広げた像の中まで伸び、ある走査ではそこで軸から曲がって離れている。
画素 4<!--n:value tried--> nm では、細くなる端は背景に溶け込み、計測した中心線はその手前で止まる。
角ばった端は、真の端から画素の幅以内で止まる。したがって端の誤差の向きは一定ではなく、
画素サイズと繊維の終わり方によって決まり、実際の走査からは繊維がどう終わっているかは
分からない。これらは自由端の結果であり、交差で切れた端は §4.11 の場合である。

### 4.15 画素ノイズのもとでの頂点高さ

半径 15<!--n:value tried--> nm の球状の先端で膨張させた直径 2<!--n:value tried--> nm の円柱から点標本化した繊維を、行に対して
20<!--n:value tried--> 度の直線と、半径 4<!--n:value tried--> $W$ の円弧として、下の各見かけ幅になる画素サイズで描き、画素ノイズ
0<!--n:value tried-->、0.05<!--n:value tried-->、0.1<!--n:value tried-->、0.2<!--n:value tried--> nm、シード 3<!--n:count--> 通りを加えた（実験 crest_noise）。既定の中心線を真の軸の画素トラックの
上に置き、繊維の中央 60<!--n:definition--> % での頂点高さの中央値を真の高さと比べた。直線の繊維での差（nm）は
次のとおり。

| 見かけの幅（画素） | ノイズ無し | 0.05<!--n:value tried--> nm | 0.1<!--n:value tried--> nm | 0.2<!--n:value tried--> nm |
|---|---|---|---|---|
| 3<!--n:value tried--> | −0.050<!--m:crest_noise.line.W3.n0_nm--> | −0.046<!--m:crest_noise.line.W3.n0.05_nm--> | −0.041<!--m:crest_noise.line.W3.n0.1_nm--> | −0.007<!--m:crest_noise.line.W3.n0.2_nm--> |
| 5<!--n:value tried--> | −0.020<!--m:crest_noise.line.W5.n0_nm--> | −0.011<!--m:crest_noise.line.W5.n0.05_nm--> | +0.007<!--m:crest_noise.line.W5.n0.1_nm--> | +0.061<!--m:crest_noise.line.W5.n0.2_nm--> |
| 8<!--n:value tried--> | −0.008<!--m:crest_noise.line.W8.n0_nm--> | +0.006<!--m:crest_noise.line.W8.n0.05_nm--> | +0.030<!--m:crest_noise.line.W8.n0.1_nm--> | +0.087<!--m:crest_noise.line.W8.n0.2_nm--> |
| 16<!--n:value tried--> | −0.002<!--m:crest_noise.line.W16.n0_nm--> | +0.016<!--m:crest_noise.line.W16.n0.05_nm--> | +0.042<!--m:crest_noise.line.W16.n0.1_nm--> | +0.097<!--m:crest_noise.line.W16.n0.2_nm--> |
| 24<!--n:value tried--> | −0.001<!--m:crest_noise.line.W24.n0_nm--> | +0.026<!--m:crest_noise.line.W24.n0.05_nm--> | +0.060<!--m:crest_noise.line.W24.n0.1_nm--> | +0.175<!--m:crest_noise.line.W24.n0.2_nm--> |

各断面の頂点は頂部付近の標本の最大値であり、ノイズがあると、それは標本がばらつく中心の
頂部より上にあり、頂部が平らなほど大きく上回る。そのため頂点高さは、ノイズが大きく繊維が
太いほど高く出て、24<!--n:value tried--> 画素・0.2<!--n:value tried--> nm では直線の繊維で +0.175<!--m:crest_noise.line.W24.n0.2_nm--> nm、円弧で +0.190<!--m:crest_noise.arc.W24.n0.2_nm--> nm に
達した。高さの四十分の一にあたる 0.05<!--n:value tried--> nm のノイズでは、差が最も大きかったのは円弧の
3<!--n:value tried--> 画素での −0.048<!--m:crest_noise.arc.W3.n0.05_nm--> nm で、画素格子が高さを制限する場合である（§1.9）。

### 4.16 画素ノイズのもとでの見かけの幅

§4.15 の直線の繊維を、見かけの幅 8<!--n:value tried-->〜32<!--n:value tried--> 画素、画素ノイズ 0.05<!--n:value tried-->〜0.3<!--n:value tried--> nm で、シード
3<!--n:count--> 通りずつ描いた（実験 width_noise）。`place_centerline` が測った幅（画素）と、かっこ内に、
自身の断面の上に置けた中心線の点の割合を示す。

| 見かけの幅（画素） | 0.05<!--n:value tried--> nm | 0.1<!--n:value tried--> nm | 0.15<!--n:value tried--> nm | 0.2<!--n:value tried--> nm | 0.3<!--n:value tried--> nm |
|---|---|---|---|---|---|
| 8<!--n:value tried--> | 7.75<!--m:width_noise.W8.n0.05.width_px--> (100<!--m:width_noise.W8.n0.05.located_percent--> %) | 7.75<!--m:width_noise.W8.n0.1.width_px--> (100<!--m:width_noise.W8.n0.1.located_percent--> %) | 7.75<!--m:width_noise.W8.n0.15.width_px--> (100<!--m:width_noise.W8.n0.15.located_percent--> %) | 7.75<!--m:width_noise.W8.n0.2.width_px--> (100<!--m:width_noise.W8.n0.2.located_percent--> %) | 7.67<!--m:width_noise.W8.n0.3.width_px--> (100<!--m:width_noise.W8.n0.3.located_percent--> %) |
| 16<!--n:value tried--> | 15.75<!--m:width_noise.W16.n0.05.width_px--> (100<!--m:width_noise.W16.n0.05.located_percent--> %) | 15.92<!--m:width_noise.W16.n0.1.width_px--> (100<!--m:width_noise.W16.n0.1.located_percent--> %) | 15.83<!--m:width_noise.W16.n0.15.width_px--> (100<!--m:width_noise.W16.n0.15.located_percent--> %) | 14.50<!--m:width_noise.W16.n0.2.width_px--> (100<!--m:width_noise.W16.n0.2.located_percent--> %) | 13.92<!--m:width_noise.W16.n0.3.width_px--> (100<!--m:width_noise.W16.n0.3.located_percent--> %) |
| 24<!--n:value tried--> | 23.75<!--m:width_noise.W24.n0.05.width_px--> (100<!--m:width_noise.W24.n0.05.located_percent--> %) | 23.75<!--m:width_noise.W24.n0.1.width_px--> (100<!--m:width_noise.W24.n0.1.located_percent--> %) | 13.42<!--m:width_noise.W24.n0.15.width_px--> (0<!--m:width_noise.W24.n0.15.located_percent--> %) | 12.17<!--m:width_noise.W24.n0.2.width_px--> (0<!--m:width_noise.W24.n0.2.located_percent--> %) | 9.25<!--m:width_noise.W24.n0.3.width_px--> (13<!--m:width_noise.W24.n0.3.located_percent--> %) |
| 32<!--n:value tried--> | 31.75<!--m:width_noise.W32.n0.05.width_px--> (100<!--m:width_noise.W32.n0.05.located_percent--> %) | 31.75<!--m:width_noise.W32.n0.1.width_px--> (100<!--m:width_noise.W32.n0.1.located_percent--> %) | 10.25<!--m:width_noise.W32.n0.15.width_px--> (3<!--m:width_noise.W32.n0.15.located_percent--> %) | 8.17<!--m:width_noise.W32.n0.2.width_px--> (37<!--m:width_noise.W32.n0.2.located_percent--> %) | 5.75<!--m:width_noise.W32.n0.3.width_px--> (59<!--m:width_noise.W32.n0.3.located_percent--> %) |

ノイズが 0.15<!--n:value tried--> nm 以上になると、24<!--n:value tried--> 画素と 32<!--n:value tried--> 画素の幅は半分程度以下に読まれ、置けた点も
わずかになった。最初の範囲 ±12<!--c:lib/centerline.py::_WIDTH_SEARCH_PX--> 画素が幅の 1.25<!--c:lib/centerline.py::_WIDTH_RANGE_MIN_WIDTHS--> 倍より短いときは、より長い範囲で断面を読み直し、
その読み取りは大半の断面が頂点を 1<!--n:count--> つしか含まないときだけ使われる
（`centerline.measure_apparent_width`）。ふもとから見た頂点の高さの十分の一を超えて立ち上がる
ノイズの山があるとこの判定に通らず、ふもとが繊維の裾に来る狭い最初の読み取りが残る。中心線の配置とキンク規則の長さは
どれも $W$ の倍数なので、そうした走査では両方とも誤った尺度で働く。

### 4.17 ノイズの警告

`pipeline.noise_warnings` は、スケルトン上の補正後の高さの中央値が、補正後の背景の
画素ノイズの 20<!--c:lib/pipeline.py::MIN_FIBER_SNR--> 倍に満たないときに警告する（`pipeline.fiber_snr`）。画素ノイズは、
二値化マスクから 4<!--c:lib/pipeline.py::_NOISE_MASK_MARGIN_PX--> 画素より離れた、横に隣り合う画素の差の中央絶対偏差の 1.4826<!--n:definition--> 倍を
$\sqrt{2}$ で割ったものである。この限界は §4.15〜§4.16 から決めた。ノイズが高さの
二十分の一のとき、頂点高さの高めのずれは最大 +0.060<!--m:crest_noise.line.W24.n0.1_nm--> nm（24<!--n:value tried--> 画素）で、どの幅も保たれ、
それよりノイズが大きいと頂点高さはさらに高く出て、24<!--n:value tried--> 画素と 32<!--n:value tried--> 画素の幅は崩れた。

同梱の 3<!--n:count--> つのスキャンでは比は 42–406<!--m:noise_warning.inputs.snr_range--> で（実験 noise_warning）、どれも警告されなかった。
§4.15 の直線の繊維をパイプライン全体で解析した。8<!--n:value tried--> 画素では、ノイズ 0.1<!--n:value tried--> nm 以上で
警告が出て（読んだ比 19.6<!--m:noise_warning.W8.n0.1.default.snr-->）、0.05<!--n:value tried--> nm（39.6<!--m:noise_warning.W8.n0.05.default.snr-->）では出なかった。24<!--n:value tried--> 画素では、既定の解析は
どのノイズでも何も追跡しなかった。背景補正が繊維を取り除き（§1.8。補正後の画像で確認）、
`background_warnings` が幅を測れなかったことを報告した。その警告が勧める設定である、幅の
3<!--n:value tried--> 倍の構造要素の `tophat` では、0.05<!--n:value tried--> nm で繊維が幅 23.75<!--m:noise_warning.W24.n0.05.tophat.width_px--> 画素で追跡され、警告は
出なかった。0.1<!--n:value tried--> nm 以上では警告が出て（比 18.1<!--m:noise_warning.W24.n0.1.tophat.snr--> 以下）、大半の成分で幅を測れず、
スケルトンは 0.05<!--n:value tried--> nm の 349<!--m:noise_warning.W24.n0.05.tophat.skeleton_px--> 画素に対して 573<!--m:noise_warning.W24.n0.3.tophat.skeleton_px-->〜867<!--m:noise_warning.W24.n0.15.tophat.skeleton_px--> 画素になった。

## 5. 縞ノイズの検査

### 5.1 段差のしきい値

`stripe_noise.evaluate_scan_lines` は、中央値の高さが 3<!--c:lib/stripe_noise.py::DEFAULT_STEP_THRESHOLD_NM--> nm を超えて違う 2<!--n:count--> 本の
走査線の境界を検出する。GUI01 が検査するのと同じく、各テスト入力の生の高さで調べた
（実験 stripe_threshold）。

| 入力 | 検出された境界 | 検出された最小の段差 (nm) | 検出されない最大の段差 (nm) | 検出されない段差の 99<!--n:definition--> パーセンタイル (nm) |
|---|---|---|---|---|
| チュニケート CNF | 0<!--m:stripe_threshold.tunicate.flagged--> | — | 2.71<!--m:stripe_threshold.tunicate.unflagged_max_step_nm--> | 1.24<!--m:stripe_threshold.tunicate.unflagged_p99_step_nm--> |
| 高等植物 TOC | 2<!--m:stripe_threshold.hplantTOC.flagged--> | 5.53<!--m:stripe_threshold.hplantTOC.flagged_min_step_nm--> | 0.21<!--m:stripe_threshold.hplantTOC.unflagged_max_step_nm--> | 0.13<!--m:stripe_threshold.hplantTOC.unflagged_p99_step_nm--> |
| Bruker NDTOC | 0<!--m:stripe_threshold.NDTOC.flagged--> | — | 0.23<!--m:stripe_threshold.NDTOC.unflagged_max_step_nm--> | 0.18<!--m:stripe_threshold.NDTOC.unflagged_p99_step_nm--> |

描いてみると、高等植物のスキャンで検出された 2<!--n:count--> つの境界は、全幅にわたってずれた
行を挟んでおり、フィードバックのグリッチである。検出されない最大の段差
（チュニケートのスキャン）はグリッチではない。この生のスキャンは各行に沿って強く
傾いているため、行の中央値は、中央の順位の値を持つ列の高さになる。数行を横切る物質が
その列を動かす。平面を引いた高さには、そこに帯は無い。このスキャンでは、しきい値は
グリッチではない段差の 0.29<!--x:3 - 2.70925--> nm 上にしかない。

## 6. GUI04 の孤立判定

### 6.1 枠

`measure.isolated_fiber_flags` は、骨格の画素が最外周の行か列に達した繊維を、
走査範囲の外へ続くものとみなす。余白は取らない。各テスト入力の追跡済みの繊維で、
枠を 1<!--n:value tried-->〜5<!--n:value tried--> px の余白に広げた（実験 frame_margin）。

| 入力 | 繊維 | 枠に達する、余白なし | 余白 2<!--n:value tried--> px | 余白 5<!--n:value tried--> px |
|---|---|---|---|---|
| チュニケート CNF | 63<!--m:frame_margin.tunicate.fibers--> | 17<!--m:frame_margin.tunicate.margin_0.reaching--> | 17<!--m:frame_margin.tunicate.margin_2.reaching--> | 17<!--m:frame_margin.tunicate.margin_5.reaching--> |
| 高等植物 TOC | 15<!--m:frame_margin.hplantTOC.fibers--> | 3<!--m:frame_margin.hplantTOC.margin_0.reaching--> | 3<!--m:frame_margin.hplantTOC.margin_2.reaching--> | 3<!--m:frame_margin.hplantTOC.margin_5.reaching--> |
| Bruker NDTOC | 142<!--m:frame_margin.NDTOC.fibers--> | 16<!--m:frame_margin.NDTOC.margin_0.reaching--> | 16<!--m:frame_margin.NDTOC.margin_2.reaching--> | 17<!--m:frame_margin.NDTOC.margin_5.reaching--> |

余白 1<!--n:value tried--> px と 2<!--n:value tried--> px では判定は 1<!--n:count--> つも変わらなかった（変化: 0<!--m:frame_margin.all.changed_up_to_2-->）。3<!--n:value tried--> px 以上では、
Bruker のスキャンの繊維が 1<!--m:frame_margin.all.changed_at_5--> 本加わる。補正後の高さ画像に重ねて描くと、それは
交差の間にある短い断片で、走査範囲の外へ出るのではなく、左端から数画素のところを
端に沿って走っている。余白を取ると、外へ続いていない繊維を外へ続くものと数えることになる。

### 6.2 孤立した母集団の長さの偏り

「非孤立を除外」は、他のファイバーに接せず走査範囲の内側にとどまるファイバーを残す。
その母集団がファイバーの長さの公平な標本かどうかを、単位正方形に無作為に置いた直線の
線分で確かめた（実験 isolation_length_bias）。長さは中央値 0.08<!--c:scripts/measure_docs.py::ISOLATION_MEDIAN_LENGTH-->、対数の標準偏差 0.6<!--c:scripts/measure_docs.py::ISOLATION_LOG_SIGMA--> の
対数正規分布から取り、中心と向きは一様に無作為とし、本数ごとに 200<!--c:scripts/measure_docs.py::ISOLATION_SCENES--> 場面を作った。
他のどの線分とも交わらず、正方形の内側に収まる線分を孤立とした。

| 場面あたりの本数 | 孤立 (%) | 長さの中央値、全体 | 長さの中央値、孤立 | 孤立のほうが短い割合 (%) |
|---|---|---|---|---|
| 20<!--n:value tried--> | 79<!--m:isolation_length_bias.n20.isolated_share_percent--> | 0.081<!--m:isolation_length_bias.n20.all_median--> | 0.074<!--m:isolation_length_bias.n20.isolated_median--> | 9<!--m:isolation_length_bias.n20.shorter_percent--> |
| 60<!--n:value tried--> | 65<!--m:isolation_length_bias.n60.isolated_share_percent--> | 0.080<!--m:isolation_length_bias.n60.all_median--> | 0.070<!--m:isolation_length_bias.n60.isolated_median--> | 13<!--m:isolation_length_bias.n60.shorter_percent--> |
| 150<!--n:value tried--> | 44<!--m:isolation_length_bias.n150.isolated_share_percent--> | 0.080<!--m:isolation_length_bias.n150.all_median--> | 0.062<!--m:isolation_length_bias.n150.isolated_median--> | 23<!--m:isolation_length_bias.n150.shorter_percent--> |

孤立した線分は、どの密度でも全体より短く、場面が密なほどその差は大きかった。したがって孤立した母集団では長いファイバーが少なく、
全長を測ったファイバーではあっても、ファイバーの長さの公平な標本ではない。
