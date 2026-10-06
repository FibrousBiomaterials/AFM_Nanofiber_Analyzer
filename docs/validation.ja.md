# 個別データでの評価

[解析アルゴリズム](algorithms.ja.md) は、解析の各段が何を計算するかを説明する。
このページは、各段が個別のデータで何をしたかをまとめる。対象は、リポジトリに
同梱したスキャンと、答えが分かるように描いた合成スキャンである。コードの既定値の
いくつかはこれらの結果を見て選んでおり、どれがそうかもこのページに書く。

**このページの数値はすべて、それを測ったデータについての記述であり、
アルゴリズムの性質ではない。** 同梱スキャンは 5<!--m:kink_reference.scans--> 枚で、実試料 3<!--n:count--> 種と人工
サンプル 2<!--n:count--> 種である。合成スキャンは、決まった繊維と探針の形で描いている。どちらも、
別の試料・別の装置・別の走査サイズで解析がどう振る舞うかは教えない。ここに
示す結果は、確かめる価値のある振る舞いの種類を示すにすぎない。自分の画像で
それが成り立つかは、自分の画像を見て判断する。

## データと数値の管理

| データ | 内容 | コード |
|---|---|---|
| 同梱スキャン | チュニケート CNF（`testdata_tunicateCNF`）、高等植物 TOC（`testdata_higherplantTOC`）、Bruker NDTOC（`testdata_Bruker_txt`）の各スキャンと、等方・異方の人工スキャン（`testdata_artificial`） | `scripts/kink_reference_score.py` の `SCANS` |
| 目視基準 | 同梱スキャンの高さ画像に、検出器の出力を一切表示せずに目視で付けたキンクの印。明瞭なキンク 64<!--m:kink_reference.clear_marks--> 件 | `scripts/kink_reference_score.py` |
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
| チュニケート CNF | 0.23<!--m:bg_stats.tunicate.plane_slope_nm_per_px--> | 4.6<!--m:bg_stats.tunicate.drop_across_hole_nm--> | 15.2<!--m:bg_stats.tunicate.quadratic_p2p_nm--> | 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> |
| 人工データ（等方） | 0.24<!--m:bg_stats.art_iso.plane_slope_nm_per_px--> | 2.4<!--m:bg_stats.art_iso.drop_across_hole_nm--> | 3.5<!--m:bg_stats.art_iso.quadratic_p2p_nm--> | 7.5<!--m:bg_stats.art_iso.skeleton_height_median_nm--> |
| 人工データ（異方） | 0.24<!--m:bg_stats.art_aniso.plane_slope_nm_per_px--> | 2.4<!--m:bg_stats.art_aniso.drop_across_hole_nm--> | 7.5<!--m:bg_stats.art_aniso.quadratic_p2p_nm--> | 7.2<!--m:bg_stats.art_aniso.skeleton_height_median_nm--> |
| 高等植物 TOC | 0.001<!--m:bg_stats.hplantTOC.plane_slope_nm_per_px--> | 0.01<!--m:bg_stats.hplantTOC.drop_across_hole_nm--> | 1.7<!--m:bg_stats.hplantTOC.quadratic_p2p_nm--> | 1.7<!--m:bg_stats.hplantTOC.skeleton_height_median_nm--> |
| Bruker NDTOC | 0.003<!--m:bg_stats.NDTOC.plane_slope_nm_per_px--> | 0.04<!--m:bg_stats.NDTOC.drop_across_hole_nm--> | 21.9<!--m:bg_stats.NDTOC.quadratic_p2p_nm--> | 2.1<!--m:bg_stats.NDTOC.skeleton_height_median_nm--> |

平面の傾きは生の高さに当てた最小二乗平面の傾き、落差はその傾きに膨張後の繊維
マスクの幅の中央値を掛けたもの、皿状成分は平面を除いた後に当てた 2<!--n:definition--> 次曲面の
2<!--n:definition--> 次の項の山谷、高さは既定のスケルトンの下にある補正後の高さの中央値である
（実験 bg_stats）。チュニケートのスキャンでは、中央値 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> nm の高さしかない
繊維 1<!--n:count--> 本分のマスクを横切る間に、背景が 4.6<!--m:bg_stats.tunicate.drop_across_hole_nm--> nm 落ちる。高等植物と Bruker の
スキャンは平面としては水平だが、Bruker のスキャンは皿状成分だけで 21.9<!--m:bg_stats.NDTOC.quadratic_p2p_nm--> nm に
及ぶ。背景補正のトレンド曲面を平面ではなく 2<!--n:definition--> 次曲面にしたのは、最後のような
スキャンがあるためである。

### 1.2 デトレンドの有無による充填の精度

チュニケートのスキャンの繊維の無い背景に、21<!--m:bg_fill.hole_size_px--> px 四方の穴を 20<!--m:bg_fill.holes--> 個開けて
調べると（実験 bg_fill）、充填値がそこで実際に測られた高さから外れる量は、
デトレンドしない場合は最近傍伝播で 2.5<!--m:bg_fill.none.nearest.fill_error_median_nm--> nm、inpainting で 1.7<!--m:bg_fill.none.inpaint.fill_error_median_nm--> nm、2<!--n:definition--> 次の
トレンドを除いた後はそれぞれ 0.30<!--m:bg_fill.quadratic.nearest.fill_error_median_nm--> nm と 0.27<!--m:bg_fill.quadratic.inpaint.fill_error_median_nm--> nm であった（各穴での最大の外れの、
穴全体での中央値）。これらの穴では、精度を決めていたのは充填法ではなく
デトレンドであり、平面でも 2<!--n:definition--> 次曲面とほぼ同じ結果であった（最近傍の充填で
0.34<!--m:bg_fill.plane.nearest.fill_error_median_nm--> nm と 0.30<!--m:bg_fill.quadratic.nearest.fill_error_median_nm--> nm）。

### 1.3 1.0.0 までの充填方式

デトレンドしない 1.0.0 までの inpainting は、上のチュニケートの穴で本当の背景
から 1.7<!--m:bg_fill.none.inpaint.fill_error_median_nm--> nm 外れた。1.0.0 のリリースの背景補正（タグ `v1.0.0` から実行）を、
0.24<!--m:bg_legacy_halo.slope_nm_per_px--> nm/px の平面の上に高さ 8<!--m:bg_legacy_halo.fiber_height_nm--> nm の繊維を 1<!--n:count--> 本置いた合成走査にかけると
（実験 bg_legacy_halo）、繊維の脇の補正後の背景は −0.76<!--m:bg_legacy_halo.v1_0_0.beside_min_nm-->〜+0.77<!--m:bg_legacy_halo.v1_0_0.beside_max_nm--> nm となり、
二値化しきい値の既定 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm を超えた。現在のコードではそこは
−0.21<!--m:bg_legacy_halo.current.beside_min_nm-->〜+0.18<!--m:bg_legacy_halo.current.beside_max_nm--> nm である。

### 1.4 縁での `tophat`

同梱スキャンで最も急な平面の傾き（§1.1）である 0.24<!--m:tophat_border.slope_nm_per_px--> nm/px の斜面に、
直径 25<!--c:lib/pipeline.py::ProcParams.tophat_se_size--> px の要素で生の高さに opening をかけると、上り側の端から 12<!--n:definition--> px
以内に高さ**3.1<!--m:tophat_border.raw.uphill_band_max_nm--> nm** の帯が残る。二値化しきい値 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm を大きく超える
値である。デトレンドした高さに opening をかけると 0.29<!--m:tophat_border.detrended.uphill_band_max_nm--> nm になる
（実験 tophat_border）。

### 1.5 処理時間

同梱の 1024<!--m:bg_timing.image_rows-->×1024<!--m:bg_timing.image_cols--> の Bruker スキャンでの実測は、`tophat` 約 0.5<!--m:bg_timing.tophat.seconds--> 秒、
`trendfill` 約 1.2<!--m:bg_timing.trendfill.seconds--> 秒、`spline1d` 約 2.6<!--m:bg_timing.spline1d.seconds--> 秒であった（いずれも 2<!--n:count--> 回実行した
うちの 2<!--n:count--> 回目）。`trendfill` の中では、`lmfit` のヒストグラムフィットに
`_bg_generate` の半分ほどの時間がかかった（実験 bg_timing）。1<!--n:count--> 台の計算機での
経過時間であり、計算機とその負荷によって変わる。

### 1.6 `spline1d` の向き

各テスト入力を、`trendfill` と、`'x'` と `'y'` の 2<!--n:count--> つの向きの `spline1d` で補正した。
ほかはすべて既定値である（実験 spline1d_axis）。背景（3<!--n:count--> つの二値化マスクを合わせた
範囲から 5<!--n:definition--> px より離れた画素）で、行ごとの中央値のばらつき（標準偏差、nm）と、
列ごとの中央値のばらつきを表に示す。前者は横縞があると大きくなり、後者は縦縞が
あると大きくなる。

| 入力 | 行、`trendfill` | 行、`'x'` | 行、`'y'` | 列、`trendfill` | 列、`'x'` | 列、`'y'` |
|---|---|---|---|---|---|---|
| チュニケート CNF | 0.009<!--m:spline1d_axis.tunicate.trendfill.row_median_std_nm--> | 0.007<!--m:spline1d_axis.tunicate.x.row_median_std_nm--> | 0.062<!--m:spline1d_axis.tunicate.y.row_median_std_nm--> | 0.011<!--m:spline1d_axis.tunicate.trendfill.column_median_std_nm--> | 0.015<!--m:spline1d_axis.tunicate.x.column_median_std_nm--> | 0.015<!--m:spline1d_axis.tunicate.y.column_median_std_nm--> |
| 人工、等方 | 0.011<!--m:spline1d_axis.art_iso.trendfill.row_median_std_nm--> | 0.013<!--m:spline1d_axis.art_iso.x.row_median_std_nm--> | 0.039<!--m:spline1d_axis.art_iso.y.row_median_std_nm--> | 0.012<!--m:spline1d_axis.art_iso.trendfill.column_median_std_nm--> | 0.026<!--m:spline1d_axis.art_iso.x.column_median_std_nm--> | 0.019<!--m:spline1d_axis.art_iso.y.column_median_std_nm--> |
| 人工、異方 | 0.005<!--m:spline1d_axis.art_aniso.trendfill.row_median_std_nm--> | 0.006<!--m:spline1d_axis.art_aniso.x.row_median_std_nm--> | 0.016<!--m:spline1d_axis.art_aniso.y.row_median_std_nm--> | 0.011<!--m:spline1d_axis.art_aniso.trendfill.column_median_std_nm--> | 0.022<!--m:spline1d_axis.art_aniso.x.column_median_std_nm--> | 0.014<!--m:spline1d_axis.art_aniso.y.column_median_std_nm--> |
| 高等植物 TOC | 0.224<!--m:spline1d_axis.hplantTOC.trendfill.row_median_std_nm--> | 0.006<!--m:spline1d_axis.hplantTOC.x.row_median_std_nm--> | 0.286<!--m:spline1d_axis.hplantTOC.y.row_median_std_nm--> | 0.005<!--m:spline1d_axis.hplantTOC.trendfill.column_median_std_nm--> | 0.006<!--m:spline1d_axis.hplantTOC.x.column_median_std_nm--> | 0.011<!--m:spline1d_axis.hplantTOC.y.column_median_std_nm--> |
| Bruker NDTOC | 0.019<!--m:spline1d_axis.NDTOC.trendfill.row_median_std_nm--> | 0.019<!--m:spline1d_axis.NDTOC.x.row_median_std_nm--> | 0.307<!--m:spline1d_axis.NDTOC.y.row_median_std_nm--> | 0.015<!--m:spline1d_axis.NDTOC.trendfill.column_median_std_nm--> | 0.015<!--m:spline1d_axis.NDTOC.x.column_median_std_nm--> | 0.036<!--m:spline1d_axis.NDTOC.y.column_median_std_nm--> |

`'y'` では、行ごとのばらつきがどの入力でも `trendfill` より大きかった。補正後の画像を
描くと、`'y'` では、チュニケート、Bruker、高等植物の入力で、画像全体に明るい横帯と
暗い横帯ができ、高等植物のスキャンの走査線のグリッチも残る。`'x'` では、高等植物の
スキャンでそのグリッチが消え、チュニケートのスキャンで `trendfill` が残す横の
筋も消える。ただし、チュニケートと人工の 2<!--n:count--> つのスキャンでは、縦に近い向きに走る
繊維の右側に、`trendfill` より目に見えて深い暗い縁ができる。`'x'` で列ごとの
ばらつきが `trendfill` より大きくなった入力は、この縁が見えた入力と同じである。

### 1.7 X 方向だけのならし

各テスト入力を既定の `trendfill` で補正し、背景の Savitzky–Golay 平滑化を、コードの
とおり X 方向だけにかけた場合と、X 方向の後に Y 方向にもかけた場合とで比べた（実験
savgol_axis）。表は、背景（2<!--n:count--> つの二値化マスクを合わせた範囲から 5<!--n:definition--> px より離れた
画素）で、行ごとの中央値のばらつき（標準偏差、nm）を示す。横縞があると大きくなる。

| 入力 | 行、X のみ | 行、X と Y |
|---|---|---|
| チュニケート CNF | 0.009<!--m:savgol_axis.tunicate.x_only.row_median_std_nm--> | 0.070<!--m:savgol_axis.tunicate.x_and_y.row_median_std_nm--> |
| 人工、等方 | 0.011<!--m:savgol_axis.art_iso.x_only.row_median_std_nm--> | 0.073<!--m:savgol_axis.art_iso.x_and_y.row_median_std_nm--> |
| 人工、異方 | 0.005<!--m:savgol_axis.art_aniso.x_only.row_median_std_nm--> | 0.070<!--m:savgol_axis.art_aniso.x_and_y.row_median_std_nm--> |
| 高等植物 TOC | 0.224<!--m:savgol_axis.hplantTOC.x_only.row_median_std_nm--> | 0.291<!--m:savgol_axis.hplantTOC.x_and_y.row_median_std_nm--> |
| Bruker NDTOC | 0.016<!--m:savgol_axis.NDTOC.x_only.row_median_std_nm--> | 0.046<!--m:savgol_axis.NDTOC.x_and_y.row_median_std_nm--> |
Y 方向にもならすと、どの入力でも行ごとのばらつきが大きくなった。補正後の画像を
描くと、両方向にならした画像では、チュニケート、人工の等方、高等植物のスキャンに、
X 方向だけのときには無い横方向の筋が全体に出る。Bruker のスキャンは、どちらでも
ほとんど同じに見える。

### 1.8 `spline1d` がトレンドを足し戻す順番

`spline1d` はトレンドを Savitzky–Golay 平滑化の前に足し戻し、`trendfill` は後に足し
戻す。各テスト入力を、両方の順番の `spline1d` で補正した（実験 spline1d_trend_order）。
表は、補正後の高さのいちばん大きい違い（nm）である。

| 入力 | いちばん大きい違い (nm) |
|---|---|
| チュニケート CNF | 0.006<!--m:spline1d_trend_order.tunicate.max_difference_nm--> |
| 人工、等方 | 0.004<!--m:spline1d_trend_order.art_iso.max_difference_nm--> |
| 人工、異方 | 0.005<!--m:spline1d_trend_order.art_aniso.max_difference_nm--> |
| 高等植物 TOC | 0.000<!--m:spline1d_trend_order.hplantTOC.max_difference_nm--> |
| Bruker NDTOC | 0.000<!--m:spline1d_trend_order.NDTOC.max_difference_nm--> |
平滑化は線形なので、2<!--n:count--> つの順番の違いは、トレンドそのものとそれをならしたものの差
だけになり、トレンドが X 方向に大きく曲がっている所ほど大きい。どの入力でも、違いは
二値化のしきい値 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm よりずっと小さい。

## 2. 二値化

[解析アルゴリズム](algorithms.ja.md) §2 を参照。

### 2.1 直線性フィルタのエッジマップ

1.0.0 までは、外接矩形内のマスク全体からエッジマップを作っていた。同梱
スキャン 5<!--m:hough_edge_map.identical--> 枚すべてで、最終的な二値化マスクはどちらでもビット単位で一致する
（実験 hough_edge_map）。

### 2.2 リッジ回収

チュニケートの走査では、二値化マスクから 10<!--n:value tried--> px 以上離れた画素の
99.8<!--m:ridge_hysteresis.ridge.far_below_low_percent--> % が、リッジ応答のヒステリシスの低い側のレベルを下回る（実験
ridge_hysteresis）。
<!-- TODO(review): 生の振幅との対比は再現していない。チュニケートの走査では、補正後の高さへのヒステリシスは画像の 11.6 % を覆い、リッジ応答は 7.7 % で、画像全体へは浸透しなかった（実験 ridge_hysteresis）。 -->
<!-- TODO(review): 採用済みマスクを連結成分処理の前に差し引く効果の実測例（ある 10 µm 走査、候補成分 56 個、最長 1476 nm）は、リポジトリに無い走査のものであったため削除した。同梱スキャンで ridge_min_length_nm に達する候補は、水平な走査線のアーティファクト（高等植物のスキャン）と、端や交差での短い断片（チュニケートのスキャン）であって繊維ではない（実験 ridge_recovery_bundled、描画して確認）。 -->
<!-- TODO(review): 100 nm を下回るあたりから候補を粒子の裾や探針アーティファクトと目視で区別できなくなるというのは、リッジフィルタを評価したときの目視の判断であり、scripts/measure_docs.py のどの実験も再現しない。 -->

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
| チュニケート CNF | 15.6<!--m:local_threshold.tunicate.global.mask_width_px--> → 10.1<!--m:local_threshold.tunicate.both.mask_width_px--> | 1<!--m:local_threshold.tunicate.global.mask_components--> → 9<!--m:local_threshold.tunicate.both.mask_components--> | 68<!--m:local_threshold.tunicate.global.branch_points--> → 33<!--m:local_threshold.tunicate.both.branch_points--> | 25<!--m:local_threshold.tunicate.removed_percent_of_crest--> / 83<!--m:local_threshold.tunicate.kept_percent_of_crest--> |
| 人工、等方 | 17.4<!--m:local_threshold.art_iso.global.mask_width_px--> → 11.2<!--m:local_threshold.art_iso.both.mask_width_px--> | 2<!--m:local_threshold.art_iso.global.mask_components--> → 2<!--m:local_threshold.art_iso.both.mask_components--> | 0<!--m:local_threshold.art_iso.global.branch_points--> → 0<!--m:local_threshold.art_iso.both.branch_points--> | 22<!--m:local_threshold.art_iso.removed_percent_of_crest--> / 85<!--m:local_threshold.art_iso.kept_percent_of_crest--> |
| 人工、異方 | 15.4<!--m:local_threshold.art_aniso.global.mask_width_px--> → 10.0<!--m:local_threshold.art_aniso.both.mask_width_px--> | 4<!--m:local_threshold.art_aniso.global.mask_components--> → 3<!--m:local_threshold.art_aniso.both.mask_components--> | 0<!--m:local_threshold.art_aniso.global.branch_points--> → 0<!--m:local_threshold.art_aniso.both.branch_points--> | 22<!--m:local_threshold.art_aniso.removed_percent_of_crest--> / 84<!--m:local_threshold.art_aniso.kept_percent_of_crest--> |
| 高等植物 TOC | 12.2<!--m:local_threshold.hplantTOC.global.mask_width_px--> → 9.0<!--m:local_threshold.hplantTOC.both.mask_width_px--> | 10<!--m:local_threshold.hplantTOC.global.mask_components--> → 7<!--m:local_threshold.hplantTOC.both.mask_components--> | 6<!--m:local_threshold.hplantTOC.global.branch_points--> → 5<!--m:local_threshold.hplantTOC.both.branch_points--> | 34<!--m:local_threshold.hplantTOC.removed_percent_of_crest--> / 75<!--m:local_threshold.hplantTOC.kept_percent_of_crest--> |
| Bruker NDTOC | 12.9<!--m:local_threshold.NDTOC.global.mask_width_px--> → 9.6<!--m:local_threshold.NDTOC.both.mask_width_px--> | 16<!--m:local_threshold.NDTOC.global.mask_components--> → 20<!--m:local_threshold.NDTOC.both.mask_components--> | 160<!--m:local_threshold.NDTOC.global.branch_points--> → 77<!--m:local_threshold.NDTOC.both.branch_points--> | 35<!--m:local_threshold.NDTOC.removed_percent_of_crest--> / 72<!--m:local_threshold.NDTOC.kept_percent_of_crest--> |

同梱スキャン 5<!--m:kink_reference.scans--> 枚すべての高さ画像に重ねて描くと、局所しきい値が落とす画素は、繊維の斜面の下のほうである。繊維が 1<!--n:count--> 本だけで離れている場所では、
マスクが細くなるだけである。次に書くつながりが見られたのは、繊維が近くを並んで
走るか、背景に凹凸のある、チュニケートと Bruker のスキャンである。全体のしきい値だけでは、近くを並んで走る
2<!--n:count--> 本の繊維が斜面どうしでつながって 1<!--n:count--> つのかたまりになり、スケルトンがその間を
通った。チュニケートのスキャンでは、網目全体がひとつのかたまりになった。Bruker の
スキャンでは、背景のミミズ状の凹凸が繊維の斜面に触れて繊維のマスクとつながり、
スケルトンに横枝を残した。局所しきい値を加えると、そうした凹凸は繊維から離れ、
二値化の後段のフィルタで取り除かれた。

### 2.5 直線性フィルタ

5<!--m:linearity_filter.inputs--> 個のテスト入力（実験 linearity_filter）で、$s_{\text{ratio}}$ は最大 3.36<!--m:linearity_filter.s_ratio_max--> に
なり、$s_{\text{ratio}} > 1$ となったかたまりは 51<!--m:linearity_filter.s_ratio_above_one--> 個あった。フィルタが消したかたまりのうち、
囲む長方形が `h_length` に届くものは 251<!--m:linearity_filter.removed_reaching_h_length--> 個で、すべてを補正後の高さ画像に
重ねて描き、目で判断した。ほとんどは背景の凹凸、粒子、高等植物のスキャンの
走査線のグリッチであったが、7<!--m:linearity_filter.removed_fiber_pieces--> 個は本物の繊維の片であった。曲がった、
または折れた短い繊維片（チュニケートのスキャン）と、画像の端で切れた繊維の端（人工の
異方、高等植物、Bruker の各スキャン）である。

行の向きに走る合成の帯（面積 865<!--m:linearity_filter.band.horizontal.area--> 画素）では、囲む長方形で切り出した画像の
中に Canny が見つけた輪郭は 14<!--m:linearity_filter.band.horizontal.edge_pixels--> 画素で、すべて丸い両端にあった。点数は
0<!--m:linearity_filter.band.horizontal.s_ratio--> で、帯は消された。同じ帯を 45<!--n:definition--> 度に傾けると（面積 620<!--m:linearity_filter.band.diagonal.area--> 画素）、輪郭は
356<!--m:linearity_filter.band.diagonal.edge_pixels--> 画素、点数は 1.35<!--m:linearity_filter.band.diagonal.s_ratio--> で、帯は残った。

### 2.6 直線性フィルタが検査しないかたまり

直線性フィルタは、面積 1000<!--n:literal in the quoted code--> 画素以上のかたまりを検査せずに残す。各テスト入力を、
コードのとおりの場合と、すべてのかたまりを検査する場合とでフィルタにかけた（実験
linearity_large_exemption）。時間は 1<!--n:count--> 台の計算機でのフィルタの実行時間で、計算機と
その負荷によって変わる。

| 入力 | 1000<!--n:literal in the quoted code--> px 以上のかたまり | そのうち検査すると消えるもの | コードのとおりの時間 (s) | すべて検査したときの時間 (s) |
|---|---|---|---|---|
| チュニケート CNF | 9<!--m:linearity_large_exemption.tunicate.large_components--> | 0<!--m:linearity_large_exemption.tunicate.large_removed_if_tested--> | 0.081<!--m:linearity_large_exemption.tunicate.code.seconds--> | 1.678<!--m:linearity_large_exemption.tunicate.all.seconds--> |
| 人工、等方 | 1<!--m:linearity_large_exemption.art_iso.large_components--> | 0<!--m:linearity_large_exemption.art_iso.large_removed_if_tested--> | 0.013<!--m:linearity_large_exemption.art_iso.code.seconds--> | 0.061<!--m:linearity_large_exemption.art_iso.all.seconds--> |
| 人工、異方 | 3<!--m:linearity_large_exemption.art_aniso.large_components--> | 0<!--m:linearity_large_exemption.art_aniso.large_removed_if_tested--> | 0.013<!--m:linearity_large_exemption.art_aniso.code.seconds--> | 0.116<!--m:linearity_large_exemption.art_aniso.all.seconds--> |
| 高等植物 TOC | 4<!--m:linearity_large_exemption.hplantTOC.large_components--> | 0<!--m:linearity_large_exemption.hplantTOC.large_removed_if_tested--> | 0.116<!--m:linearity_large_exemption.hplantTOC.code.seconds--> | 0.353<!--m:linearity_large_exemption.hplantTOC.all.seconds--> |
| Bruker NDTOC | 15<!--m:linearity_large_exemption.NDTOC.large_components--> | 0<!--m:linearity_large_exemption.NDTOC.large_removed_if_tested--> | 1.622<!--m:linearity_large_exemption.NDTOC.code.seconds--> | 3.794<!--m:linearity_large_exemption.NDTOC.all.seconds--> |
どの入力でも、大きなかたまりを検査して消えるものは無かった。一方、検査すると
フィルタの時間は数倍になり、チュニケートのスキャンでは十倍を超えた。大きな
切り出しの Hough 変換は時間がかかるからである。ただし、大きな汚れのかたまりのような、
線の形をしていない大きなものも、検査されずに残る。

## 3. 細線化

[解析アルゴリズム](algorithms.ja.md) §3 を参照。

### 3.1 画像端での細線化

同梱スキャンでは、端を複製しない場合、画像の外へ抜けるトラックの最後の
5<!--n:definition--> 点が、法線方向に測って高さの稜線から中央値で 3.9<!--m:border_drift.plain.end_median_px--> px 離れており、繊維の
中ほどの 0.9<!--m:border_drift.plain.middle_median_px--> px と対比される。複製すると、端の点は稜線から 1.0<!--m:border_drift.padded.end_median_px--> px になる
（実験 border_drift）。12<!--c:lib/skeletonizer.py::DEFAULT_BORDER_PAD--> px の縁帯より内側のスケルトンは、同梱スキャン
5<!--m:border_padding.identical_inside_band--> 枚すべてで本補正の有無によらず完全に一致した（実験 border_padding）。ただし
これは保証ではない。

### 3.2 `bp_height` と繊維の高さ

既定の `bp_height` 10<!--c:lib/pipeline.py::ProcParams.bp_height--> nm は、どの同梱スキャンでもスケルトン下の高さの
中央値（1.7<!--m:bg_stats.hplantTOC.skeleton_height_median_nm-->〜7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> nm、§1.1）より高い。最初のスケルトンの分岐点の高さ
（実験 branch_pruning）は、チュニケートのスキャンでは中央値 9.3<!--m:branch_pruning.tunicate.bp_height_median_nm--> nm で、分岐点の
41<!--m:branch_pruning.tunicate.bp_at_or_above_percent--> % が `bp_height` に届く。ほかのスキャンではひとつも届かない（中央値は高等植物の
スキャンで 1.9<!--m:branch_pruning.hplantTOC.bp_height_median_nm--> nm、Bruker のスキャンで 2.0<!--m:branch_pruning.NDTOC.bp_height_median_nm--> nm、人工のスキャンで 7.9<!--m:branch_pruning.art_iso.bp_height_median_nm--> nm と
7.6<!--m:branch_pruning.art_aniso.bp_height_median_nm--> nm）。そこではすべての分岐点が「低い」になり、高さによる区別は何もしない。

チュニケートの高さ画像に重ねて描くと、`bp_height` 以上の分岐点は、2<!--n:count--> 本の繊維が
交差する場所か、1<!--n:count--> 本がもう 1<!--n:count--> 本に合流する場所にある。重なった 2<!--n:count--> 本の繊維の高さが
足し合わされる場所である。それより低い分岐点にも、交差や合流が含まれる。たとえば
スキャンの下部の絡まりにある、細い繊維どうしの交差である。そのため、このスキャン
では、分岐点が低いことは偽の枝であることの印にならない。

高さで決める枝刈りは、最終的なスケルトンをほとんど変えない。この処理を外すと、
変わるスケルトンの画素は、チュニケートのスキャンで 7975<!--m:branch_pruning.tunicate.final_pixels--> 画素のうち 1<!--m:branch_pruning.tunicate.skipped.final_changed_pixels--> 画素、
高等植物のスキャンで 1789<!--m:branch_pruning.hplantTOC.final_pixels--> 画素のうち 24<!--m:branch_pruning.hplantTOC.skipped.final_changed_pixels--> 画素、Bruker のスキャンで 9030<!--m:branch_pruning.NDTOC.final_pixels--> 画素のうち
161<!--m:branch_pruning.NDTOC.skipped.final_changed_pixels--> 画素、人工のスキャンで 0<!--m:branch_pruning.art_iso.skipped.final_changed_pixels--> 画素である。すべての分岐点を「低い」として扱っても、
チュニケートのスキャンで変わる画素は 0<!--m:branch_pruning.tunicate.all_low.final_changed_pixels--> である。この処理が刈る短い腕は、
[解析アルゴリズム](algorithms.ja.md) §3.5 のとげ刈りが、長さだけで判断してもう一度
刈るからである。とげ刈りを止めると、この処理を外したときに変わる画素は、同じ 3<!--n:count--> 枚の
スキャンでそれぞれ 139<!--m:branch_pruning.tunicate.spurs_off.skipped.final_changed_pixels-->、161<!--m:branch_pruning.hplantTOC.spurs_off.skipped.final_changed_pixels-->、899<!--m:branch_pruning.NDTOC.spurs_off.skipped.final_changed_pixels--> 画素になる。

### 3.3 ループの囲み

同梱スキャンでは、マスク内部の穴が残すループ 1<!--n:count--> つが、その輪の上に分岐点を
1<!--m:loop_candidates.all.branch_points_range[0]-->〜4<!--m:loop_candidates.all.branch_points_range[1]--> 個作る。充填の大きさの条件を満たす 18<!--m:loop_candidates.candidates--> 個の囲みは、高さ画像の
目視ですべて繊維の内側（10<!--m:loop_candidates.fiber.count--> 個）か交差（8<!--m:loop_candidates.crossing.count--> 個）にあり、内部の高さの
中央値は周囲リッジの中央値の 78<!--m:loop_candidates.all.ratio_percent_range[0]-->〜105<!--m:loop_candidates.all.ratio_percent_range[1]--> % であった（実験 loop_candidates）。
別々の 2<!--n:count--> 本が 2<!--n:count--> 点で接触して囲む細長い隙間で、条件を満たすものは同梱スキャンには
無い。
そうした隙間は、代わりに合成画像で作った（§3.4）。

### 3.4 2 本の繊維が囲む細長い隙間

まっすぐな 2<!--n:count--> 本の繊維がレンズ形の隙間をはさんで分かれ、また合わさる合成画像
24<!--m:loop_sliver.scans--> 枚（断面は高さ 4<!--n:value tried--> nm、標準偏差 1.5<!--n:value tried-->・2<!--n:value tried-->・3<!--n:value tried--> px のガウス形、隙間の幅は 4<!--n:value tried-->〜12<!--n:value tried--> px。
実験 loop_sliver）では、`collapse_skeleton_loops` が調べる大きさの囲みが 5<!--m:loop_sliver.candidates--> 個できた。
内側の高さの中央値は、周りの尾根の 53<!--m:loop_sliver.ratio_percent_range[0]-->〜97<!--m:loop_sliver.ratio_percent_range[1]--> % であった。近い 2<!--n:count--> 本の繊維の斜面が
重なるからである。そのため 5<!--m:loop_sliver.filled--> 個とも 0.3<!--c:lib/skeletonizer.py::DEFAULT_LOOP_HEIGHT_RATIO--> のチェックを通って塗りつぶされ、描いて
みると、2<!--n:count--> 本の繊維は隙間の真ん中を通る 1<!--n:count--> 本の線にまとめられていた。隙間がもっと
広いと、囲みが `max_loop_area` より大きくなり、2<!--n:count--> 本のまま残った。これらの画像では、
このチェックが塗りつぶしを止めたことは 1<!--n:count--> 度も無かった。

### 3.5 2 つの刈り取りの端の幅

枝刈り（解析アルゴリズムの §3.3）は、画像の端から `branch_length`（12<!--c:lib/pipeline.py::ProcParams.branch_length--> px）以内の端点を
調べず、とげ刈り（同 §3.5）は、端から 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px 以内の腕を刈らない。各テスト入力を、片方の
幅を相手の値に変えて 1<!--n:count--> つずつ細線化した（実験 border_margins）。

| 入力 | 枝刈りを 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px にしたとき変わった画素 | 端からの最大の距離 (px) | とげ刈りを 12<!--c:lib/pipeline.py::ProcParams.branch_length--> px にしたとき変わった画素 | 端からの最大の距離 (px) |
|---|---|---|---|---|
| チュニケート CNF | 0<!--m:border_margins.tunicate.branch_margin_2.changed_px--> | 0<!--m:border_margins.tunicate.branch_margin_2.farthest_from_border_px--> | 10<!--m:border_margins.tunicate.spur_margin_wide.changed_px--> | 12<!--m:border_margins.tunicate.spur_margin_wide.farthest_from_border_px--> |
| 人工、等方 | 1<!--m:border_margins.art_iso.branch_margin_2.changed_px--> | 9<!--m:border_margins.art_iso.branch_margin_2.farthest_from_border_px--> | 2<!--m:border_margins.art_iso.spur_margin_wide.changed_px--> | 9<!--m:border_margins.art_iso.spur_margin_wide.farthest_from_border_px--> |
| 人工、異方 | 0<!--m:border_margins.art_aniso.branch_margin_2.changed_px--> | 0<!--m:border_margins.art_aniso.branch_margin_2.farthest_from_border_px--> | 0<!--m:border_margins.art_aniso.spur_margin_wide.changed_px--> | 0<!--m:border_margins.art_aniso.spur_margin_wide.farthest_from_border_px--> |
| 高等植物 TOC | 0<!--m:border_margins.hplantTOC.branch_margin_2.changed_px--> | 0<!--m:border_margins.hplantTOC.branch_margin_2.farthest_from_border_px--> | 0<!--m:border_margins.hplantTOC.spur_margin_wide.changed_px--> | 0<!--m:border_margins.hplantTOC.spur_margin_wide.farthest_from_border_px--> |
| Bruker NDTOC | 8<!--m:border_margins.NDTOC.branch_margin_2.changed_px--> | 7<!--m:border_margins.NDTOC.branch_margin_2.farthest_from_border_px--> | 21<!--m:border_margins.NDTOC.spur_margin_wide.changed_px--> | 13<!--m:border_margins.NDTOC.spur_margin_wide.farthest_from_border_px--> |
描いてみると、枝刈りの幅を狭めると、端へ向かう短い腕が刈られた。とげ刈りの幅を
広げると、コードでは刈られる、端のすぐそばの短いとげが残った。どちらの場合も、
変化は端に沿った帯の中に収まる。2<!--n:count--> つの幅が違う理由は見つからなかった。

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
中点、頂点）のうち頂点が 5<!--m:synthetic_centerline.ribbons.crest_farthest_of_three--> 本すべてで軸から最も離れ、既定の線の
1.1<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->〜1.4<!--m:synthetic_centerline.ribbons.crest_over_default_range[1]--> 倍であった（横方向のずれの二乗平均平方根）。またキンク規則が、円形の
対照繊維を含むリボンの走査 6<!--m:synthetic_centerline.ribbons.count--> 枚で報告したキンクは 0<!--m:synthetic_centerline.ribbons.kinks_reported--> 件であった（実験
synthetic_centerline）。半値より低いレベルが一様に良かったわけではない。1/4 高さの
中点はリボン 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> 本中 4<!--m:synthetic_centerline.ribbons.quarter_closer_than_default--> 本で既定の線より軸に近かったが、細い円形の対照繊維
では背景の凹凸に最大 3.5<!--m:synthetic_centerline.G_circle_d3.max_nm.quarter_max--> nm 引き寄せられた。

**なぜ 1/4 幅か。** 平滑化の幅は、2<!--n:count--> つの特徴がどこまで近づくと中心線がそれらを
1<!--n:count--> つに均してしまうかを決める。合成データ一式の同じ向きのコーナー対で調べた。
8<!--m:synthetic_centerline.pairs--> 枚の走査のそれぞれに、1〜3<!--n:value tried--> $W$ 離れた 60<!--n:value tried--> 度のコーナーが 2<!--n:count--> つある。

| 枠とオフセットの平滑化 | 1<!--n:count--> つの折れと判定された組 | コーナー頂点から中心線までの距離（中央値。間隔ごとの範囲） | 真の中心線までの距離（中央値） |
|---|---|---|---|
| $W/2$ | 8<!--m:synthetic_centerline.pairs--> 組中 2<!--m:synthetic_centerline.pairs_w2.merged_pairs--> 組 | 0.97<!--m:synthetic_centerline.pairs_w2.vertex_median_px_range[0]-->〜1.17<!--m:synthetic_centerline.pairs_w2.vertex_median_px_range[1]--> px | 0.12<!--m:synthetic_centerline.pairs_w2.centerline_median_px--> px |
| $W/4$（既定） | 8<!--m:synthetic_centerline.pairs--> 組中 0<!--m:synthetic_centerline.pairs_w4.merged_pairs--> 組 | 0.63<!--m:synthetic_centerline.pairs_w4.vertex_median_px_range[0]-->〜0.84<!--m:synthetic_centerline.pairs_w4.vertex_median_px_range[1]--> px | 0.10<!--m:synthetic_centerline.pairs_w4.centerline_median_px--> px |

**既知の中心線に対する精度。** 合成データ一式の A〜F 群の走査 60<!--m:synthetic_centerline.scans_af--> 枚（球状の探針で
描画。コーナー、ジグザグ、コーナー対、端に近いコーナー、直線、円弧、蛇行、交差、
分岐）で比べた結果は次のとおりである。

| | 真の中心線までの距離（中央値） | 同 95<!--n:definition--> パーセンタイル | 輪郭長の誤差（スキャン群ごとの範囲） |
|---|---|---|---|
| 半値中点の中心線 | 0.11<!--m:synthetic_centerline.half_max_025w.median_px--> px | 0.35<!--m:synthetic_centerline.half_max_025w.p95_px--> px | −1.5<!--m:synthetic_centerline.half_max_025w.length_error_percent_range[0]-->〜+0.5<!--m:synthetic_centerline.half_max_025w.length_error_percent_range[1]--> % |
| スケルトントラック（補正済みチェーンコード長） | 0.29<!--m:synthetic_centerline.skeleton_track.median_px--> px | 0.90<!--m:synthetic_centerline.skeleton_track.p95_px--> px | −1.4<!--m:synthetic_centerline.skeleton_track.length_error_percent_range[0]-->〜+2.2<!--m:synthetic_centerline.skeleton_track.length_error_percent_range[1]--> % |

### 4.3 選べる中心線の比較

表を読むときは 2<!--n:count--> 点に注意してほしい。

- **距離の中央値**は、合成データ一式の A〜F 群の群ごとに求めた、真の中心線まで
  の距離の中央値（nm）であり、欄には群全体での範囲を示す（実験
  synthetic_centerline）。
- **実スキャン**は、目視基準に対し超過回転規則で採点した結果で、「検出 /
  見落とし / どの印とも一致しない折れ」の件数である。印から 1〜2<!--n:definition--> 幅ずれた検出
  （§4.4 の表の「印から 1〜2<!--n:definition--> 幅ずれて検出」）と、1<!--n:count--> つの検出が 2<!--n:count--> つの印に
  またがった「統合」はこの表に含めていないので、検出と見落としの和は 64<!--m:kink_reference.clear_marks--> に
  ならない。採点したのは 3<!--n:count--> 種類だけである。

| `centerline_method` | 距離の中央値（nm） | 実スキャン | 備考 |
|---|---|---|---|
| `"half_max_025w"`（既定） | 0.21<!--m:synthetic_centerline.half_max_025w.group_median_nm_range[0]-->〜0.24<!--m:synthetic_centerline.half_max_025w.group_median_nm_range[1]--> | 60<!--m:kink_reference.default.found--> / 3<!--m:kink_reference.default.missed--> / 64<!--m:kink_reference.default.false--> | |
| `"half_max_05w"` | 0.20<!--m:synthetic_centerline.half_max_05w.group_median_nm_range[0]-->〜0.25<!--m:synthetic_centerline.half_max_05w.group_median_nm_range[1]--> | 56<!--m:kink_reference.hm05.found--> / 4<!--m:kink_reference.hm05.missed--> / 43<!--m:kink_reference.hm05.false--> | 採点した 3<!--n:count--> 種類の中で一致しない折れが最も少ない。ただし合成の同じ向きのコーナー対 8<!--m:synthetic_centerline.pairs--> 組中 2<!--m:synthetic_centerline.pairs_w2.merged_pairs--> 組で 2<!--n:count--> つのコーナーを 1<!--n:count--> つにまとめ、平滑化をわずかに強めると見落としが 10〜13<!--m:kink_reference.hm05_stronger.missed_range--> 件に増えた。 |
| `"skeleton_pixels"` | 0.54<!--m:synthetic_centerline.skeleton_pixels.group_median_nm_range[0]-->〜0.62<!--m:synthetic_centerline.skeleton_pixels.group_median_nm_range[1]--> | 62<!--m:kink_reference.skeleton_pixels.found--> / 0<!--m:kink_reference.skeleton_pixels.missed--> / 135<!--m:kink_reference.skeleton_pixels.false--> | 階段状のギザつきと分岐部での振れを折れとして読んでしまう。 |
| `"smoothed_skeleton_05w"`、`"smoothed_skeleton_1w"` | 0.33<!--m:synthetic_centerline.smoothed_skeleton_05w.group_median_nm_range[0]-->〜0.56<!--m:synthetic_centerline.smoothed_skeleton_05w.group_median_nm_range[1]--> / 0.39<!--m:synthetic_centerline.smoothed_skeleton_1w.group_median_nm_range[0]-->〜0.95<!--m:synthetic_centerline.smoothed_skeleton_1w.group_median_nm_range[1]--> | 採点なし | |
| `"quarter_max"` | 0.20<!--m:synthetic_centerline.quarter_max.group_median_nm_range[0]-->〜0.24<!--m:synthetic_centerline.quarter_max.group_median_nm_range[1]--> | 採点なし | ねじれリボン 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> 本中 4<!--m:synthetic_centerline.ribbons.quarter_closer_than_default--> 本で既定より軸に近いが、細い円形の対照繊維では背景の凹凸に最大 3.5<!--m:synthetic_centerline.G_circle_d3.max_nm.quarter_max--> nm 引き寄せられた。 |
| `"centroid"` | 0.32<!--m:synthetic_centerline.centroid.group_median_nm_range[0]-->〜0.38<!--m:synthetic_centerline.centroid.group_median_nm_range[1]--> | 採点なし | |
| `"crest"` | 0.42<!--m:synthetic_centerline.crest.group_median_nm_range[0]-->〜0.48<!--m:synthetic_centerline.crest.group_median_nm_range[1]--> | 採点なし | ねじれリボン 5<!--m:synthetic_centerline.ribbons.crest_farthest_of_three--> 本すべてで軸から最も離れた（既定の 1.1<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->〜1.4<!--m:synthetic_centerline.ribbons.crest_over_default_range[1]--> 倍）。 |

### 4.4 目視基準との比較

「一致なし」は、どの印とも一致しない報告された折れの件数で、以下で誤検出と
呼ぶのはこれである。

| 規則 | 検出 | 印から 1〜2<!--n:definition--> 幅ずれて検出 | 見落とし | 一致なし |
|---|---|---|---|---|
| 超過回転規則（中心線上） | 60<!--m:kink_reference.default.found--> | 1<!--m:kink_reference.default.displaced--> | 3<!--m:kink_reference.default.missed--> | 64<!--m:kink_reference.default.false--> |
| 以前の折れ線規則（スケルトントラック上） | 52<!--m:kink_reference.old_rule.found--> | 4<!--m:kink_reference.old_rule.displaced--> | 8<!--m:kink_reference.old_rule.missed--> | 76<!--m:kink_reference.old_rule.false--> |

以前の規則の行は、同じ画像の追跡済みスケルトントラックに、形式 1.0<!--n:bundle format version--> の
バンドルのために残してある `KinkDetector.kinks_and_decomposed_from_track`
（`kink_decompose_px` = 3<!--c:lib/pipeline.py::ProcParams.kink_decompose_px--> px、`kinkangle_deg` = 150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg--> 度）を適用して採点した。

規則の長さは、$W$ が画像の分解能であることから決めた $W$ の倍数であり、この基準で
確かめはしたが、合わせ込んではいない。どれか 1<!--n:count--> つを隣の値に変えると、検出
できた明瞭なキンクは 56〜62<!--m:kink_reference.sens_all.found_range--> 件、一致なしは 48〜80<!--m:kink_reference.sens_all.false_range--> 件の範囲で動いた（既定は
それぞれ 60<!--m:kink_reference.default.found--> 件と 64<!--m:kink_reference.default.false--> 件）。検出が最も減ったのは平滑化を強める側で、向きの
平滑化 0.35<!--n:value tried--> W で 56<!--m:kink_reference.sens_heading_0.35.found--> 件、中心線の平滑化 ×1.4<!--n:value tried--> で 57<!--m:kink_reference.sens_line_x1.4.found--> 件であった。

| 長さ | 既定値 | 試した隣の値 |
|---|---|---|
| 中心線の平滑化 | W/4 | ×0.6<!--n:value tried-->、×1.4<!--n:value tried--> |
| 窓の半長 $c$ | 0.75<!--c:lib/kink_detector.py::_CORE_WIDTHS--> W | 0.6<!--n:value tried--> W、0.9<!--n:value tried--> W |
| 脇の長さ $f$ | 1.0<!--c:lib/kink_detector.py::_FLANK_WIDTHS--> W | 0.75<!--n:value tried--> W、1.5<!--n:value tried--> W |
| 向きの平滑化 $\sigma$ | 0.25<!--c:lib/kink_detector.py::_HEADING_SIGMA_WIDTHS--> W | 0.15<!--n:value tried--> W、0.35<!--n:value tried--> W |
| 端の範囲 | 1.5<!--c:lib/kink_detector.py::END_MARGIN_WIDTHS--> W | 1.0<!--n:value tried--> W、2.0<!--n:value tried--> W |
| 抑制半径 | 0.75<!--c:lib/kink_detector.py::_SUPPRESS_WIDTHS--> W | 0.5<!--n:value tried--> W、1.0<!--n:value tried--> W |

窓の回転そのものの極大から取る候補を除くと、明瞭な基準キンクの検出は
60<!--m:turn_maxima.with.found--> 件から 56<!--m:turn_maxima.without.found--> 件に減り、一致しない折れは 64<!--m:turn_maxima.with.false--> 件から 47<!--m:turn_maxima.without.false--> 件に減った（実験
turn_maxima）。

### 4.5 キンクとして保存する角度

鋭い合成コーナーでは、探針と中心線が頂点を丸めるため、超過回転は実際より
小さく読まれた。

| コーナーの回転角 | 読まれた超過回転 |
|---|---|
| 40<!--n:value tried--> 度 | 37〜38<!--m:synthetic_kinks.corner40.excess_read_range_deg--> 度 |
| 60<!--n:value tried--> 度 | 52〜56<!--m:synthetic_kinks.corner60.excess_read_range_deg--> 度 |
| 90<!--n:value tried--> 度 | 83〜85<!--m:synthetic_kinks.corner90.excess_read_range_deg--> 度 |
| 120<!--n:value tried--> 度 | 101〜110<!--m:synthetic_kinks.corner120.excess_read_range_deg--> 度 |

このため、しきい値をわずかに上回る折れが下回って読まれることがある。テスト
スイートで 33.5<!--m:test_suite_bend.drawn_turn_deg--> 度に描いた折れは 26.5<!--m:test_suite_bend.read_excess_deg--> 度と読まれる（実験 test_suite_bend）。
キンクとして保存する角度を、180<!--n:definition--> 度から超過回転を引いた値ではなく腕から読むのは
このためである。10<!--c:scripts/kink_rule_sweep.py::TIP_RADIUS_NM--> nm の探針で描画した内角 120<!--n:example-->・140<!--n:example-->・145<!--n:example--> 度の合成
コーナーでは、見つかったコーナーについて、3<!--c:scripts/kink_rule_sweep.py::len(NOISES_NM)--> つのノイズ水準をまとめた角度の
誤差の中央値は次のとおりであった。

| 見かけ幅 | 腕のなす角 | 180<!--n:definition--> 度 − 超過回転 |
|---|---|---|
| 3<!--m:kink_rule_sweep.W5.measured_width_px--> px | 4.2<!--m:kink_rule_sweep.W5.arm_error_deg--> 度 | 4.6<!--m:kink_rule_sweep.W5.excess_error_deg--> 度 |
| 5.5<!--m:kink_rule_sweep.W8.measured_width_px--> px | 1.7<!--m:kink_rule_sweep.W8.arm_error_deg--> 度 | 7.9<!--m:kink_rule_sweep.W8.excess_error_deg--> 度 |
| 11<!--m:kink_rule_sweep.W16.measured_width_px--> px | 1.7<!--m:kink_rule_sweep.W16.arm_error_deg--> 度 | 3.4<!--m:kink_rule_sweep.W16.excess_error_deg--> 度 |

### 4.6 合成形状での結果

- 合成ジグザグでは、1.5〜3<!--n:value tried--> $W$ 離れたコーナーはすべて見つかった
  （30<!--m:synthetic_kinks.zigzag_1.5W_up.clear--> 件中 30<!--m:synthetic_kinks.zigzag_1.5W_up.found--> 件）が、1<!--n:value tried--> $W$ 離れたコーナーは 10<!--m:synthetic_kinks.zigzag1W.clear--> 件中 4<!--m:synthetic_kinks.zigzag1W.found--> 件に
  とどまった。
- 直線の繊維（2<!--m:synthetic_kinks.straight.scans--> 枚で 0<!--m:synthetic_kinks.straight.reported--> 件）、半径 3〜10<!--n:value tried--> $W$ の円弧（6<!--m:synthetic_kinks.arcs.scans--> 枚で 0<!--m:synthetic_kinks.arcs.reported--> 件）、
  交差と分岐（10<!--m:synthetic_kinks.crossings_branches.scans--> 枚で 0<!--m:synthetic_kinks.crossings_branches.reported--> 件）、ねじれリボン（6<!--m:synthetic_centerline.ribbons.count--> 枚で 0<!--m:synthetic_centerline.ribbons.kinks_reported--> 件）では、折れを
  報告しなかった。
- 40<!--n:value tried--> 度以上の孤立したコーナーはすべて見つけた（8<!--m:synthetic_kinks.corners_40_up.clear--> 件中 8<!--m:synthetic_kinks.corners_40_up.found--> 件）。
- 最小曲率半径が 1.6〜1.8<!--m:synthetic_kinks.sines.tightest_radius_w_range--> $W$ の正弦波状の蛇行 4<!--m:synthetic_kinks.sines.scans--> 枚では、12<!--m:synthetic_kinks.sines.reported--> 件の折れを
  報告した。半径が約 $2.9\,W$ を下回ると窓の中だけで 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v--> 度を超えて回り、
  曲率が急に変わる場所では脇の回転でそれを打ち消しきれないためである。
- 以前の折れ線規則は、同じ円弧と蛇行で 31<!--m:synthetic_kinks.old_rule.arcs_sines_reported--> 件を報告した（実験 synthetic_kinks）。

### 4.7 中心線ごとのノイズ床

ノイズ床を既定で無効にしているのは、誤検出と本物のキンクを分けられなかった
ためである。目視基準で採点した結果（`scripts/kink_reference_score.py`）は次の
とおりである。

| ノイズ床の倍数 | 失った明瞭なキンク | 減った誤検出 |
|---|---|---|
| 3<!--n:value tried--> | 3<!--m:kink_reference.noise3.lost--> | 6<!--m:kink_reference.noise3.fewer_false--> |
| 4<!--n:value tried--> | 5<!--m:kink_reference.noise4.lost--> | 10<!--m:kink_reference.noise4.fewer_false--> |

これらのスキャンの誤検出は、丸みのある曲がり、絡まり、交差の近くの折れ、
それに超過回転がしきい値をわずかに上回るだけの浅い折れであって、ノイズでは
ない。64<!--m:kink_reference.default.false--> 件のうち 28<!--m:kink_reference.default.false_excess_30_40--> 件は超過回転が 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v-->〜40<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|190 - v--> 度である。そのうち
11<!--m:kink_reference.default.false_arm_turn_below_threshold--> 件は、腕から読んだ回転（180<!--n:definition--> 度 − `ka`）が 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v--> 度を下回る。腕の角度は
判定に使う超過回転とは別に測るためである。また強く折れ曲がった繊維では、その
繊維自身のキンクがノイズ床を押し上げる。失われた明瞭なキンクはそうした繊維に
あった。合成データの掃引では、ノイズ床はどの条件でも見つかるコーナーを変えず、
偽陽性を変えたのは最も細かい画素サイズと最も強いノイズの条件（幅 11<!--m:kink_rule_sweep.W16.measured_width_px--> px、
画素ノイズ 0.30<!--n:value tried--> nm）だけであった。その条件でも 1<!--n:definition--> µm あたりの偽陽性を
3.9<!--m:kink_rule_sweep.W16.n0.30.base.fp_per_um--> から 3.7<!--m:kink_rule_sweep.W16.n0.30.k3.fp_per_um--> に減らしただけで、その条件ですでに見落としていたコーナーは
戻らなかった。

### 4.8 掃引で規則が働いた範囲

ここでの見かけ幅は、合成画像の設計値ではなく、各設定の直線の繊維でパイプラインが
実際に測った $W$ である。各コーナーは 3<!--c:scripts/kink_rule_sweep.py::len(NOISES_NM)--> つのノイズ水準と 2<!--c:scripts/kink_rule_sweep.py::len(SEEDS)--> つのシードで
描き、角度と幅ごとに 6<!--m:kink_rule_sweep.W5.kink120.cases--> 枚である。

- 3<!--m:kink_rule_sweep.W5.measured_width_px--> px では、内角 120<!--n:example--> 度と 145<!--n:example--> 度のコーナーはすべて見つかり（6<!--m:kink_rule_sweep.W5.kink145.cases--> 枚中
  6<!--m:kink_rule_sweep.W5.kink120.found--> 枚と 6<!--m:kink_rule_sweep.W5.kink145.found--> 枚）、140<!--n:example--> 度は 6<!--m:kink_rule_sweep.W5.kink140.cases--> 枚中 4<!--m:kink_rule_sweep.W5.kink140.found--> 枚であった。見落とした 140<!--n:example--> 度の例
  でもコーナーを含む繊維は途切れずに追跡されていたので、見落としは追跡ではなく
  規則の側で起きている。140<!--n:example--> 度が 145<!--n:example--> 度より見つかりにくかった原因は特定して
  いない。
- 5.5<!--m:kink_rule_sweep.W8.measured_width_px--> px では、すべてのコーナーが見つかった（6<!--m:kink_rule_sweep.W8.kink140.cases--> 枚中 6<!--m:kink_rule_sweep.W8.kink120.found-->・6<!--m:kink_rule_sweep.W8.kink140.found-->・6<!--m:kink_rule_sweep.W8.kink145.found--> 枚）。
- 11<!--m:kink_rule_sweep.W16.measured_width_px--> px では、各角度とも 6<!--m:kink_rule_sweep.W16.kink140.cases--> 枚中 5<!--m:kink_rule_sweep.W16.kink120.found-->・5<!--m:kink_rule_sweep.W16.kink140.found-->・5<!--m:kink_rule_sweep.W16.kink145.found--> 枚であった。画素ノイズ 0.15<!--n:value tried--> nm
  まではすべて見つかり、0.30<!--n:value tried--> nm では 2<!--c:scripts/kink_rule_sweep.py::len(SEEDS)--> 枚中 1<!--m:kink_rule_sweep.W16.n0.30.kink120.found--> 枚であった。このノイズでは、ほぼ
  水平な腕が高さ画像そのものの中で途切れて描かれ、追跡は繊維を多数の断片に
  分け、偽の折れがその腕に集まった。同じ設定の直線・円弧・正弦波の繊維では、
  規則は 1<!--n:definition--> µm あたり 3.9<!--m:kink_rule_sweep.W16.n0.30.base.fp_per_um--> 件の偽の折れを報告した。
- 画素ノイズ 0.15<!--n:value tried--> nm までの直線・円弧・蛇行では、どの幅でも偽陽性は無く、
  165<!--n:example--> 度の曲がりでも無かった。
- 掃引で最も粗い画素サイズ（5.2<!--c:scripts/kink_rule_sweep.py::APPARENT_WIDTH_NM|v / 3--> nm。繊維が占める画素は 3<!--m:kink_rule_sweep.W5.measured_width_px--> px の設定より
  少ない）では、繊維の追跡そのものがほとんど途切れ、幅は測れずに代替値が
  使われ、コーナーは一つも見つからなかった。規則は追跡済みの繊維を受け取って
  判定していたが、真のコーナーに一致する折れは報告しなかった。

### 4.9 端の範囲

実データの同梱スキャン 3<!--n:count--> 枚では、トラック端の 46<!--m:track_ends.hplantTOC.near_branch_percent-->〜68<!--m:track_ends.tunicate.near_branch_percent--> % が分岐点から
3<!--n:definition--> px 以内にある（実験 track_ends）。トラックの端の多くは繊維の本当の終端では
なく、交差での切断である。

端の範囲を $1.0\,W$ にすると、同梱スキャンの誤検出は 64<!--m:kink_reference.default.false--> 件から 80<!--m:kink_reference.sens_end_1.false--> 件に
増え、明瞭なキンクの検出は 1<!--n:count--> 件も増えなかった。$2.0\,W$ にすると誤検出は
49<!--m:kink_reference.sens_end_2.false--> 件に減ったが、既定では判定していた端から 2<!--n:value tried--> $W$ の合成コーナー
（2<!--m:synthetic_kinks.end_cases_per_distance--> 件中 2<!--m:synthetic_kinks.margin_default.end2W.corners_judged--> 件）を判定しなくなった（0<!--m:synthetic_kinks.margin_2W.end2W.corners_judged--> 件）。同梱スキャンで判定しな
かった 48<!--m:kink_reference.default.unjudged--> 件の折れには、明瞭な基準キンクに当たるものは無かった。

### 4.10 頂点高さと中心線上の高さ

各テスト入力の、追跡できるスケルトンのつながった部分すべてについて、既定の中心線を
`KinkDetector` と同じやり方で置き（実験 crest_height）、信頼できる点で、頂点高さと、
中心線の位置で読んだ補正後の高さとを比べた。

| 入力 | 差の中央値 (nm) | 差の 90<!--n:definition--> パーセンタイル (nm) | 中央値、頂点高さに対する % | 90<!--n:definition--> パーセンタイル、頂点高さに対する % |
|---|---|---|---|---|
| チュニケート CNF | 0.072<!--m:crest_height.tunicate.median_nm--> | 0.211<!--m:crest_height.tunicate.p90_nm--> | 0.941<!--m:crest_height.tunicate.median_percent--> | 2.620<!--m:crest_height.tunicate.p90_percent--> |
| 人工、等方 | 0.108<!--m:crest_height.art_iso.median_nm--> | 0.234<!--m:crest_height.art_iso.p90_nm--> | 1.322<!--m:crest_height.art_iso.median_percent--> | 2.829<!--m:crest_height.art_iso.p90_percent--> |
| 人工、異方 | 0.075<!--m:crest_height.art_aniso.median_nm--> | 0.210<!--m:crest_height.art_aniso.p90_nm--> | 1.031<!--m:crest_height.art_aniso.median_percent--> | 2.975<!--m:crest_height.art_aniso.p90_percent--> |
| 高等植物 TOC | 0.012<!--m:crest_height.hplantTOC.median_nm--> | 0.064<!--m:crest_height.hplantTOC.p90_nm--> | 0.712<!--m:crest_height.hplantTOC.median_percent--> | 3.573<!--m:crest_height.hplantTOC.p90_percent--> |
| Bruker NDTOC | 0.024<!--m:crest_height.NDTOC.median_nm--> | 0.128<!--m:crest_height.NDTOC.p90_nm--> | 1.227<!--m:crest_height.NDTOC.median_percent--> | 6.996<!--m:crest_height.NDTOC.p90_percent--> |
頂点高さが中心線上の高さより低いことは、1<!--n:count--> 度も無かった。したがって、中心線の
位置で高さを読むと、繊維は低く出る。差は表のとおり小さいが、いつも低く出る向きで
ある。左右が非対称な断面では、半値の中点が頂点の横にずれるからである。

### 4.11 切り口の近くの高さ

各テスト入力の、長さ 5<!--n:definition--> W 以上のトラックについて、既定の中心線に沿って、端の近くの
頂点高さをそのトラックの頂点高さの中央値で割り、交差で切れた端（分岐点から 3<!--n:definition--> px
以内）と自由な端とに分けて中央値をとった（実験 cut_end_skirt）。人工のスキャンには
切り口が無い。

| 入力 | 切り口の数 | 切り口での比 | 1.05<!--n:definition--> 以下に戻るまでの距離 (W) | 自由な端での比 |
|---|---|---|---|---|
| チュニケート CNF | 49<!--m:cut_end_skirt.tunicate.cut_ends--> | 1.41<!--m:cut_end_skirt.tunicate.cut.ratio_at_end--> | 0.75<!--m:cut_end_skirt.tunicate.cut.back_within_widths--> | 1.03<!--m:cut_end_skirt.tunicate.free.ratio_at_end--> |
| 高等植物 TOC | 7<!--m:cut_end_skirt.hplantTOC.cut_ends--> | 1.31<!--m:cut_end_skirt.hplantTOC.cut.ratio_at_end--> | 1.00<!--m:cut_end_skirt.hplantTOC.cut.back_within_widths--> | 0.93<!--m:cut_end_skirt.hplantTOC.free.ratio_at_end--> |
| Bruker NDTOC | 89<!--m:cut_end_skirt.NDTOC.cut_ends--> | 1.23<!--m:cut_end_skirt.NDTOC.cut.ratio_at_end--> | 0.50<!--m:cut_end_skirt.NDTOC.cut.back_within_widths--> | 0.69<!--m:cut_end_skirt.NDTOC.free.ratio_at_end--> |

距離ごとの変化を描くと、切り口では高さが繊維自身の高さより持ち上がり、幅ひとつ分
ほどのうちに戻る。自由な端には、この持ち上がりが無い。交差での相手繊維の裾が、
分岐点で消した画素の先まで届いているからである。
