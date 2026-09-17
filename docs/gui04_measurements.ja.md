# GUI04 のファイバー計測

このページは、GUI04（`guis/GUI04_Tracking_fiber.py`）が `.b2z` バンドルを開いた
あとに何を計算するのかを説明する。対象は、各ファイバーを描画し計測する中心線と、
ファイバー一覧・ファイバー詳細ウィンドウ・連結ダイアログに表示されるすべての数値
である。各手順を実行するコードを引用するので、図のキャプションに書いた値を、
それを生んだ計算と照らし合わせて確認できる。

バンドルを書き出す前処理 4 段階（背景補正・二値化・細線化・キンク検出）は
[解析アルゴリズム](algorithms.ja.md) で説明している。このページはその続きから
始まる。キンク規則そのものは同ページの §4.3〜§4.6 で説明しており、ここでは
その使われ方だけを扱う。

## コード片の読み方

各コードブロックの先頭には、出典を示すヘッダがある。

```text
# source: lib/measure.py::compute_fiber_stats
```

これは、その行が属するファイルと、関数・メソッド（`Class.method`）・モジュール
定数を表す。1 ファイルの複数の定数をカンマ区切りで並べることもある。`...` だけの
行は省略を表す。コード片ではコメント行と空行を省き、メソッド本体は字下げを外して
示す。コメント付きで読みたい場合は、指定されたシンボルを開けばよい。

これらのコード片が黙って古くなることはない。`scripts/check_gui04_docs.py` が、
各コード片をそれが名指すシンボルと 1 行ずつ照合する。さらに、引用した各シンボルを
コメントと docstring を除いて指紋化している。そのためどれかの計算内容が変わると、
このページを読み直して指紋を更新するまで検査が失敗する（§6）。

## 表記規則

| 量 | 単位 | 備考 |
|---|---|---|
| 中心線の座標 `Fiber.xtrack`、`Fiber.ytrack` | px、ファイバーの外接矩形基準 | 矩形の原点は解析配列上の `Fiber.data[0]`、`Fiber.data[1]`。座標は小数。 |
| スケルトントラックの座標 `Fiber.skeleton_xtrack`、`Fiber.skeleton_ytrack` | px、ファイバーの外接矩形基準 | 整数の画素座標。 |
| 中心線に沿った距離 `Fiber.horizon` | nm | 0 から始まる累積値。 |
| 高さ `Fiber.height` | nm | 背景補正後の高さで、基板が 0 nm。 |
| 見かけ幅 W | 内部では px、表では nm | §2.1 参照。 |
| 曲率 | rad/µm | §3.6 参照。 |
| キンク密度 | 1/µm | §3.9 参照。 |
| 連結の距離 | px | スケルトン画素の間で測る。§5.1 参照。 |

**中心線とスケルトントラック。** このページでは、繊維に沿った 2 種類の座標列を
次の名前で区別し、どちらを指すのかを常に名前で明示する。

- **スケルトントラック**：細線化画像（バンドルの `skeletonized`）で 1 本の繊維を
  なす画素を、端から端へ順に並べた整数座標列。`Fiber.skeleton_xtrack` /
  `Fiber.skeleton_ytrack` に入っており、`fiber.skeleton_track` で取り出す。
  繊維の識別に使い、描画にも計測にも使わない（§1.3）。
- **中心線**：スケルトントラックの各点を、高さ断面の半値中点へ移した小数座標列
  （§2）。`Fiber.xtrack` / `Fiber.ytrack` に入っており、描画とすべての計測は
  この上で行う。

形式 1.0 のバンドルでは中心線を置かず、`Fiber.xtrack` / `Fiber.ytrack` に
スケルトントラックそのものが入る（§1.2）。そのため形式 1.0 のバンドルでは、この
ページの「中心線」を「`Fiber.xtrack` / `Fiber.ytrack` に入ったスケルトン
トラック」と読み替える。計算方法が変わる箇所では、その違いを個別に書いている
（§2.7、§3.5）。

**画素サイズ。** このページの物理的な長さはすべて、`measure.measure_bundle` が
走査範囲から求めた画素サイズを使う。既定の走査範囲はバンドルに記録されたもの
（`spatial_calibration`）である。GUI04 は代わりに、スケール欄の X・Y 走査範囲を
渡す。Y が空欄なら X を使う。解析配列は生スキャンより各軸 1 画素小さいので
（[解析アルゴリズム](algorithms.ja.md) の「全体を通じた表記規則」参照）、割る数は
配列サイズに 1 を足したものになる。

```python
# source: lib/measure.py::measure_bundle
data, meta = _load_validated_arrays(
    bundle_path, TRACKING_BUNDLE_KEYS, optional=_TRACKING_OPTIONAL_KEYS,
)
height_px, width_px = data["calibrated"].shape
x_size_per_pixel = scale_um * 1000.0 / (width_px + 1)
y_size_per_pixel = scale_y_um * 1000.0 / (height_px + 1)
...
fragments = image.fibers_in_image_parallel(
    max_workers=max_workers,
    progress_cb=progress_cb,
)
...
return curate_fibers(
    image,
    fragments,
    exclude_anchors=exclude_anchors,
    plan=plan,
)
```

`curate_fibers` は、保存済みの除外を追跡済みの断片に適用し、残った断片に保存済み
の連結プランを適用する（§5）。返されるファイバーがファイバー一覧の各行になる。

## 1. バンドルからファイバーへ

### 1.1 追跡した成分 1 つが 1 本のファイバー

`FiberTrackingImage` は前処理の段を再実行しない。バンドルの `calibrated`・
`skeletonized`・`bp`・`ep`・`kp`・`ka` を読み、あれば `up` と `ke` も読む。
スケルトンを各分岐点で切断し、残った連結成分をそれぞれ 1 本のファイバーとする。
これはキンク検出と同じ整理である（[解析アルゴリズム](algorithms.ja.md) §4.1）。
各成分は `_build_fiber` に渡される。

### 1.2 ファイバーを中心線とスケルトントラックのどちらの上に組み立てるか

形式 1.1 のバンドルは半値中点線の上でキンクを判定しているので、GUI04 は中心線の
上にファイバーを組み立てる。それより古いバンドルはスケルトン画素の上で判定して
いるので、再解析されるまではスケルトントラックのまま扱う。この選択は
`bundle_schema.centerline_from_meta` がバンドルの形式バージョンから行う。その
ため、キンクと、それを描く座標列（中心線またはスケルトントラック）は常に同じ定義から
来る。

```python
# source: lib/fiber_tracking_image.py::_build_fiber
xtrack_prcimg, ytrack_prcimg = imp_tools.tracking(target_image)
fiber_image = cal[y: y + h, x: x + w].copy()
if centerline == HALF_MAX_CENTERLINE:
    placed = place_centerline(
        cal, xtrack_prcimg, ytrack_prcimg, branch_points,
    )
    xtrack = placed.x - x
    ytrack = placed.y - y
    horizon = polyline_distance(
        xtrack, ytrack, size_per_pixel, y_size_per_pixel,
    )
    height = placed.crest
    skeleton_xtrack = xtrack_prcimg - x
    skeleton_ytrack = ytrack_prcimg - y
    width_px = placed.width_px
    width_measured = placed.width_measured
    line_reliable = placed.reliable
else:
    xtrack = xtrack_prcimg - x
    ytrack = ytrack_prcimg - y
    horizon = imp_tools.convert_track_to_distance(
        xtrack, ytrack, size_per_pixel, y_size_per_pixel,
    )
    height = cal[ytrack_prcimg, xtrack_prcimg]
...
for i, (px, py) in enumerate(zip(xtrack_prcimg.tolist(), ytrack_prcimg.tolist())):
    if (px, py) in kink_set:
        kink_indices.append(i)
    if (px, py) in dp_set:
        decomposed_point_indices.append(i)
    if (px, py) in ep_set:
        ep_indices.append(i)
    if (px, py) in unjudged:
        unjudged_indices.append(i)
```

`imp_tools.tracking` は成分を一方の端からもう一方の端まで辿り、画素を順番に返す。
中心線はスケルトン画素 1 つにつきちょうど 1 点を持つので、添字 `i` は中心線と
スケルトントラックで同じ場所を指す。そのため、バンドルにスケルトン画素として保存された
キンク・端点・未判定の折れを、スケルトン座標で照合したうえで、中心線上の同じ添字に
描ける。

### 1.3 識別と幾何を分けて持つ

ファイバーは、添字の揃った中心線とスケルトントラックの両方を持つ。
`Fiber.xtrack` / `Fiber.ytrack` は描画し計測する中心線である。
`Fiber.skeleton_xtrack` / `Fiber.skeleton_ytrack` は中心線の元になった
スケルトントラックで、`fiber.skeleton_track` で取り出す。ファイバーを
**識別する**処理はすべてスケルトン画素を読む。除外と連結のアンカー、連結の探索
（§5.1）、分岐点と画像端の判定がそうである。スケルトンが変わるのは画像を再解析
したときだけである。一方、中心線はその推定方法が変わるたびに動くので、中心線で識別すると
保存済みのサイドカーが対応を失ってしまう。

## 2. 中心線

スケルトンは二値化マスクの medial axis である。マスク境界はしきい値の等高線
なので、背景の残差や近くの物体によって位置がずれる。さらに 8 連結の画素鎖が
階段状のずれを加える。半値中点線は、代わりに各スケルトン点を繊維自身の高さ断面の
上に置く。この定義を選んだ理由と、合成スキャンでの精度は
[解析アルゴリズム](algorithms.ja.md) §4.2 にある。この節ではコードを順に追う。

`centerline.place_centerline` は幅を測ってから中心線を置く。

```python
# source: lib/centerline.py::place_centerline
width, measured = measure_apparent_width(height, x, y, return_measured=True)
lx, ly, reliable, crest = _refine(height, x, y, width, branch_points)
return CenterlineResult(lx, ly, float(width), bool(measured), reliable, crest)
```

中心線を置くときの長さはすべて見かけ幅 W の倍数である。したがって、この手順は
どの画素サイズでも同じ意味を持つ。

```python
# source: lib/centerline.py::_WIDTH_SEARCH_PX, _WIDTH_STEP_PX, _WIDTH_TANGENT_HALF, FALLBACK_WIDTH_PX, _CREST_WINDOW_WIDTHS, _FRAME_SIGMA_WIDTHS, _CREST_REACH_WIDTHS, _HALF_MAX_REACH_WIDTHS, _MAX_SECTION_WIDTHS, _OFFSET_SMOOTH_WIDTHS, _JUNCTION_WIDTHS, _MIN_CREST_AMPLITUDE_FRAC
_WIDTH_SEARCH_PX = 12.0
_WIDTH_STEP_PX = 0.25
_WIDTH_TANGENT_HALF = 3
FALLBACK_WIDTH_PX = 8.0
_CREST_WINDOW_WIDTHS = 0.25
_FRAME_SIGMA_WIDTHS = 0.25
_CREST_REACH_WIDTHS = 0.75
_HALF_MAX_REACH_WIDTHS = 1.5
_MAX_SECTION_WIDTHS = 1.5
_OFFSET_SMOOTH_WIDTHS = 0.25
_JUNCTION_WIDTHS = 1.0
_MIN_CREST_AMPLITUDE_FRAC = 0.25
```

画素単位なのは最初の 3 つだけである。これらは幅のプロファイルをどれだけ細かく
標本化するかを決めるもので、繊維の性質ではない。

### 2.1 見かけ幅 W

`centerline.measure_apparent_width` は、繊維の半値全幅を**高さ**画像から読む。
二値化マスクは使わない。

```python
# source: lib/centerline.py::measure_apparent_width
tx, ty = _unit_tangents(x, y, _WIDTH_TANGENT_HALF)
nx, ny = -ty, tx
offsets = np.arange(-_WIDTH_SEARCH_PX, _WIDTH_SEARCH_PX + 1e-9, _WIDTH_STEP_PX)
profiles = _bilinear(
    np.asarray(height, dtype=np.float64),
    y[:, None] + ny[:, None] * offsets[None, :],
    x[:, None] + nx[:, None] * offsets[None, :],
)
peak = profiles.max(axis=1)
base = np.percentile(profiles, 10.0, axis=1)
level = base + 0.5 * (peak - base)
above = profiles >= level[:, None]
centre = offsets.size // 2
widths = np.empty(x.size, dtype=np.float64)
usable = np.zeros(x.size, dtype=bool)
for i in range(x.size):
    lo = centre
    while lo > 0 and above[i, lo - 1]:
        lo -= 1
    hi = centre
    while hi < offsets.size - 1 and above[i, hi + 1]:
        hi += 1
    widths[i] = offsets[hi] - offsets[lo]
    usable[i] = lo > 0 and hi < offsets.size - 1
if usable.sum() < max(1, x.size // 2):
    return (FALLBACK_WIDTH_PX, False) if return_measured else FALLBACK_WIDTH_PX
width = float(np.median(widths[usable]))
if not np.isfinite(width) or width < 2.0:
    return (FALLBACK_WIDTH_PX, False) if return_measured else FALLBACK_WIDTH_PX
return (width, True) if return_measured else width
```

手順は次のとおりである。

1. 各スケルトン点の法線を、スケルトントラック上の前後 ±3 点の中心差分から求める。その法線に
   沿って、±12 px の範囲の高さプロファイルを 0.25 px ごとに双線形補間で標本化する。
2. 各プロファイルは、自身の標本の 10 パーセンタイルを基準にする。そのため、背景に
   傾斜が残っていても、繊維はその場の基準に対して測られる。レベルは、その基準と
   プロファイルの最大値の中間である。
3. レベルを上回る区間を、スケルトン点から外側へ広げていく。プロファイルが最初に
   レベルを下回った所で止めるので、法線上のさらに先にある別の繊維が区間を広げる
   ことはない。探索範囲の端まで達した区間は、レベルまで下がらなかったということ
   なので使わない。
4. W は使える点での**中央値**である。幅は繊維の性質なので、1 本の繊維全体で 1 つの
   値を使う。

使える点が半数未満の場合、または中央値が 2 px 未満の場合は、`FALLBACK_WIDTH_PX`
（8 px）で代用する。代用したことは報告される。`CenterlineResult.width_measured`
が `False` になり、GUI04 はそのファイバーの `W (nm)` 欄を空欄にする（§3.10）。

### 2.2 枠：方向だけを与える平滑化コピー

`centerline._refine` はまず、スケルトントラックのコピーを $\sigma = W/4$（スケルトン
トラックの点数に換算）のガウスで平滑化する。両端は線形外挿で延長するので、まっすぐな端が内側へ
引き込まれることはない。この平滑化コピー（*枠*）が与えるのは、各点が動ける法線
方向と、横方向オフセットを測る基準だけである。点を平滑化位置へ動かすことは
決してない。そうすると本物のコーナーが丸まってしまう。

```python
# source: lib/centerline.py::_refine
width = float(width_px)
mean_step = max(float(np.hypot(np.diff(x), np.diff(y)).mean()), 1e-9)
sigma = _FRAME_SIGMA_WIDTHS * width / mean_step
fx = _smooth_extrapolated(x, sigma)
fy = _smooth_extrapolated(y, sigma)
tx = np.gradient(fx)
ty = np.gradient(fy)
norm = np.hypot(tx, ty)
norm[norm == 0.0] = 1.0
nx, ny = -ty / norm, tx / norm
reach = _CREST_REACH_WIDTHS * width
half_reach = _HALF_MAX_REACH_WIDTHS * width
s = np.arange(-(reach + half_reach), reach + half_reach + 1e-9, _WIDTH_STEP_PX)
ns = s.size
prof = _bilinear(img, fy[:, None] + ny[:, None] * s[None, :],
                 fx[:, None] + nx[:, None] * s[None, :])
```

`prof[i, :]` は点 $i$ の断面で、法線に沿って 0.25 px ごとに標本化してある。
範囲は枠から $\pm(0.75 + 1.5)\,W$ で、内訳は断面の最大値を探す 0.75 W と、その先で
半値交点を探す 1.5 W である。

### 2.3 最寄りの極大へ上る

各断面では、枠の点から坂を上って**最寄りの**極大へ向かう。射程内で最も高い点へは
向かわない。これにより、より明るい隣の繊維に中心線を奪われない。

```python
# source: lib/centerline.py::_refine
c = int(np.argmin(np.abs(s)))
dif = np.diff(prof, axis=1)
k = np.full(n, c)
go_right = dif[:, c] > 0
go_left = ~go_right & (dif[:, c - 1] < 0)
stop_right = dif[:, c:] <= 0
right_end = np.where(stop_right.any(1), stop_right.argmax(1), stop_right.shape[1]) + c
k = np.where(go_right, np.minimum(right_end, ns - 1), k)
stop_left = dif[:, :c][:, ::-1] >= 0
left_steps = np.where(stop_left.any(1), stop_left.argmax(1), c)
k = np.where(go_left, c - left_steps, k)
peak = prof[rows, k]
within_reach = np.abs(s[k]) < reach - 0.5 * _WIDTH_STEP_PX
```

`k[i]` はその極大の標本位置、`peak[i]` はその高さである。枠から 0.75 W 以上
離れた極大は別の物体のものである。その断面は `within_reach` を満たさず、中心線を置く
のには使わない。

### 2.4 半値中点

極大の両側それぞれで、1.5 W 以内の最小の標本を取る。基準はこの 2 つの最小値の
低い方で、レベルは基準とピークの中間である。各側の交点は、そのレベルを下回る
標本のうち極大に最も近いもので、線形補間によって標本間の位置まで求める。中心線の点は
2 つの交点の中点に置く。

```python
# source: lib/centerline.py::_refine
window = np.abs(s[None, :] - s[k][:, None]) <= half_reach
left = window & (col < k[:, None])
right = window & (col > k[:, None])
left_min = np.where(left, prof, np.inf).min(1)
right_min = np.where(right, prof, np.inf).min(1)
left_min = np.where(np.isfinite(left_min), left_min, peak)
right_min = np.where(np.isfinite(right_min), right_min, peak)
base = np.minimum(left_min, right_min)
amplitude = peak - base
level = base + 0.5 * amplitude
below = prof < level[:, None]
li = np.where(left & below, col, -1).max(1)
ri = np.where(right & below, col, ns).min(1)
resolved = within_reach & (li >= 0) & (ri < ns) & (amplitude > 0)
offset = s[k].astype(np.float64)
r = np.nonzero(resolved)[0]
if r.size:
    jl = li[r]
    pl0 = prof[r, jl]
    pl1 = prof[r, jl + 1]
    xl = s[jl] + (level[r] - pl0) / np.where(pl1 != pl0, pl1 - pl0, 1.0) * _WIDTH_STEP_PX
    jr = ri[r]
    pr0 = prof[r, jr - 1]
    pr1 = prof[r, jr]
    xr = s[jr - 1] + (pr0 - level[r]) / np.where(pr0 != pr1, pr0 - pr1, 1.0) * _WIDTH_STEP_PX
    offset[r] = 0.5 * (xl + xr)
    owns = (xl <= 0.0) & (xr >= 0.0)
    narrow = (xr - xl) <= _MAX_SECTION_WIDTHS * width
    resolved[r[~(owns & narrow)]] = False
```

したがって、位置を決められた点のオフセットは枠から法線方向に測って

$$
\text{offset}_i = \tfrac{1}{2}\,(x_{\text{L},i} + x_{\text{R},i})
$$

となる。これは平らな頂部ではなく、ノイズが交点を最も動かさない急な斜面から
読む値である。

中点を求めたあとでも、2 つの場合には断面を不採用にする。枠の点が半値区間の外に
ある場合（`owns`）は、その断面はスケルトントラックが載っている断面ではない。区間が 1.5 W
より広い場合（`narrow`）は、2 本の繊維が並んでいる。

### 2.5 信頼できる点と補間されるオフセット

点が**信頼できる**とされるのは、その断面がこの 1 本の繊維の位置を決められた
場合だけである。位置を決められた断面は、さらに次の 2 条件も満たす必要がある。
振幅がスケルトントラック上の決められた振幅の中央値の 1/4 以上であること、そしてどの分岐点
からも 1 W より離れていることである。

```python
# source: lib/centerline.py::_refine
typical = float(np.median(amplitude[resolved])) if resolved.any() else float(np.median(amplitude))
weight = (resolved & (amplitude >= _MIN_CREST_AMPLITUDE_FRAC * typical)).astype(np.float64)
if branch_points is not None:
    mask = np.asarray(branch_points)
    radius = _JUNCTION_WIDTHS * width
...
    weight[d2 < radius * radius] = 0.0
lam = (_OFFSET_SMOOTH_WIDTHS * width / mean_step) ** 2
lateral = np.clip(_whittaker_first_order(offset, weight, lam), -reach, reach)
reliable = weight > 0.0
```

次に、重み付きの一次 Whittaker 平滑化で、オフセットをスケルトントラックに沿ってつなぐ。
信頼できない点の重みは 0 である。

$$
\min_z \; \sum_i w_i\,(z_i - \text{offset}_i)^2 \;+\; \lambda \sum_i (z_{i+1} - z_i)^2,
\qquad \lambda = \left(\frac{W/4}{\overline{\Delta s}}\right)^2
$$

```python
# source: lib/centerline.py::_whittaker_first_order
n = target.size
if n == 1:
    return target.astype(np.float64).copy()
main = weight + 1e-6 + lam * np.concatenate([[1.0], np.full(n - 2, 2.0), [1.0]])
off = np.full(n - 1, -lam)
return _solve_tridiagonal(off, main, off, weight * target)
```

一次罰則は、信頼できない点が続く区間を線形に補間する。最後の信頼できる点より先
ではオフセットを一定に保つので、信頼できない端は漂流せず、隣の信頼できる部分の
オフセットを保つ。結果は ±0.75 W にクリップする。補間区間は直線なので、そこでは
キンクも曲率も見つからない。これを示すのが `reliable` 列である（§3.11）。

### 2.6 頂点高さ

中心線は半値中点にあり、非対称な断面では頂部の上ではなく脇に来る。中心線の位置で補間した
高さは低めに出てしまう。そこで、繊維の高さは断面の**頂点**とする。

```python
# source: lib/centerline.py::_refine
near = np.abs(s[None, :] - lateral[:, None]) <= _CREST_WINDOW_WIDTHS * width
crest_near = np.where(near, prof, -np.inf).max(1)
line_x = fx + nx * lateral
line_y = fy + ny * lateral
at_line = _bilinear(img, line_y, line_x)
crest_near = np.where(np.isfinite(crest_near), crest_near, at_line)
crest = np.maximum(np.where(reliable, peak, crest_near), at_line)
return line_x, line_y, reliable, crest.astype(np.float64)
```

- 信頼できる点は、その断面で上り着いた最大値 `peak` を取る。
- 補間された点は自身の断面を持たないので、中心線から法線方向に W/4 以内の最大値を取る。
- どちらの値も、必要なら中心線の位置そのもので補間した高さまで引き上げる。プロファイル
  は 0.25 px ごとの標本にすぎないので、こうして頂点高さが中心線の位置の高さを下回らない
  ようにしている。

`_build_fiber` はこれを `Fiber.height` として保存する（§1.2）。このページの高さの
数値はすべてこれを読む。

### 2.7 輪郭長

中心線では、繊維に沿った距離は折れ線の単純なユークリッド長である。各軸はそれぞれの
画素サイズで換算する。

```python
# source: lib/centerline.py::polyline_distance
x = np.asarray(xtrack, dtype=np.float64)
y = np.asarray(ytrack, dtype=np.float64)
x_step = float(pixel_step_size)
y_step = x_step if y_pixel_step_size is None else float(y_pixel_step_size)
out = np.zeros(x.size, dtype=np.float64)
if x.size > 1:
    steps = np.hypot(np.diff(x) * x_step, np.diff(y) * y_step)
    out[1:] = np.cumsum(steps)
return out
```

$$
s_j = \sum_{i=1}^{j} \sqrt{\bigl((x_i - x_{i-1})\,p_x\bigr)^2 + \bigl((y_i - y_{i-1})\,p_y\bigr)^2}
$$

この配列が `Fiber.horizon` で、ファイバーの長さはその末尾の値である。

```python
# source: lib/fiber.py::Fiber.length
@property
def length(self) -> float:
...
    return self.horizon[-1]
```

古いバンドルのスケルトントラックでは、代わりに
`imp_tools.convert_track_to_distance` を使う。その補正済みチェーンコード重みは、
8 連結画素鎖の長さの過大評価を取り除く。小数座標の中心線にはこの過大評価は無い。

## 3. ファイバー一覧

GUI04 のファイバー一覧は次の列を持つ。

```python
# source: guis/GUI04_Tracking_fiber.py::App._build_fiber_table
cols = ("#", "length (nm)", "median (nm)", "max (nm)", "p90 (nm)",
        "straightness", "curvature (rad/" + UNIT_MICROMETER + ")",
        "EP count", "Kink count",
        "kink density (1/" + UNIT_MICROMETER + ")",
        "unjudged", "W (nm)", "reliable")
```

`#`・`EP count`・`Kink count` 以外の列はすべて `lib/measure.py` が計算する。CSV
出力・GUI03・`cli.py measure` も同じ関数を呼ぶので、ここで確認した値はそれらが
報告する値と同じである。

| 列 | 出所 | 空欄になる場合 |
|---|---|---|
| `#` | 表示中の一覧での行位置 | — |
| `length (nm)` | `Fiber.length` | — |
| `median (nm)` | `FiberStats.height_median_nm` | — |
| `max (nm)` | `FiberStats.height_max_nm` | — |
| `p90 (nm)` | `FiberStats.height_p90_nm` | 高さ標本が無い |
| `straightness` | `measure.fiber_straightness` | 輪郭長が 0 |
| `curvature (rad/µm)` | `measure.fiber_mean_curvature` | ファイバーが 100 nm の窓より短い |
| `EP count` | `len(Fiber.ep_indices)` | — |
| `Kink count` | `len(Fiber.kink_indices)` | — |
| `kink density (1/µm)` | `measure.fiber_kink_density` | 何も判定していない |
| `unjudged` | `len(Fiber.unjudged_indices)` | — |
| `W (nm)` | `FiberStats.width_nm` | 幅を測定できなかった、または形式 1.0 のバンドル（スケルトントラック） |
| `reliable` | `FiberStats.line_reliable_fraction` | 形式 1.0 のバンドル（スケルトントラック） |

表は次のように埋める。

```python
# source: guis/GUI04_Tracking_fiber.py::App._populate_fiber_table
x_spp = self.current_image.size_per_pixel
y_spp = self.current_image.y_size_per_pixel
fresh = _table_values(
    compute_fiber_stats(fibers, x_spp, y_spp), fibers, x_spp, y_spp,
)
...
self.fiber_tree.insert("", "end", iid=str(i), values=(
    i,
    f"{f.length:.0f}",
    f"{med:.2f}",
    f"{mx:.2f}",
    blank_if_nan(p90, "{0:.2f}"),
    blank_if_nan(straight, "{0:.3f}"),
    blank_if_nan(curv, "{0:.2f}"),
    len(f.ep_indices),
    len(f.kink_indices),
    blank_if_nan(kink_dens, "{0:.2f}"),
    int(unjudged),
    blank_if_nan(width_nm if width_measured else float("nan"),
                 "{0:.1f}"),
    blank_if_nan(reliable, "{0:.2f}"),
))
```

```python
# source: guis/GUI04_Tracking_fiber.py::_table_values
return [
    (s.height_median_nm, s.height_max_nm, s.straightness,
     fiber_mean_curvature(
         f, x_spp, y_spp, window_nm=DEFAULT_CURVATURE_WINDOW_NM,
     ),
     fiber_kink_density(s),
     s.height_p90_nm, s.width_nm, s.width_measured,
     s.line_reliable_fraction, s.unjudged_count)
    for s, f in zip(stats, fibers)
]
```

フィルターが無効なら、解析ワーカーが計算した値を再利用する。有効なら同じ 2 つの
関数で計算し直す。どちらの場合も、各セルの値は `compute_fiber_stats` と
`_table_values` から来る。

### 3.1 `#`

現在表示している一覧での行の位置である。連結の有効・無効を切り替えたり高さ
フィルターを掛けたりすると、番号は振り直される。したがってこの番号は固定の識別子
ではない。除外と連結はこの番号ではなく、スケルトン画素として保存する（§1.3）。

### 3.2 `length (nm)`

`Fiber.length`、すなわちファイバーの中心線に沿った輪郭長（§2.7）を nm 単位に丸めた
ものである。連結したフィブリルでは、各隙間を埋める直線の橋渡しも含む（§5.2）。

### 3.3 どの高さ標本を数えるか

`Fiber.height` のすべての点が高さ統計に入るわけではない。
`measure.height_sample_mask` は 2 種類の標本を外す。

```python
# source: lib/measure.py::CUT_END_EXCLUSION_WIDTHS, MIN_HEIGHT_SAMPLES, HEIGHT_UPPER_PERCENTILE
CUT_END_EXCLUSION_WIDTHS = 1.0
MIN_HEIGHT_SAMPLES = 3
HEIGHT_UPPER_PERCENTILE = 90.0
```

```python
# source: lib/measure.py::height_sample_mask
n = len(fiber.height)
if n == 0:
    return np.zeros(0, dtype=bool)
measured = getattr(fiber, "height_measured", None)
measured = (np.ones(n, dtype=bool) if measured is None
            else np.asarray(measured, dtype=bool))
mask = measured.copy()
width = float(getattr(fiber, "width_px", float("nan")))
if np.isfinite(width) and width > 0.0 and n > 1:
    ends = set(int(i) for i in np.asarray(fiber.ep_indices).tolist())
    arc = polyline_distance(fiber.xtrack, fiber.ytrack, 1.0)
    zone = CUT_END_EXCLUSION_WIDTHS * width
    if 0 not in ends:
        mask &= ~(arc < zone)
    if n - 1 not in ends:
        mask &= ~(arc > arc[-1] - zone)
if mask.sum() < MIN_HEIGHT_SAMPLES:
    mask = measured
    if not mask.any():
        mask = np.ones(n, dtype=bool)
return mask
```

1. **橋渡しの標本。** 連結したフィブリルの橋渡し部の高さは連結処理が補間した値で
   （§5.2）、画像の測定値ではない。これらは `Fiber.height_measured` が `False` に
   なっている。
2. **切断端の最後の 1 幅。** 点が `ep_indices` に含まれない端は切断である。つまり
   スケルトンはそこで交差へ続いていた。`imp_tools.remove_bp` が消すのは分岐点の
   周りの 3×3 だけだが、相手の繊維の裾はその先さらに約 1 幅広がる。そのため、
   こうした端から 1 W 以内（中心線に沿った画素単位の弧長で測る）の標本は、一部が相手の
   繊維のものになっている。本物の繊維端の標本は残す。

残る標本が 3 未満になる場合は、短い断片でも高さを報告できるよう切断端の除外を
やめる。測定値が 1 つも残らない場合は全標本を使う。幅を持たないファイバー
（形式 1.0 のバンドルで、スケルトントラック上のもの）には切断端の除外を行わない。

### 3.4 `median (nm)`、`max (nm)`、`p90 (nm)`

```python
# source: lib/measure.py::compute_fiber_stats
for i, f in enumerate(fibers):
    samples = np.asarray(f.height, dtype=float)
    if samples.size:
        samples = samples[height_sample_mask(f)]
    med = float(np.median(samples)) if samples.size else 0.0
    mx = float(np.max(samples)) if samples.size else 0.0
    p90 = (float(np.percentile(samples, HEIGHT_UPPER_PERCENTILE))
           if samples.size else float("nan"))
```

マスクが残した頂点高さ（§2.6）の中央値・最大値・90 パーセンタイルである。
パーセンタイルには NumPy 既定の、順序統計量の間の線形補間を使う。最大値は極値
なので、ノイズの尖塔 1 つや汚染粒子 1 つで動く。`p90` は、1 つの標本に左右されずに
繊維の高い側を要約する。

### 3.5 `straightness`

```python
# source: lib/measure.py::fiber_straightness
length = float(fiber.length)
if not (length > 0.0):
    return float("nan")
if y_size_per_pixel is None:
    y_size_per_pixel = x_size_per_pixel
if getattr(fiber, "centerline", SKELETON_TRACK) == HALF_MAX_CENTERLINE:
    dx = (float(fiber.xtrack[-1]) - float(fiber.xtrack[0])) * x_size_per_pixel
    dy = (float(fiber.ytrack[-1]) - float(fiber.ytrack[0])) * y_size_per_pixel
    return float(np.hypot(dx, dy) / length)
x0, x1 = int(fiber.xtrack[0]), int(fiber.xtrack[-1])
y0, y1 = int(fiber.ytrack[0]), int(fiber.ytrack[-1])
steps = max(abs(x1 - x0), abs(y1 - y0))
if steps == 0:
    return 0.0
t = np.linspace(0.0, 1.0, steps + 1)
line_x = np.rint(x0 + t * (x1 - x0)).astype(int)
line_y = np.rint(y0 + t * (y1 - y0)).astype(int)
straight = float(imp_tools.convert_track_to_distance(
    line_x, line_y, x_size_per_pixel, y_size_per_pixel,
)[-1])
return float(straight / length)
```

中心線では、直線度は中心線の最初の点と最後の点のユークリッド距離を輪郭長で割った
ものである。

$$
\text{straightness} = \frac{\sqrt{(\Delta x\,p_x)^2 + (\Delta y\,p_y)^2}}{L}
$$

1.0 が直線で、巻き込んだファイバーほど 0 に近づく。まっすぐな合成ファイバーは
0.9994 になる。1 を下回るのは、中心線自身のわずかな横方向ノイズのためだけである。
端点は追跡した部分の端なので、交差で切断されたファイバーは、追跡した部分について
記述される。

古いバンドルのスケルトントラックでは、分子はユークリッド弦ではない。同じ 2 画素を
結ぶ離散化した直線を、輪郭と同じチェーンコード尺度で測った長さである。この尺度は
まっすぐな画素鎖をユークリッド弦より約 5 % 短く報告するが、2 つの長さを同じ方法で
測ることで、直線状のファイバーではこの偏りが打ち消される。

### 3.6 `curvature (rad/µm)`

```python
# source: lib/measure.py::DEFAULT_CURVATURE_WINDOW_NM
DEFAULT_CURVATURE_WINDOW_NM = 100.0
```

```python
# source: lib/measure.py::fiber_curvature_profile
if y_size_per_pixel is None:
    y_size_per_pixel = x_size_per_pixel
horizon = np.asarray(fiber.horizon, dtype=float)
if horizon.size < 3 or float(horizon[-1]) < window_nm:
    return np.empty(0, dtype=float)
xs = np.asarray(fiber.xtrack, dtype=float) * x_size_per_pixel
ys = np.asarray(fiber.ytrack, dtype=float) * y_size_per_pixel
half = window_nm / 2.0
before = np.searchsorted(horizon, horizon - half, side="left")
after = np.searchsorted(horizon, horizon + half, side="left")
valid = (after < horizon.size) & (after > before)
valid &= (horizon - horizon[np.clip(before, 0, horizon.size - 1)] >= half * 0.5)
if not valid.any():
    return np.empty(0, dtype=float)
i = np.nonzero(valid)[0]
j = before[i]
k = after[i]
angle_in = np.arctan2(ys[i] - ys[j], xs[i] - xs[j])
angle_out = np.arctan2(ys[k] - ys[i], xs[k] - xs[i])
turn = np.abs((angle_out - angle_in + np.pi) % (2.0 * np.pi) - np.pi)
arc = (horizon[k] - horizon[j]) / 2.0
good = arc > 0.0
return (turn[good] / arc[good]) * 1000.0
```

```python
# source: lib/measure.py::fiber_mean_curvature
profile = fiber_curvature_profile(
    fiber, x_size_per_pixel, y_size_per_pixel, window_nm=window_nm,
)
return float(np.mean(profile)) if profile.size else float("nan")
```

中心線の各点 $i$ について、弧長で半窓（50 nm）後ろの点 $j$ と、半窓前の点 $k$ を取る。
2 本の弦 $j \to i$ と $i \to k$ を引き、それらのなす符号なしの角を、両者が張る弧の
半分で割ったものが曲率である。

$$
\kappa_i = \frac{\lvert \operatorname{wrap}(\phi_{ik} - \phi_{ji}) \rvert}{(s_k - s_j)/2}
\times 1000 \quad [\text{rad/µm}]
$$

弧の半分で割るのは、各弦の方向がその弦自身の中点での接線方向に等しく、2 つの方向の
間隔が窓の半分しかないためである。弧全体で割ると、真の曲率の半分を報告してしまう。
列に表示するのは、ファイバー全体での $\kappa_i$ の平均である。

小数座標の中心線でも窓は必要である。数画素の範囲では、回転角は中心線自身の横方向
ノイズで決まってしまう。画素 2 nm で半径 80〜400 nm の合成円弧では、100 nm の窓で
$1/R$ の 2 % 以内に収まった。

点を使うのは、その**前方**に完全な半窓がある場合だけである（`after <
horizon.size`）。**後方**は半窓の半分（25 nm）あれば足りる。この判定は
`horizon[i] - horizon[j] >= half * 0.5` なので、先頭から 25〜50 nm の点は短い後方の
弦を使う。100 nm より短いファイバーは曲率を持たず、欄は 0 ではなく空欄になる。
完全な直線と読まれないようにするためである。

### 3.7 `EP count`

`len(Fiber.ep_indices)`。ファイバーの端のうち、バンドルの `ep` 配列にある
**スケルトン端点**の数である（§1.2）。分岐点での切断は端点ではない。したがって、
両端とも自由なファイバーは 2、片端で切断されたファイバーは 1、2 つの交差の間の
断片は 0 になる。連結したフィブリルでは、外側の各端は、元の断片がスケルトン端点で
終わっていた場合だけ数える（§5.2）。画像の縁にある端点も数える。繊維が走査範囲の
外へ続いている可能性があっても同じである。

### 3.8 `Kink count` と `unjudged`

`len(Fiber.kink_indices)` と `len(Fiber.unjudged_indices)`。追跡した断片では、
どちらもバンドルから読む。`kp` は判定したキンク、`up` は中心線の端から 1.5 W 以内で
測って判定しなかった折れを持つ。どちらもスケルトン画素でファイバーと照合する
（§1.2）。これらを生んだ規則は [解析アルゴリズム](algorithms.ja.md) §4.3〜§4.4 に
ある。

連結したフィブリルや高さ帯のサブファイバーは、バンドルに含まれない中心線である。GUI04
はこれらを、バンドルに記録された `kinkangle_deg` を使って
`KinkDetector.judge_line` で判定し直す。これにより、1 枚の画像に 2 つの規則の
キンクが混在することはない（§5.2）。未判定の折れは灰色の中空の円で描く。
`Kink count`・キンク密度・CSV のキンク角のどれにも数えない。

### 3.9 `kink density (1/µm)`

```python
# source: lib/kink_detector.py::END_MARGIN_WIDTHS
END_MARGIN_WIDTHS = 1.5
```

```python
# source: lib/measure.py::fiber_kink_density
length_um = float(stat.length_nm) / 1000.0
width_nm = float(getattr(stat, "width_nm", float("nan")))
if np.isfinite(width_nm) and width_nm > 0.0:
    length_um -= 2.0 * END_MARGIN_WIDTHS * width_nm / 1000.0
if length_um <= 0.0:
    return float("nan")
return float(stat.kink_count) / length_um
```

$$
\text{kink density} = \frac{N_\text{kink}}{(L - 2 \times 1.5\,W)/1000}
$$

分母は**判定した**長さである。キンク規則は両端から 1.5 W 以内の折れを判定しない
ので、輪郭全体で割ると密度は低めに偏る。その偏りは、短い断片の多い密な試料ほど
大きい。3 W より短いファイバーは何も判定していないので空欄になる。判定した長さの
上にキンクが無いファイバーは、実在する 0.00 である。ここで使う W は
`FiberStats.width_nm` で、代替幅であってもそのまま使う（`W (nm)` 列では空欄になる
値である）。幅を持たないファイバー（形式 1.0 のバンドルで、スケルトントラック上のもの）は
輪郭全体で割る。

### 3.10 `W (nm)`

```python
# source: lib/measure.py::compute_fiber_stats
width_px = float(getattr(f, "width_px", float("nan")))
width_nm = (
    width_px * x_size_per_pixel
    if x_size_per_pixel is not None and np.isfinite(width_px)
    else float("nan")
)
```

§2.1 の見かけ幅 W を、**X** の画素サイズで nm に換算したものである。W は繊維の
向きによらず法線方向に画素単位で測るので、X と Y の画素サイズが異なる走査では、
正確なのは Y 方向に走る繊維の場合だけである。代替幅を代用した場合
（`Fiber.width_measured` が `False`）は空欄になり、読み込みログにその本数が出る。
W はそのファイバーのキンクを判定した尺度であり、探針による広がりを含む。繊維の
物理的な直径ではない。

### 3.11 `reliable`

```python
# source: lib/measure.py::compute_fiber_stats
reliable = getattr(f, "line_reliable", None)
reliable_fraction = (
    float("nan") if reliable is None or len(reliable) == 0
    else float(np.mean(np.asarray(reliable, dtype=bool)))
)
```

中心線の点のうち、補間ではなくこのファイバー自身の断面で位置を測った点（§2.5）の割合で
ある。値が低いほど中心線の多くが直線補間で、そこではキンクも曲率も見つからない。連結
したフィブリルでは、橋渡しの点を信頼できない点として数える（§5.2）。

## 4. ファイバー詳細ウィンドウ

### 4.1 ファイバー画像

```python
# source: guis/GUI04_Tracking_fiber.py::FiberDetailWindow._redraw_fiber_image
x_scale, y_scale, unit_label = app._get_extent_scale_xy_and_unit()
if app.current_image is not None:
    full_h, full_w = app.current_image.calibrated_image.shape[:2]
    x_spp = x_scale / full_w
    y_spp = y_scale / full_h
...
if app.show_fiber_track_var.get() and len(fiber.xtrack) > 0:
    ax.plot((fiber.xtrack + off_x + 0.5) * x_spp,
            (fiber.ytrack + off_y + 0.5) * y_spp,
            color="lime", lw=1.0, alpha=0.75, zorder=4)
if app.show_fiber_kink_var.get() and len(fiber.kink_indices) > 0:
    kx = (fiber.xtrack[fiber.kink_indices] + off_x + 0.5) * x_spp
    ky = (fiber.ytrack[fiber.kink_indices] + off_y + 0.5) * y_spp
    ax.scatter(kx, ky, c="cyan", s=20, zorder=5)
unjudged = getattr(fiber, "unjudged_indices", None)
if app.show_fiber_kink_var.get() and unjudged is not None and len(unjudged) > 0:
    ux = (fiber.xtrack[unjudged] + off_x + 0.5) * x_spp
    uy = (fiber.ytrack[unjudged] + off_y + 0.5) * y_spp
    ax.scatter(ux, uy, s=20, facecolors="none", edgecolors="0.6",
               linewidths=1.0, zorder=5)
```

緑色で描かれるのは中心線（`Fiber.xtrack` / `Fiber.ytrack`）で、一覧のすべての
数値はこの中心線に沿って測っている。シアンの点はキンク、灰色の中空の円は未判定の折れで、どちらも中心線上の
添字の位置に描く。0.5 のずれは各座標を画素の中心へ置くためのもので、これにより中心線が
稜線の上に載る。

このビューは、表示範囲を配列サイズで割って軸を換算する（`x_scale / full_w`）。
一方、計測用の画素サイズは配列サイズに 1 を足した数で割る（「表記規則」参照）。
そのため、描画される軸と計測される長さは、走査幅にして 1 画素分だけ異なる。

### 4.2 高さプロファイル

```python
# source: guis/GUI04_Tracking_fiber.py::FiberDetailWindow._redraw_profile
horizon = np.asarray(fiber.horizon, dtype=float)
height = np.asarray(fiber.height, dtype=float)
used = height_sample_mask(fiber)
if used.all():
    ax.plot(horizon, height, color="dimgray", lw=1.5)
else:
    grown = used | np.roll(used, 1) | np.roll(used, -1)
    ax.plot(horizon, np.where(grown, height, np.nan),
            color="dimgray", lw=1.5)
    ax.plot(horizon, np.where(~used, height, np.nan),
            color="silver", lw=1.2, linestyle="--")
if app.show_medmax_var.get():
    med = float(np.median(height[used]))
    mx  = float(np.max(height[used]))
...
if app.show_kink_var.get() and len(fiber.kink_indices) > 0:
    for i, ki in enumerate(fiber.kink_indices):
        if ki < len(fiber.horizon):
            ax.axvline(x=fiber.horizon[ki], color="cyan", linestyle="--", lw=1.0,
                       label="Kink" if i == 0 else None)
```

プロファイルは `Fiber.height`（頂点高さ、§2.6）を `Fiber.horizon`（§2.7）に対して
描く。高さ統計が使う標本は実線で描く。`height_sample_mask` が外す標本（§3.3）は
薄い破線で描く。中央値と最大値の補助線は `median (nm)`・`max (nm)` と同じマスクから
計算するので、プロットと表は常に一致する。シアンの縦線は、中心線に沿ったキンクの位置を
示す。

## 5. 連結したフィブリル

GUI01 はスケルトンを交差と分岐のたびに切断するので、1 本の物理的なフィブリルは
複数の断片として GUI04 に届く。「自動連結」を押すと、どの断片が 1 本のフィブリルを
なすかを決める探索が走る。連結ダイアログは 1 本のファイバーの連結候補を並べ、
連結を手で選べるようにする。どちらの連結も断片の連鎖として保存され、計測のときに
組み立て直される。

### 5.1 候補の値

```python
# source: lib/fiber_connector.py::ConnectParams
clusters_range: float = 20.0
angle_threshold: float = 110.0
lookback_length: int = 15
num_avg_points: int = 5
height_diff_ratio: float = 1.0
trim_points: int = 5
```

探索と候補一覧は**スケルトン画素**（§1.3）を `(row, col)` の順で読む。どの断片が
互いに続いているかはトポロジーの問題であり、しきい値もスケルトンの上で調整した
ためである。断片の各端 $B$ について、振り返り点 $A$ は端から
スケルトントラック上で `lookback_length` − 1 = 14 点だけ内側にある。15 点より短い断片では、
断片のもう一方の端になる。

```python
# source: lib/fiber_connector.py::_fragment_end_geometry
sx, sy = skeleton_track(frag)
xs = sx + frag.data[0]
ys = sy + frag.data[1]
step = min(lookback_length, len(xs))
ends[i, 0] = (ys[0], xs[0])
backs[i, 0] = (ys[step - 1], xs[step - 1])
ends[i, 1] = (ys[-1], xs[-1])
backs[i, 1] = (ys[-step], xs[-step])
```

高さゲートで使う各断片の高さは、スケルトン画素上の補正済み画像の中央値である。
§2.6 の頂点高さではない。

```python
# source: lib/fiber_connector.py::_fragment_median_heights
medians[i] = float(np.median(calibrated[ys, xs]))
```

ダイアログは `clusters_range` の 2 倍（既定 40 px）以内を探す。

```python
# source: lib/fiber_connector.py::MANUAL_RANGE_FACTOR
MANUAL_RANGE_FACTOR = 2.0
```

```python
# source: lib/fiber_connector.py::_manual_reach
if radius is None:
    return float(params.clusters_range * MANUAL_RANGE_FACTOR)
return float(radius)
```

その半径内にある他のファイバーの各端 $C$（振り返り点 $D$）について、ダイアログは
次の値を報告する。

```python
# source: lib/fiber_connector.py::_candidates_for
dist = float(np.hypot(B[0] - C[0], B[1] - C[1]))
if dist > reach:
    continue
angle_abd = angle_between_three_points(A, B, D)
angle_acd = angle_between_three_points(A, C, D)
low = min(medians[index], medians[j])
ratio = (
    abs(medians[index] - medians[j]) / low if low > 0 else 0.0
)
auto = (
    dist <= params.clusters_range
    and angle_abd > params.angle_threshold
    and angle_acd > params.angle_threshold
    and ratio <= params.height_diff_ratio
)
out.append({
    "index": j,
    "self_end": e,
    "other_end": f,
    "distance": dist,
    "angle": float(min(angle_abd, angle_acd)),
    "height_ratio": float(ratio),
    "auto": bool(auto),
})
```

```python
# source: lib/fiber_connector.py::angle_between_three_points
ba = np.array(A) - np.array(B)
bd = np.array(D) - np.array(B)
denom = np.linalg.norm(ba) * np.linalg.norm(bd)
if denom == 0:
    return 0.0
cosine_angle = np.dot(ba, bd) / denom
return float(np.degrees(np.arccos(np.clip(cosine_angle, -1.0, 1.0))))
```

| ダイアログの列 | 値 |
|---|---|
| distance (px) | 画素添字での $\lVert B - C \rVert$。画素サイズでは換算しない。 |
| angle (degree) | $\min(\angle ABD,\ \angle ACD)$。一直線に続く 2 断片では約 180°、U ターンでは約 0° になる。 |
| height diff | 2 つの高さ中央値について $\lvert m_1 - m_2 \rvert / \min(m_1, m_2)$。低い方の中央値が正でなければ 0。 |
| 自動 | 4 つのゲート（距離 ≤ `clusters_range`、2 つの角度がともに > `angle_threshold`、高さ差 ≤ `height_diff_ratio`）をすべて満たすかどうか。 |

ゲートは**報告するだけで適用しない**。そのため、角度ゲートが退ける続きも手で
選べる。候補はすべてのゲートを満たすものを先に、次に距離の順に並べる。

```python
# source: lib/fiber_connector.py::connection_candidates
ends, backs = _fragment_end_geometry(fibers, params.lookback_length)
medians = _fragment_median_heights(image.calibrated_image, fibers)
reach = _manual_reach(params, radius)
out = _candidates_for(index, ends, backs, medians, params, reach)
out.sort(key=lambda c: (not c["auto"], c["distance"]))
return out
```

### 5.2 連鎖からフィブリルを組み立てる

連鎖は断片の順序付きリストで、各断片には反転するかどうかのフラグが付いている。
`_build_chain_fiber` は断片を端と端でつなぐ。

```python
# source: lib/fiber_connector.py::_build_chain_fiber
long_enough = len(fh) > trim + n_avg
head_trim = trim if (k > 0 and long_enough) else 0
tail_trim = trim if (k < last and long_enough) else 0
...
if xs:
    b_y, b_x = ys[-1], xs[-1]
    c_y, c_x = fy[0], fx[0]
    tail_avg = float(np.mean(hs[-min(n_avg, len(hs)):]))
    head_avg = float(np.mean(fh[:min(n_avg, len(fh))]))
    num_points = max(abs(b_y - c_y), abs(b_x - c_x))
    if num_points > 1:
        bridge_y = np.linspace(b_y, c_y, num=num_points).round().astype(int).tolist()[1:-1]
        bridge_x = np.linspace(b_x, c_x, num=num_points).round().astype(int).tolist()[1:-1]
        ys.extend(bridge_y)
        xs.extend(bridge_x)
        if on_centerline:
            lys.extend(np.linspace(lys[-1], fly[0], num=num_points).tolist()[1:-1])
            lxs.extend(np.linspace(lxs[-1], flx[0], num=num_points).tolist()[1:-1])
        else:
            lys.extend(bridge_y)
            lxs.extend(bridge_x)
        bridge_h = np.linspace(tail_avg, head_avg, num=num_points).tolist()[1:-1]
        hs.extend(bridge_h)
        rel.extend([False] * len(bridge_h))
        meas.extend([False] * len(bridge_h))
```

1. **切り落とし。** 接合する各端から `trim_points` = 5 点を切り落とし、断片が
   切断された交差のノイズを除く。切り落とすのは、断片が `trim_points` +
   `num_avg_points` より長い場合だけである。両側の切り落としで内側の断片が
   すべて消えてしまう場合は、まず末尾側の切り落としをやめ、それでも足りなければ
   先頭側もやめる。
2. **橋渡し。** 切り落とした 2 つの端の隙間を、直線上の
   $\max(\lvert\Delta\text{row}\rvert, \lvert\Delta\text{col}\rvert) - 2$ 点で
   埋める。これはスケルトントラックと中心線の両方で同時に行い、両者の添字を揃えた
   ままにする。各断片は表示されていた中心線をそのまま保ち、連結によって中心線は
   動かない。
3. **橋渡しの高さ。** 隙間の手前の最後の `num_avg_points` = 5 個の高さの平均から、
   隙間の先の最初の 5 個の平均まで、線形に変化させる。橋渡しの点は、信頼できる点
   とも測定値とも扱わない。そのため `reliable` の割合を下げ、高さ統計からは外れる
   （§3.3）が、`length (nm)` には含まれる。

つないだ中心線は、次に `Fiber` になる。

```python
# source: lib/fiber_connector.py::_rebuild_connected_fiber
if kind == HALF_MAX_CENTERLINE:
    horizon = polyline_distance(
        xtrack, ytrack, size_per_pixel, y_size_per_pixel,
    )
...
if kind == HALF_MAX_CENTERLINE:
    width, width_measured = measure_apparent_width(
        image.calibrated_image, pix_x, pix_y, return_measured=True,
    )
    judged = detector.judge_line(line_x, line_y, width)
    kink_indices, kink_angles = judged.kink_indices, judged.kink_angles
    kink_excess, unjudged_indices = judged.kink_excess, judged.unjudged_indices
...
ep_indices = np.array([
    i for i, real in zip((0, len(line_x) - 1), end_is_real) if real
], dtype=int)
```

- フィブリルの長さは、つないだ中心線の折れ線長である（§2.7）。
- W は、つないだスケルトン画素（橋渡しを含む）の上で測り直す（§2.1）。
- キンクと未判定の折れは、つないだ中心線の上でその W を使い、バンドル自身の
  `kinkangle_deg` で判定し直す。断片の切断端のそばにあった折れは、もう端のそばに
  ないので、判定されるようになる。
- 端点は最初と最後の点で、それぞれ外側の断片がスケルトン端点で終わっていた場合
  だけ数える（§3.7）。

### 5.3 高さフィルター

GUI04 の高さフィルターは連結のあとに走る。各ファイバーを、`Fiber.height` が指定
した帯に入る連続区間ごとに切り出し（橋渡しの高さも含む）、各区間を
`_rebuild_connected_fiber` で組み立て直す。

```python
# source: lib/fiber_connector.py::filter_fibers_by_height
h = np.asarray(fib.height)
lower_cond = (h >= lower_height) if include_lower_limit else (h > lower_height)
upper_cond = (h <= upper_height) if include_upper_limit else (h < upper_height)
in_band = lower_cond & upper_cond
if not in_band.any():
    continue
...
for start, stop in _contiguous_runs(in_band):
    if stop - start < 2:
        continue
```

サブファイバーは親の中心線の一部である。その上で W を測り直し、キンクも判定し直すので、
`Kink count`・`unjudged`・`W (nm)`・キンク密度は親と異なることがある。サブ
ファイバーの端が本物の端なのは、それが親自身の本物の端である場合だけである。
フィルターの切断で生じた端は切断であり、高さ統計でもそのように扱う（§3.3）。

## 6. このページを最新に保つ

このページはコードを引用している。引用したコードが変わったら、ページを読み直す
必要がある。そうした変更は、次の 3 つの仕組みが捕らえる。

- `scripts/check_gui04_docs.py` は引用するシンボルの一覧（`WATCHED_SYMBOLS`）を
  持ち、すべての検査を実行する。検査内容は、各コード片がシンボルと一致すること、
  監視シンボルがすべて両言語版で引用されていること、両言語版の見出し構造が同じで
  コード片も同一であること、ファイバー一覧の各列に、その列名を見出しに含む §3 の
  小節があること、本文が中心線とスケルトントラックを常に名前で書き分けて
  いること、各シンボルの
  指紋が `tests/gui04_doc_manifest.json` と一致すること、である。
- `.githooks/pre-commit` はこれをステージ済みの内容に対して実行し、指摘があれば
  コミットを止める。指紋だけを更新して、このページのどちらの言語版にも触れない
  コミットも止める。`tests/test_gui04_docs.py` は同じ検査を CI で実行し、そこでは
  省略できない。
- Claude Code フック `.claude/hooks/doc_code_reminder.py` は、AI エージェントが
  監視対象のファイルを編集した直後に走る。その編集で引用中のシンボルの計算内容が
  変わった場合、どの節を更新すべきかをエージェントに伝える。

変更したら、`docs/gui04_measurements.md` と `docs/gui04_measurements.ja.md` の
両方で該当する節とコード片を更新し、指紋を更新する。

```text
.venv\Scripts\python.exe scripts\check_gui04_docs.py --update
```

GUI04 のファイバー一覧に列を追加したら、両言語版の §3 に、その列名を
バッククォートで見出しに含む小節（例：``### 3.12 `new column` ``）を設けて解説する。
概要表に名前を加えるだけでは検査を通らない。

新しいシンボルを引用するときは、先に `WATCHED_SYMBOLS` へ追加する。監視していない
シンボルの引用は検査が拒否するので、引用したコードは常に守られる。
