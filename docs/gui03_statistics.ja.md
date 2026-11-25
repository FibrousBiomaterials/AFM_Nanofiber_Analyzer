# GUI03 の統計

このページは、GUI03（`guis/GUI03_Fiber_Morphology_Statistics.py`）が計測した
ファイバーから計算する統計を説明します。1 標本とは何か、要約統計量と図をどう
計算するか、画像の枠で切れた輪郭長をどう扱うか、2 つのグループをどう比べるか
です。各段階を実行するコードを引用し、各段階が従う既発表の手法の名前を挙げます。
これにより読者は、結果表の数値をそれを生んだ計算と照らし合わせ、手法の原典の
記述にたどり着けます。著者と年で挙げた文献は、末尾の「参考文献」に並べています。

計測量そのもの、すなわち 1 本のファイバーの高さ・輪郭長・直線度・曲率・キンク数は
`afm_nanofiber_analyzer.measure` が計算します。これは GUI04 のファイバー一覧を埋めるのと
同じコードであり、[GUI04 のファイバー計測](gui04_measurements.ja.md) の §3 で説明して
います。このページはファイバーごとの値から始めます。これらの手法を特定のデータに
適用した結果は [特定のデータでの評価](validation.ja.md) にあります。

## コード片の読み方

各コードブロックは、出典を示すヘッダで始まります。

```text
# source: afm_nanofiber_analyzer/group_compare.py::compare_groups
```

これはファイルと、コードが属する関数・メソッド（`Class.method`）・モジュール定数
です。1 ファイルの複数の定数をカンマ区切りで並べることもあります。`...` だけの行は
省略を表します。コメントと空行はコード片から除き、メソッド本体は字下げを外して
示します。コメント付きのコードを読むには、示されたシンボルを開いてください。

`scripts/check_gui03_docs.py` は、各コード片を、それが示すシンボルと 1 行ずつ
照合し、引用した各シンボルをコメントと docstring を除いて指紋化します。そのどれかの
計算内容が変わると、このページを読み直して指紋を更新するまで検査が失敗します
（§5 参照）。

## 表記規則

| 用語 | 意味 |
|---|---|
| グループ | GUI03 の一覧で 1 つの名前の下に登録したバンドル。グループは 1 つの試料を表し、そのバンドルはまとめて計測・集計する。 |
| 集計単位 | 1 標本を何とするか。`pixel`（スケルトン画素 1 点）、`fiber`（ファイバー 1 本）、`image`（バンドル 1 個）。 |
| 標本 | 選んだ集計単位での、グループの分布の 1 つの値。 |
| 重み | 輪郭長の枠補正（§3）が標本に付ける数。それ以外では標本は重みを持たない。 |

計測量・集計単位・枠の扱いの名前（`contour length`、`fiber`、`Miles-Lantuejoul`
など）は、GUI03 がそのまま表示する固定の英語キーです。このページも同じ形で書きます。

## 1. 1 標本とは何か

### 1.1 計測量ごとに選べる集計単位

各計測量には、GUI03 が選ばせる集計単位が並んでおり、先頭が既定です。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::PARAM_SPECS
PARAM_SPECS = {
PARAM_HEIGHT: {
"slug": "height",
"value_unit": "nm",
"axis_label": "height (nm)",
"units": (UNIT_PIXEL, UNIT_FIBER, UNIT_IMAGE),
...
PARAM_LENGTH: {
"slug": "contour_length",
"value_unit": "nm",
"axis_label": "contour length (nm)",
"units": (UNIT_FIBER, UNIT_IMAGE),
...
"axis_label": "straightness",
"units": (UNIT_FIBER, UNIT_IMAGE),
...
"axis_label": "curvature (rad/" + UNIT_MICROMETER + ")",
"units": (UNIT_FIBER, UNIT_IMAGE),
...
"axis_label": "kink density (" + UNIT_PER_MICROMETER_PLOT + ")",
...
"units": (UNIT_IMAGE,),
```

スケルトン画素ごとにまとめられるのは高さだけです（§1.4）。キンク密度は画像単位
でだけ選べます（§1.3）。

### 1.2 ファイバー 1 本に 1 つの値

`fiber` 単位では、各ファイバーは長さによらず多くても 1 標本を出すため、長い
ファイバーが短いファイバーより重く数えられることはありません。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_fiber_value
def _fiber_value(stat, param: str):
if param == PARAM_HEIGHT:
value = float(stat.height_median_nm)
return None if not np.isfinite(value) else value
if param == PARAM_LENGTH:
return float(stat.length_nm)
if param == PARAM_STRAIGHTNESS:
value = float(stat.straightness)
return None if not np.isfinite(value) else value
return None
```

ファイバーの高さは、中心線に沿った高さ標本の中央値です
（`FiberStats.height_median_nm`。[GUI04 のファイバー計測](gui04_measurements.ja.md)
§3.3–§3.4 参照）。高さや直線度が定義できない（NaN の）ファイバーは、0 ではなく
「標本なし」になります。曲率は別に集めます（`measure.collect_fiber_curvature`）。
ファイバー 1 本に 1 値で、曲率窓より短いファイバーは値を持たず、標本を出しません
（GUI03 はその本数をログに出します）。

### 1.3 画像 1 枚に 1 つの値

`image` 単位では、各バンドルが 1 標本を出します。そのファイバーが出す値の中央値
であり、ファイバーの多い画像が、同じ試料の疎な画像より重く数えられることは
ありません。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._values_from_fiber_stats
def pooled(source_values, source_weights) -> float:
if frame_weighted:
return _summary_stats(
np.asarray(source_values, dtype=float),
np.asarray(source_weights, dtype=float),
)["median"]
return float(np.median(source_values))
...
for _path, stats in per_source:
if param == PARAM_KINK_DENSITY and unit == UNIT_IMAGE:
kinks, judged_um, used = _kink_totals(stats)
if used == 0:
continue
n_fibers += used
n_images += 1
values.append(kinks / judged_um)
continue
...
if not source_values:
continue
n_images += 1
if unit == UNIT_IMAGE:
values.append(pooled(source_values, source_weights))
else:
values.extend(source_values)
if weights is not None:
weights.extend(source_weights)
```

長さが Miles-Lantuéjoul 重み（§3.2）を持つとき、画像の値は §2.1 の重み付き中央値
であり、画像の標本そのものは重みを持ちません。曲率も同じ規則で、バンドルごとに
中央値を 1 つ取ります。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._curvature_values
for _path, curvature in per_fiber:
measurable = curvature[np.isfinite(curvature)]
if measurable.size == 0:
continue
n_fibers += int(measurable.size)
n_images += 1
if unit == UNIT_IMAGE:
values.append(float(np.median(measurable)))
else:
values.extend(measurable.tolist())
```

**キンク密度**は、画像の値が中央値でない唯一の計測量です。画像の全ファイバーの
キンクを足し合わせ、ファイバーの判定長の合計で割ります。

$$\rho_\text{image} = \frac{\sum_f k_f}{\sum_f L_f}$$

ここで $k_f$ はファイバー $f$ のキンク数、$L_f$ はその判定長（µm）です
（`measure.fiber_judged_length_um`。[GUI04 のファイバー計測](gui04_measurements.ja.md)
§3.9）。判定長を持たないファイバーは両方の和から外します。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_kink_totals
def _kink_totals(stats) -> tuple:
kinks = 0
judged_um = 0.0
n_fibers = 0
for stat in stats:
length_um = fiber_judged_length_um(stat)
if not np.isfinite(length_um):
continue
kinks += int(stat.kink_count)
judged_um += length_um
n_fibers += 1
return kinks, judged_um, n_fibers
```

コードが述べる理由は次のとおりです。1 本の密度は、自身の判定長 $L$ に対して
$0, 1/L, 2/L, \dots$ の値しか取れないため、ファイバーごとの密度の分布の形は断片の
長さで決まります。また画像のファイバーの半数以上がキンクを持たないとき、その密度の
中央値は、キンクを持つファイバーがどうであれ 0 になります。まとめた比は、各
ファイバーを判定された長さに比例して数えます。キンク密度が `image` 単位しか選べない
のはこのためです。

### 1.4 スケルトン画素の高さ

`pixel` 単位では、ファイバーを追跡せずに、バンドルのスケルトン画素ごとに高さを
読みます。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._collect_bundle_values
if param == PARAM_HEIGHT and unit == UNIT_PIXEL:
parts, load_errors = self._collect_per_bundle(
skeleton_height_values, bundle_paths,
```

`measure.skeleton_height_values` は、各スケルトン画素の補正済みの高さを残します。
ただし 2 種類の画素を除きます。どちらも繊維が交差・分岐する所にあります。保存された
各分岐点の 3 × 3 の近傍と、スケルトンに沿って測ってその近傍から、バンドルが記録した
見かけの幅の中央値の `CUT_END_EXCLUSION_WIDTHS` 倍より近い画素です。幅を記録して
いないバンドルでは、後者を残します。

```python
# source: afm_nanofiber_analyzer/measure.py::_skeleton_pixel_heights
near_branch = cv2.dilate((np.asarray(arrays["bp"]) > 0).astype(np.uint8), square) > 0
kept = skeleton & ~near_branch
cleared = skeleton & near_branch
...
width = _recorded_median_width(meta)
if width is not None:
cut = kept & (cv2.dilate(cleared.astype(np.uint8), square) > 0)
if cut.any():
zone = CUT_END_EXCLUSION_WIDTHS * width
distance = _distance_along_skeleton(
kept, cut, pixel_aspect_from_meta(meta, cal.shape), zone)
kept &= ~(distance < zone)
return cal[kept], int(pieces), int(pieces - len(excluded))
```

各画素は 1 回ずつ数えるため、ファイバーは画素数に比例して寄与し、画素の細かい
バンドルほど、ファイバー 1 µm あたり多くの画素を出します。これらの標本は試料の
独立な観測ではなく、GUI03 がこれを検定しないのはこのためです（§4.1）。

## 2. 要約統計量と図

### 2.1 平均・標準偏差・四分位数

結果表はグループごとに、平均、標準偏差、中央値、第 1・第 3 四分位数 $Q_1$ と
$Q_3$（および四分位範囲 $Q_3 - Q_1$）、最頻値（§2.2）を報告します。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_summary_stats
def _summary_stats(values: np.ndarray, weights=None) -> dict:
if weights is None:
q1, median, q3 = (
float(v) for v in np.percentile(values, [25.0, 50.0, 75.0])
)
return {
"mean": float(np.mean(values)),
"std": (float(np.std(values, ddof=1)) if np.size(values) > 1
else float("nan")),
"q1": q1, "median": median, "q3": q3,
"std_definition": STD_SAMPLE,
}

total = float(weights.sum())
mean = float(np.sum(values * weights) / total)
variance = float(np.sum(weights * (values - mean) ** 2) / total)
order = np.argsort(values)
sorted_values = values[order]
sorted_weights = weights[order]
cumulative = np.cumsum(sorted_weights)
positions = (cumulative - 0.5 * sorted_weights) / total
q1, median, q3 = (
float(v) for v in np.interp([0.25, 0.5, 0.75], positions, sorted_values)
)
return {
"mean": mean,
"std": float(np.sqrt(variance)),
"q1": q1, "median": median, "q3": q3,
"std_definition": STD_WEIGHTED,
}
```

**重みのない標本。** 標準偏差は標本標準偏差です。

$$s = \sqrt{\frac{1}{n-1}\sum_{i=1}^{n}(x_i - \bar x)^2}$$

値が 1 個のときは定義されません（NaN）。四分位数は、`numpy.percentile` の既定の
方法 `linear` によるもので、NumPy の文書はこれを
Hyndman and Fan (1996) の定義 7 としています。$n$ 個の値を並べたとき、
分位点 $q$ は 0 から数えた位置 $(n-1)q$ にあり、隣り合う値の間を線形補間します。

**重みのある標本**（§3 の枠補正）。平均と標準偏差は重みの合計 $W = \sum_i w_i$ で
割ります。

$$\bar x_w = \frac{1}{W}\sum_i w_i x_i, \qquad s_w = \sqrt{\frac{1}{W}\sum_i w_i (x_i - \bar x_w)^2}$$

四分位数では、並べた値をそれぞれが占める重み区間の中点
$p_i = (\sum_{j \le i} w_j - w_i/2)/W$ に置き、分位点 $q$ をそれらの位置の間の線形
補間で読みます。結果表は、どちらの標準偏差を載せているか（`SD (n-1)` または
`weighted SD`）を示します。コードが重みのない場合に 1 の重みを重み付きの分岐へ渡さず
2 つの分岐を分けているのは、2 つの分位数の定義が厳密には一致しないためです。

### 2.2 ヒストグラムと最頻値

ヒストグラムは、ユーザーが入力した幅と範囲のビンに標本を数えます。標本が重みを
持つときは重み付きで数えます。最頻値は最も高いビンの中心なので、ビンの切り方に
依存します。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_bin_results
counts, _edges = np.histogram(
r["values"], bins=edges, weights=r["weights"], density=False,
)
...
if total > 0:
k = int(np.argmax(counts))
r["mode"] = float((edges[k] + edges[k + 1]) / 2.0)
else:
r["mode"] = float("nan")
r["norm_total"] = total
if r.get("km_beyond", 0.0) > 0.0:
r["norm_total"] = r["weight_total"] + r["km_beyond"]
r["mode"] = float("nan")
```

要約統計量は、入力した範囲の外にあるものも含め全標本から計算し、ビンの外に出た
重みの合計に対する割合をログに出します。Kaplan-Meier 推定（§3.3）では棒を、推定が
表す全ファイバーに対する割合とするため、棒の合計は推定が置けなかった割合だけ 1 に
届かず、最頻値は報告しません。GUI03 は、グループの標本が `MIN_SAMPLES_FOR_SHAPE`
未満のときもその旨を伝えます。それ未満ではヒストグラムが分布の形を示さないためです。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::MIN_SAMPLES_FOR_SHAPE
MIN_SAMPLES_FOR_SHAPE = 8
```

### 2.3 ECDF と箱ひげ図

ECDF は、グループごとに、各値以下にある標本（または重み）の累積割合を描くため、
ビン幅を必要としません。Kaplan-Meier では、推定が置けなかった割合だけ 1 に届かずに
終わります。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._draw_ecdf
cumulative = np.cumsum(weights) / (
float(weights.sum()) + r.get("km_beyond", 0.0))
```

箱ひげ図は、生の標本を Matplotlib に渡すのではなく、結果表の四分位数から描くため、
箱と表が食い違うことはありません。ひげは Tukey (1977) の柵（フェンス）に
従い、箱から四分位範囲の 1.5 倍以内にある最も遠い標本まで伸びます。柵の外の標本は
描きません。Kaplan-Meier 推定で四分位数が定まらないグループ（§3.4）は箱を持たず、
その位置に四分位数のある範囲を書きます。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._draw_box
iqr = r["q3"] - r["q1"]
low_fence = r["q1"] - 1.5 * iqr
high_fence = r["q3"] + 1.5 * iqr
inside = values[(values >= low_fence) & (values <= high_fence)]
```

## 3. 枠で切れた輪郭長

画像の枠に達したファイバーは走査範囲の外へ続いているため、計測した長さは下限値
です。長いファイバーほど短いファイバーより枠に達しやすいため、そうしたファイバーを
残しても外しても、長さの分布は短い側に偏ります。GUI03 は 4 通りの扱い
（`FRAME_MODES`）を用意しています。これは `contour length` にだけ適用します。走査
範囲内の部分の高さ・曲率・キンクは、その部分の計測として有効なままだからです。

| 扱い | 何をするか |
|---|---|
| `include` | すべてのファイバーを計測した長さのまま残す。 |
| `exclude` | 枠に達したファイバーを外す。 |
| `Miles-Lantuejoul` | それらを外し、残った各ファイバーを、枠の内側に収まる確率の逆数で重み付けする（§3.2）。 |
| `Kaplan-Meier` | 自身の端を持つ全ファイバーから長さの分布を推定する。もう一方の端が切れたファイバーは、計測した長さ以上であることが分かっているものとして扱う（§3.3）。`fiber` 単位のみ。 |

### 3.1 `include` と `exclude`

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_apply_frame_mode
def _apply_frame_mode(per_source, frame_mode: str) -> tuple:
if frame_mode == FRAME_KAPLAN_MEIER:
return _apply_kaplan_meier(per_source)
kept = []
report = {"total": 0, "frame": 0, "lower_bound": 0, "unrecorded": []}
for path, stats in per_source:
if any(s.touches_frame is None for s in stats):
report["unrecorded"].append(path)
continue
survivors = [s for s in stats if not s.touches_frame]
report["total"] += len(stats)
report["frame"] += len(stats) - len(survivors)
report["lower_bound"] += sum(1 for s in survivors if s.cut_end_count)
kept.append((path, survivors))
return (per_source if frame_mode == FRAME_INCLUDE else kept), report
```

ファイバーは、そのスケルトントラックの画素が解析配列の最外周の行・列にあるとき、枠に
達しています（`FiberStats.touches_frame`）。ファイバーがこの判定を記録していない
バンドルは、`include` ではそのまま残し、それ以外の扱いでは丸ごと外します。どちらの
場合もログにその名前を出します。`include`・`exclude`・`Miles-Lantuejoul` では、枠に
達していないファイバーのうち、繊維の端ではなく切断である端を持つもの
（`cut_end_count`。たとえば交差で切れたもの）の本数もログに出します。その長さも
下限値であり、それを扱うのは Kaplan-Meier 推定だけです。

### 3.2 `Miles-Lantuejoul`: 収まる確率による重み付け

この扱いの名前は、Miles と Lantuéjoul の縁補正（Miles 1974）から
来ています。標本抽出の窓の内側に完全に収まった対象だけを残すとき、残した各対象を、
その広がりを持つ対象が窓の内側に完全に収まる確率の逆数で重み付けするものです。
<!-- TODO(review): Lantuéjoul によるこの補正の文献はまだ特定していない。確認した
うえで参考文献に加える。 -->
GUI03 は広がりとしてスケルトントラックの外接矩形を使います。$W \times H$ 画素の
画像と $w \times h$ 画素の矩形について、最外周の行・列を避けて矩形を置ける位置は
$(W-1-w)(H-1-h)$ 通りであり、1 画素の重みが 1 になるよう正規化します。

$$\omega = \frac{(W-2)(H-2)}{(W-1-w)(H-1-h)}$$

```python
# source: afm_nanofiber_analyzer/measure.py::_frame_weight
def _frame_weight(
fiber: Fiber,
frame: Optional[Tuple[int, int]],
) -> float:
if frame is None or _reaches_frame(fiber, frame):
return float("nan")
height, width = frame
sx, sy = skeleton_track(fiber)
if len(sx) == 0:
return float("nan")
box_w = int(np.max(sx) - np.min(sx)) + 1
box_h = int(np.max(sy) - np.min(sy)) + 1
free_x = width - 1 - box_w
free_y = height - 1 - box_h
if free_x <= 0 or free_y <= 0:
return float("nan")
return float((width - 2) * (height - 2)) / float(free_x * free_y)
```

重みは画素数の比なので画素の大きさは打ち消し合い、大きさの違う走査の重み付き
ファイバーをまとめられます。補正するのは枠だけで、交差で切れたファイバーは
依然として全体であるかのように数えます。

重みには上限がなく、外接矩形が画像をほぼ埋めるファイバーがグループの重みの大半を
担うことがあります。そのため GUI03 はグループごとに、重みの有効標本数
（Kish 1965）と、最も重いファイバーが重みの合計に占める割合をログに
出します。

$$n_\text{eff} = \frac{\left(\sum_i \omega_i\right)^2}{\sum_i \omega_i^2}$$

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._run_comparison
"n_effective": (
float(wts.sum() ** 2 / np.sum(wts ** 2))
if frame_weighted and wts is not None and wts.size else None
),
"max_weight_share": (
float(wts.max() / wts.sum())
if frame_weighted and wts is not None and wts.size else None
),
```

結果表の標本数は、計測したファイバーの本数のままです。重みの合計は推定した本数で
あり、観測した本数ではないためです。

### 3.3 `Kaplan-Meier`: 片端で切れた長さを打ち切り観測として扱う

Kaplan-Meier 推定量（Kaplan and Meier 1958）は、一部の観測が記録した
値を超えることしか分かっていない（右側打ち切り）観測から分布を推定します。GUI03 は
これをファイバーの長さに当てはめます。そのために、ファイバーの 2 つの端のうち、
交差での切断でも枠上でもない、自身の端がいくつあるかを数えます。

```python
# source: afm_nanofiber_analyzer/measure.py::fiber_real_end_count
def fiber_real_end_count(stat: "FiberStats") -> Optional[int]:
if (stat.touches_frame is None or stat.cut_end_count is None
or stat.frame_end_count is None):
return None
own = max(0, 2 - int(stat.cut_end_count) - int(stat.frame_end_count))
if stat.touches_frame and stat.frame_end_count == 0:
own = min(own, 1)
return own
```

端以外の場所でスケルトンが枠に触れるファイバーは、そこで走査範囲の外へ出るため、
自身の端は多くても 1 つとして数えます。

自身の端の 1 つずつが、ファイバーの端から測った長さの観測の起点になります。両端とも
自身の端であるファイバーは、その長さで完全な観測を 2 つ与えます。自身の端が 1 つ
だけのファイバーは、計測した長さで打ち切られた観測を 1 つ与えます。自身の端の無い
ファイバーは何も与えません。長さ $\ell_j$ に完全な観測が $d_j$ 個あり、そこでまだ
リスクにある観測（長さ $\ell_j$ 以上のすべての観測）が $r_j$ 個のとき、長さ $\ell$
より長いファイバーの割合の推定は

$$\hat S(\ell) = \prod_{\ell_j \le \ell} \left(1 - \frac{d_j}{r_j}\right)$$

であり、各段 $\hat S(\ell_{j-1}) - \hat S(\ell_j)$ が、長さ $\ell_j$ にあるファイバーの
割合です。同じ長さでは、完全な観測を打ち切り観測より先に数えます。

```python
# source: afm_nanofiber_analyzer/measure.py::kaplan_meier_length_weights
lengths = np.asarray(lengths, dtype=np.float64)
own = np.asarray(own_ends, dtype=np.int64)
weights = np.zeros(lengths.size, dtype=np.float64)
observations = float(own.sum())
if observations == 0.0:
return weights, 1.0
order = np.lexsort((own != 2, lengths))
at_risk = observations
survival = 1.0
i = 0
while i < order.size:
j = i
while j < order.size and lengths[order[j]] == lengths[order[i]]:
j += 1
tied = order[i:j]
complete = tied[own[tied] == 2]
if complete.size and at_risk > 0.0:
step = survival * (2.0 * complete.size) / at_risk
weights[complete] = step / complete.size * (observations / 2.0)
survival -= step
at_risk -= float(own[tied].sum())
i = j
return weights, max(survival, 0.0)
```

各長さの段を、その長さで全長を見たファイバーで分け、観測数の半分を掛けるため、
重みはファイバーの本数を数えます。2 つ目の戻り値は、全長を見た最長のファイバーの
後に $\hat S$ に残る分で、推定がそれより長い側に、どこかは分からないまま置く
ファイバーの割合です。たとえば、全長を見た長さ 1 と 3 のファイバーと、片端が切れた
長さ 2 のファイバーには、重み 1、1.5、0 が付きます。切れたファイバーは 2 より長い
ため、その分はそれより長い全長を見たファイバーに回ります。

コードは推定が拠って立つ前提を述べています。ファイバーが走査範囲より広い領域に
一様に散らばり、ファイバーに沿った交差がその長さによらなければ、切断や枠による
打ち切りはファイバーの長さと独立に起きる、というものです。切断したランダムな線分で
推定がどうだったかは [特定のデータでの評価](validation.ja.md) の §6.3 にあります。

GUI03 はグループごとに、その全バンドルをまとめて 1 回推定します。統計に重みを持って
入るのは、全長を見たファイバーだけです。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_apply_kaplan_meier
lengths = [s.length_nm for _p, stats, _o in recorded for s in stats]
own = [o for _p, _s, owns in recorded for o in owns]
weights, rest = kaplan_meier_length_weights(lengths, own)
kept = []
at = 0
for path, stats, owns in recorded:
survivors = []
for s, o in zip(stats, owns):
if o == 2 and weights[at] > 0.0:
survivors.append(dataclasses.replace(s, frame_weight=float(weights[at])))
at += 1
kept.append((path, survivors))
...
report["unassigned"] = rest if sum(own) else 0.0
report["beyond"] = rest * sum(own) / 2.0
```

この扱いは `fiber` 単位でだけ選べます。画像の中央値それ自体が、全長を見た範囲より
長い側にありうるためです。

### 3.4 推定で定まらない四分位数

推定が分布の一部を全長を見た最長のファイバーより長い側に置くとき、四分位数はその
部分がどこにあるかに依存しうります。GUI03 は四分位数ごとに、それがありうる範囲を
計算します。上端は置けなかった分を無限遠に、下端は全長を見た最長のファイバーの
すぐ先に置いたものです。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_kaplan_meier_bounds
upper_positions = (np.cumsum(sorted_weights) - 0.5 * sorted_weights) / total
...
for q, key in QUARTILE_KEYS:
if sorted_values.size == 0:
bounds[key] = (0.0, float("inf"))
continue
upper = (float(np.interp(q, upper_positions, sorted_values))
if q <= assigned / total else float("inf"))
lower = float(np.interp(q, positions, lengths))
bounds[key] = (min(lower, upper), upper)
```

四分位数を数値で報告するのは両端が一致する場合だけです。一致しなければ表には範囲
`[lower, upper]` を、`lower` より先のどこにでもありうるときは `> lower` を示します。
平均と標準偏差は報告しません。推定していない部分に依存するためです。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_kaplan_meier_summary
if sum(b for _l, b in estimates) <= 0.0:
return dict(_summary_stats(values, weights), bounds={})
bounds = _kaplan_meier_bounds(values, weights, estimates)
stats = {"mean": float("nan"), "std": float("nan"),
"std_definition": STD_WEIGHTED, "bounds": bounds}
for _q, key in QUARTILE_KEYS:
lower, upper = bounds[key]
stats[key] = (upper if np.isfinite(upper)
and upper - lower <= 1e-9 * max(1.0, abs(upper))
else float("nan"))
return stats
```

### 3.5 四分位数のリサンプリング区間

§3.4 の範囲が扱うのは、置けなかった分がどこにありうるかだけで、計測したファイバー
自体も標本です。そのため GUI03 は、各グループのファイバーを復元抽出し直し
（Efron (1979) のブートストラップ）、推定とその範囲を `KM_RESAMPLES` 回
計算し直して、四分位数ごとに、リサンプルにわたる下端の 2.5 パーセンタイルから上端の
97.5 パーセンタイルまでの区間をログに出します。乱数の種は固定なので、同じデータには
同じ区間を与えます。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::KM_RESAMPLES, KM_RESAMPLE_SEED
KM_RESAMPLES = 200
KM_RESAMPLE_SEED = 20261104
```

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_kaplan_meier_interval
for _resample in range(resamples):
values, weights, estimates = [], [], []
for lengths, own in samples:
pick = rng.integers(0, lengths.size, lengths.size)
drawn, drawn_own = lengths[pick], own[pick]
fiber_weights, rest = kaplan_meier_length_weights(drawn, drawn_own)
...
return {key: (float(np.percentile(lowers[key], 2.5)),
float(np.percentile(uppers[key], 97.5, method="higher")))
for _q, key in QUARTILE_KEYS}
```

## 4. グループの比較

グループが 2 つ以上あると、GUI03 はグループの全ペアを、2 つの順位検定と効果量で
比べます（`afm_nanofiber_analyzer.group_compare`）。順位に基づく検定を使うのは、
ファイバー形態の分布が右に裾を引いており、t 検定が仮定する正規性が成り立たない
ためです。

### 4.1 GUI03 が検定するとき

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::TESTABLE_UNITS
TESTABLE_UNITS = (UNIT_FIBER, UNIT_IMAGE)
```

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._run_comparison
comparisons = []
comparison_note = ""
if len(results) < 2:
...
elif unit not in TESTABLE_UNITS:
...
elif frame_weighted and unit == UNIT_FIBER:
...
else:
try:
comparisons = compare_groups(
[(r["name"], r["values"]) for r in results]
)
```

検定は、表と図が示すのとまったく同じ標本に対して、`fiber` と `image` の単位でだけ
行います。

- **`pixel` の標本は検定しません。** 同じファイバーの隣り合う画素は同じ対象の
  繰り返しであり、長いファイバーほど多く出すため、それらに対する p 値は、試料が
  違うかどうかではなく、画像をどれだけ細かくサンプリングしたかを測ってしまいます。
- **重み付きの `fiber` の標本は検定しません。** Mann-Whitney U 検定と
  Kolmogorov-Smirnov 検定は重みを受け付けないため、`fiber` 単位で `Miles-Lantuejoul`
  または `Kaplan-Meier` の長さは記述しますが検定しません。`image` 単位の
  `Miles-Lantuejoul` では、各画像の標本は重みのない 1 つの値（重み付き中央値。§1.3）
  であり、検定します。
- **`fiber` と `image` では、何を独立とみなすかが違います。** `fiber` 単位は、同じ
  画像のファイバーを独立と数えます。それらは試料上の 1 つの場所、1 つの探針、1 回の
  背景補正を共有しているにもかかわらずです。その p 値はファイバーの本数が増えると
  小さくなります。`image` 単位は画像ごとに 1 つの値を取るため、試料上の場所ごとの
  違いが比較に入ります。GUI03 は `fiber` 単位のとき、比較表の下でその旨を述べます
  （`_comparison_caveat`）。

### 4.2 2 つの検定とその統計量

標本数 $n_A$ と $n_B$ のグループ A と B のペアについて:

- **Mann-Whitney U 検定**（Mann and Whitney 1947）は
  $U = R_A - n_A(n_A+1)/2$ を使います。$R_A$ は、合併した標本での A の標本の順位の
  和です（同じ値はそれらの順位の平均を取ります）。両側の統計量は
  $|U - n_A n_B/2|$ です。一方のグループが他方より上にある傾向に反応します。
- **2 標本 Kolmogorov-Smirnov 検定**（Smirnov 1948）は、2 つの経験
  分布関数の差の最大値 $D = \max_x |F_A(x) - F_B(x)|$ を使います。中央値が同じで
  ばらつきが違う 2 群を含め、形の違いすべてに反応します。

p 値の計算法のうち最初の 2 つ（§4.3）では、どちらの統計量も整数の尺度
$2|U - n_A n_B/2|$ と $n_A n_B D$ で計算し、等しい統計量が等しく比較されるように
します。$D$ は、両方の分布関数が段を上がる、等しい値の連なりの終わりでだけ読みます。

```python
# source: afm_nanofiber_analyzer/group_compare.py::_split_statistics
rank2 = np.rint(2.0 * rankdata(pooled)).astype(np.int64)
u2 = rank2[members].sum(axis=1) - n_a * (n_a + 1)
u_stat = np.abs(u2 - n_a * n_b)

order = np.argsort(pooled, kind="stable")
ordered = pooled[order]
run_ends = np.flatnonzero(np.r_[ordered[1:] != ordered[:-1], True])
in_a = np.zeros((members.shape[0], pooled.size), dtype=bool)
np.put_along_axis(in_a, members, True, axis=1)
count_a = np.cumsum(in_a[:, order], axis=1)[:, run_ends]
count_b = (run_ends + 1) - count_a
d_stat = np.abs(count_a * n_b - count_b * n_a).max(axis=1)
return u_stat, d_stat
```

GUI03 は Mann-Whitney U 検定を主検定とします。比較表はその p 値を §4.4 の補正後の
値で示し、括弧内に補正前の値を添えます。KS の p 値は、形の違いを見る参考値として、
補正せずに示します。2 つのうち小さく出た方を読むと各ペアを 2 回検定したことになり、
§4.4 の補正はそれを扱えません。比較表の下の注記がその旨を述べます
（`_primary_test_note`）。

### 4.3 p 値の計算法

ペアを検定するのは、両方のグループが `MIN_SAMPLES_FOR_TEST` 以上の標本を持つとき
だけです。それより小さいペアは、p 値も効果量も持たずに一覧に載ります。そのうえで
ペアの p 値を、次の 3 通りのいずれかで計算します。

```python
# source: afm_nanofiber_analyzer/group_compare.py::MIN_SAMPLES_FOR_TEST, _EXACT_ARRANGEMENT_LIMIT, _SAMPLED_SPLITS, _SAMPLED_SEED, _SAMPLED_MAX_VALUES
MIN_SAMPLES_FOR_TEST = 3
_EXACT_ARRANGEMENT_LIMIT = 100_000
_SAMPLED_SPLITS = 20_000
_SAMPLED_SEED = 0
_SAMPLED_MAX_VALUES = 5_000
```

```python
# source: afm_nanofiber_analyzer/group_compare.py::_pair_pvalues
if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
return float("nan"), float("nan")
if comb(a.size + b.size, a.size) <= _EXACT_ARRANGEMENT_LIMIT:
return _exact_pvalues(a, b)
n_values = a.size + b.size
if (n_values <= _SAMPLED_MAX_VALUES
and np.unique(np.concatenate([a, b])).size < n_values):
return _sampled_pvalues(a, b)

from scipy.stats import ks_2samp, mannwhitneyu

try:
u_p = float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
...
try:
ks_p = float(ks_2samp(a, b).pvalue)
```

1. **全ての並べ方を数える。** 合併した値を大きさ $n_A$ と $n_B$ のグループに分ける
   方法が `_EXACT_ARRANGEMENT_LIMIT` 通り以下、すなわち $\binom{n_A+n_B}{n_A}$ が
   それ以下のとき、すべての分け方を作り、統計量が観測値と同じかそれ以上に極端な
   分け方の割合を p 値とします。これは観測された値を条件とする各統計量の並べ替え
   分布なので、同じ値があっても厳密です。9 対 9 のグループは 48,620 通りで数え上げ、
   10 対 10 は 184,756 通りで数え上げません。

   ```python
   # source: afm_nanofiber_analyzer/group_compare.py::_exact_pvalues
   n_a, n_b = a.size, b.size
   pooled = np.concatenate([a, b])
   members = np.fromiter(
   (i for split in combinations(range(pooled.size), n_a) for i in split),
   dtype=np.intp,
   ).reshape(-1, n_a)
   u_stat, d_stat = _split_statistics(pooled, members, n_a, n_b)
   return (float(np.mean(u_stat >= u_stat[0])),
   float(np.mean(d_stat >= d_stat[0])))
   ```

2. **無作為な分け方。** それより大きく、同じ値を含み、値が `_SAMPLED_MAX_VALUES`
   個以下のペアは、固定の種 `_SAMPLED_SEED` で引いた `_SAMPLED_SPLITS` 個の無作為な
   分け方で検定します。観測された分け方をその 1 つに数えるので、$N$ 個のうち
   同じかそれ以上に極端なものが $k$ 個なら p 値は $(1+k)/(1+N)$ であり、0 にも
   $1/(1+N)$ 未満にもなりません。

   ```python
   # source: afm_nanofiber_analyzer/group_compare.py::_sampled_pvalues
   rng = np.random.default_rng(_SAMPLED_SEED)
   u_count = d_count = 0
   for start in range(0, _SAMPLED_SPLITS, _SAMPLED_BATCH):
   size = min(_SAMPLED_BATCH, _SAMPLED_SPLITS - start)
   members = np.argpartition(
   rng.random((size, pooled.size)), n_a - 1, axis=1)[:, :n_a]
   u_stat, d_stat = _split_statistics(pooled, members, n_a, n_b)
   u_count += int(np.count_nonzero(u_stat >= observed_u[0]))
   d_count += int(np.count_nonzero(d_stat >= observed_d[0]))
   return ((1 + u_count) / (1 + _SAMPLED_SPLITS),
   (1 + d_count) / (1 + _SAMPLED_SPLITS))
   ```

3. **SciPy。** それ以外のペア、すなわち同じ値を含まないペアと、値が
   `_SAMPLED_MAX_VALUES` 個を超えるペアは、`scipy.stats.mannwhitneyu`（両側）と
   `scipy.stats.ks_2samp` で計算します。

最初の 2 つの経路を設けた理由は、コードの記録によれば、同じ値があると SciPy の
Mann-Whitney は正規近似に切り替わり、KS 検定は値に同じものが無いものとして扱うため
です。たとえば等しい 3 値と、別の等しい 3 値では、`scipy.stats.mannwhitneyu` は
p = 0.047 を返します。これは全ての並べ方を数えた 0.1 を下回り、0.1 は 3 対 3 の
グループが到達しうる最小の p 値です（§4.6）。

### 4.4 多くのペアの補正: Holm

$k$ 群を比べると $k(k-1)/2$ 組のペアができます。各 p 値を、検定ごとに別々に、その
実行の全ペアにわたって Holm (1979) の段階的手順で補正します。$m$ 個の
p 値を $p_{(1)} \le \dots \le p_{(m)}$ と並べると、補正後の値は

$$\tilde p_{(i)} = \min\left(1,\ \max_{j \le i} (m - j + 1)\, p_{(j)}\right)$$

であり、列が非減少に保たれるため、後の比較が前の比較より有意になることはありません。
検定できなかったペア（NaN）は $m$ に数えません。

```python
# source: afm_nanofiber_analyzer/group_compare.py::holm_adjusted
values = [float(p) for p in pvalues]
finite = [(i, p) for i, p in enumerate(values) if np.isfinite(p)]
adjusted = list(values)
if not finite:
return adjusted

finite.sort(key=lambda item: item[1])
count = len(finite)
running = 0.0
for rank, (index, p) in enumerate(finite):
running = max(running, (count - rank) * p)
adjusted[index] = min(1.0, running)
return adjusted
```

たとえば p 値 0.01、0.04、0.03 は、0.03、0.06、0.06 になります。補正が扱うのは 1 つの
計測量のペアです。複数の計測量を検定すると、さらに別の一群になります。GUI03 は計測量を
1 つずつ実行するためこれを補正できず、比較表の下の注記がその旨を述べます。

```python
# source: afm_nanofiber_analyzer/group_compare.py::compare_groups
u_adjusted = holm_adjusted([p["u_p"] for p in pairs])
ks_adjusted = holm_adjusted([p["ks_p"] for p in pairs])
```

### 4.5 効果量: Cliff's delta

p 値は標本数とともに小さくなり、それが検出する隔たりはごくわずかなことがあるため、
各ペアは Cliff's delta（Cliff 1993）も報告します。

$$\delta = P(a > b) - P(a < b)$$

これはグループ A の標本 $a$ 1 つと B の標本 $b$ 1 つのすべての組にわたるものです。
値は $[-1, 1]$ にあり、2 群が対称に重なるとき 0、一方の全値が他方の全値を上回るとき
$\pm 1$、A が B を上回る傾向のとき正です。GUI03 はこれを SciPy の Mann-Whitney 統計量
から計算します。この統計量は $a > b$ の組の数に同順位の半分を加えたものなので、
$n_A n_B$ 個の組を作らずに $\delta = 2U/(n_A n_B) - 1$ となります。

```python
# source: afm_nanofiber_analyzer/group_compare.py::cliffs_delta
statistic = mannwhitneyu(a, b, alternative="two-sided").statistic
return float(2.0 * statistic / (a.size * b.size) - 1.0)
```

隣の大きさのラベルは、コードが Romano et al. (2006) によるとする
しきい値を当てはめたものです。
<!-- TODO(review): しきい値 0.147 / 0.33 / 0.474 は、Romano et al. (2006) による
とする二次資料でしか確かめておらず、会議発表論文そのものでは確認していない。 -->

```python
# source: afm_nanofiber_analyzer/group_compare.py::MAGNITUDE_THRESHOLDS, MAGNITUDE_LARGE
MAGNITUDE_THRESHOLDS = (
(0.147, "negligible"),
(0.330, "small"),
(0.474, "medium"),
)
MAGNITUDE_LARGE = "large"
```

```python
# source: afm_nanofiber_analyzer/group_compare.py::delta_magnitude
magnitude = abs(float(delta))
for threshold, label in MAGNITUDE_THRESHOLDS:
if magnitude < threshold:
return label
return MAGNITUDE_LARGE
```

### 4.6 ペアが到達しうる最小の p 値

標本が少ないと、まったく重ならない 2 群でも小さい p 値に届きません。検定した各ペアは、
その標本数でどちらかの検定が返しうる最小の p 値を記録します。同じ値を含まない、分離した
2 標本に対して検定を実行して求めます。

```python
# source: afm_nanofiber_analyzer/group_compare.py::_min_attainable_p
def _min_attainable_p(n_a: int, n_b: int) -> float:
a = np.arange(n_a, dtype=float)
b = np.arange(n_a, n_a + n_b, dtype=float)
return min(_pair_pvalues(a, b))
```

並べ方を数える場合、分離した 2 つの並び（A が B より全て下、全て上）は同じだけ極端
なので、値は $2/\binom{n_A+n_B}{n_A}$ となります。3 画像対 3 画像で 0.1、4 対 4 で
0.029 です。この値が慣例の水準を下回らないとき、比較表の下の注記はそのペアを挙げます。
そこでの「有意差なし」は、グループが違うかどうかについて何も言っていないからです。
Holm 補正は p 値を上げるだけなので、そのようなペアは補正後も水準に届きません。

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::CONVENTIONAL_ALPHA
CONVENTIONAL_ALPHA = 0.05
```

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_attainable_p_note
limited = [
c for c in comparisons
if np.isfinite(c.min_attainable_p)
and c.min_attainable_p >= CONVENTIONAL_ALPHA
]
```

`CONVENTIONAL_ALPHA` はほかに何も決めません。比較表は p 値を示し、どのペアにも有意の
印を付けません。

### 4.7 GUI03 が報告するが補正しない違い

比べるバンドルの間の違いには、試料以外の理由で計測量を変えるものがあります。GUI03 は
バンドルをそのまま計測し、比較を実行し、その違いをログか比較表の下に述べます。それが
結果にとって何を意味するかは、ユーザーが判断できます。

- バンドルを解析した中心線（`_centerline_note`）
- 曲率では、またグループ内ではスケルトン画素の高さでも、サンプリング間隔
  （`App._log_pixel_size_spread`、`App._log_group_pixel_size_spread`）
- キンク密度では、バンドルのキンクのしきい値・サンプリング間隔・バンドル形式・
  画素ノイズ（`_kink_condition_report`）
- `include` または `exclude` での輪郭長では、走査範囲（`_scan_size_spread_note`）と、
  枠がグループの長さを異なる大きさで偏らせること（`_frame_bias_note`）

## 5. このページをコードと一致させ続ける仕組み

各コード片はそのシンボルを名乗り、`scripts/check_gui03_docs.py` がそれをコードと
1 行ずつ比べます。引用したシンボルはすべて、そのスクリプトの `WATCHED_SYMBOLS` に
並び、コメントと docstring を除いて `tests/gui03_doc_manifest.json` に指紋化されて
います。検査は pre-commit フック（`--staged`）、`tests/test_gui03_docs.py`、Claude Code
フック `.claude/hooks/doc_code_reminder.py` で走ります。引用したシンボルを変えたら、
両言語版でそれを引用する節を読み直して更新し、指紋を更新してください。

```text
.venv\Scripts\python.exe scripts\check_gui03_docs.py --update
```

## 参考文献

- Cliff, N. (1993). Dominance statistics: Ordinal analyses to answer ordinal
  questions. *Psychological Bulletin*, 114(3), 494–509.
  doi:10.1037/0033-2909.114.3.494
- Efron, B. (1979). Bootstrap methods: Another look at the jackknife. *The
  Annals of Statistics*, 7(1), 1–26. doi:10.1214/aos/1176344552
- Holm, S. (1979). A simple sequentially rejective multiple test procedure.
  *Scandinavian Journal of Statistics*, 6(2), 65–70.
- Hyndman, R. J., & Fan, Y. (1996). Sample quantiles in statistical packages.
  *The American Statistician*, 50(4), 361–365.
  doi:10.1080/00031305.1996.10473566
- Kaplan, E. L., & Meier, P. (1958). Nonparametric estimation from incomplete
  observations. *Journal of the American Statistical Association*, 53(282),
  457–481. doi:10.1080/01621459.1958.10501452
- Kish, L. (1965). *Survey Sampling*. Wiley.
- Mann, H. B., & Whitney, D. R. (1947). On a test of whether one of two random
  variables is stochastically larger than the other. *The Annals of
  Mathematical Statistics*, 18(1), 50–60. doi:10.1214/aoms/1177730491
- Miles, R. E. (1974). On the elimination of edge effects in planar sampling.
  In E. F. Harding & D. G. Kendall (Eds.), *Stochastic Geometry*
  (pp. 228–247). Wiley.
  <!-- TODO(review): 頁範囲は引用文献から取ったもので、227–247 や 229–247 と
  するものもある。原書で確かめる。 -->
- Romano, J., Kromrey, J. D., Coraggio, J., & Skowronek, J. (2006). Appropriate
  statistics for ordinal level data: Should we really be using t-test and
  Cohen's d for evaluating group differences on the NSSE and other surveys?
  Paper presented at the annual meeting of the Florida Association of
  Institutional Research, Cocoa Beach, Florida.
  <!-- TODO(review): この項目は引用文献に拠っており、論文そのものは参照していない。 -->
- Smirnov, N. (1948). Table for estimating the goodness of fit of empirical
  distributions. *The Annals of Mathematical Statistics*, 19(2), 279–281.
  doi:10.1214/aoms/1177730256
- Tukey, J. W. (1977). *Exploratory Data Analysis*. Addison-Wesley.
