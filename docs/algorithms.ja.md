# 解析アルゴリズム

このページは、前処理 4 段階が実際に何をしているのか、そして各手順がソースの
どこにあるのかを説明する。想定読者は、図のキャプションに書く数値を自分で
説明できる必要がある人である。すなわち、ソフトウェアが利用者に代わって
どの判断を下したのか、どんな根拠に基づくのか、そしてどのパラメータが
その判断を変えるのかを扱う。

API リファレンスは各関数の契約を記述する。このページは、それらをつなぐ
推論を記述する。

## コード参照の読み方

コードは**シンボル名**で参照し、行番号では参照しない。行番号は無関係な編集
1 回で陳腐化するためである。`Segmenter._binaryzation` という参照は
`lib/segmenter.py` 内の同名メソッドを指し、`bg_calibrator.BG_METHOD_NAMES`
はモジュールレベル定数を指す。このページに登場するすべてのシンボルは
`tests/test_algorithm_docs.py` がテスト実行のたびにソースと照合するため、
リネームや削除があればビルドが失敗し、この記述が黙って誤りになることはない。

各手順は、**それを実行するコードとともに**示す。各コードブロックの先頭には、
出典を示すヘッダがある。

```text
# source: lib/segmenter.py::Segmenter._binaryzation
```

これは、そのコードが属するファイルと、関数・メソッド（`Class.method`）・
モジュール定数を表す。1 ファイルの複数のシンボルをカンマ区切りで並べることも
ある。`...` だけの行は省略を表し、コメント・空行・メソッドの字下げは省いて
いる。各コード片は、名指したシンボルと 1 行ずつ照合される
（`scripts/doc_excerpts.py`。`tests/test_algorithm_docs.py` と pre-commit
フックが実行する）。さらに英語版と日本語版は同一のコードを引用しなければ
ならない。そのため、コード片がソフトウェアの実際の処理と黙って食い違うことは
ない。

同じテストは逆方向も守る。コメントと docstring を除いたアルゴリズムモジュール
——4 つの段と、キンクを判定する線を置く `lib/centerline.py`——をハッシュ化して
いるため、コードの計算内容が変わればこのページを見直すまでテストが通らない。ドキュメントが記述対象のコードから静かに乖離
することはない。

## 全体を通じた表記規則

| 量 | 単位 | 備考 |
|---|---|---|
| 高さ | ナノメートル (nm) | ローダが nm へ変換する。以下の高さしきい値はすべて**背景補正後**の画像における絶対 nm 値であり、基板が 0 nm に位置する前提である。 |
| 面内距離 | 各段では画素 (px)、結果では µm | 各段は意図的に画素基準である。画素サイズは計測時にのみ関与する。 |
| 角度 | 内部ではラジアン、パラメータファイルでは度 | `pipeline.build_stages` が `KinkDetector` 構築時に `kinkangle_deg` をラジアンへ変換する。 |
| 配列添字 | `image[row, column]` すなわち `[y, x]` | いくつかのヘルパーは `np.where` の出力を返し、最初の配列が行添字になる。 |

**1 画素の切り詰め。** 背景補正は隣接画素間の 1 次差分の上に構築されている
ため、出力は入力より各軸 1 画素小さい。`BGCalibrator._bg_calibrate` は
`original[1:, 1:] - bg_sm` を返す。以降のすべての段はこの切り詰め済み配列を
扱う。したがって解析結果の画素 $(r, c)$ にある特徴は、生スキャンの画素
$(r+1, c+1)$ に対応する。

**パラメータ。** 以下に出てくる利用者設定値はすべて `pipeline.ProcParams`
のフィールドであり、各バンドルの隣に `<input_stem>_param.json` として保存
される。このファイルが、画像がどう解析されたかの完全な記録である。「既定値」
と記した値は `ProcParams` の既定値であり、GUI と CLI の出発点となるもので
ある。ステージクラスのコンストラクタ既定値とは一部異なり、そちらは
スクリプトからクラスを直接構築した場合にのみ効く。

## パイプライン全景

```text
生の AFM テキスト / CSV  ->  afm_io.load_afm_text()      \
Gwyddion .gwy            ->  gwy_io.load_gwy_image()     /  -> 高さ配列 (nm)
                                                             |
                             ProcessedImage.original_image  <-+
                                     |
   1. BGCalibrator   ->  calibrated_image   (nm、基板が 0)
   2. Segmenter      ->  binarized_image    (bool の繊維マスク)
   3. Skeletonizer   ->  skeleton_image     (1 px 幅の中心線) + ep / bp
   4. KinkDetector   ->  スケルトン成分ごとのキンク点と角度
                         （その半値中点線上で判定。§4.2）
                                     |
                             .b2z バンドル + _param.json
```

`pipeline.process_file` がまさにこの順序を実行し、GUI01 と `cli.py process`
の両方がこれを呼ぶため、2 つの入口が乖離することはない。ステージオブジェクト
は `pipeline.build_stages` が一度だけ構築する。

各段は前段が書いたものを読み、無ければ段の境界で明示的に失敗する。
`Segmenter.__call__` は `calibrated_image` が `None` なら OpenCV の内部で
失敗するのではなく、その場で例外を送出する。

---

## 1. 背景補正

**コード:** `lib/bg_calibrator.py` — `BGCalibrator.__call__` が
`_call_trendfill` / `_call_tophat` / `_call_spline1d` へ振り分ける。
**読む:** `original_image`。**書く:** `calibrated_image`。

`BGCalibrator.__call__` は振り分けるだけである。

```python
# source: lib/bg_calibrator.py::BGCalibrator.__call__
if self.bg_method == 'tophat':
    self._call_tophat(image)
elif self.bg_method == 'spline1d':
    self._call_spline1d(image)
else:
    self._call_trendfill(image)
```

### 1.1 解こうとしている問題

生の AFM スキャンは、平坦な面の上に載った試料の高さマップではない。試料の
傾きとスキャナの皿状歪みを伴っており、本プロジェクトの同梱スキャンでは
それらが信号を圧倒する。最小二乗平面は**1 画素あたり 0.23〜0.34 nm** 下降
するため、繊維 1 本の幅を横切る間に背景が 7〜9 nm 落ちる一方、繊維自身の
高さは約 10 nm しかない。同梱の Bruker スキャンでは、最適平面を除去した後
でも**32 nm のうねり**が残る。

ここから 2 つの帰結が導かれ、それがこの段全体の設計を決めている。

1. 後段のしきい値はすべて**nm の絶対高さ**である。基板が全域で 0 nm へ
   揃えられて初めて意味を持つ。
2. この傾斜を再現できない背景推定は、*明らかにしようとしている信号と同程度
   の大きさの誤差*を残す。

### 1.2 3 方式に共通する骨格

3 方式はいずれも同じ骨格をたどり、違いは 1 ステップに限られる。

```text
(任意) 繊維画素を同定して背景プールから除外
    -> 平滑なトレンド曲面をフィットして減算        (デトレンド)
    -> 除外された画素を充填                        <- ここが方式の違い
    -> Savitzky-Golay 平滑化
    -> トレンド曲面を足し戻す                      (リトレンド)
    -> 元画像から減算
```

さらに 3 方式とも、最後に任意の 3×3 中央値フィルタを適用する。`apply_median`
（既定は無効）で有効化でき、インパルス状の残留ノイズを抑える代わりに、最も
鋭い高さ特徴を鈍らせる。

このデトレンド／リトレンドの挟み込みが最も効く部分である。トレンドを除くと
マスクされた穴を跨ぐ高さ差がほぼゼロになるため、充填法の選択はほとんど効か
なくなる。幅 21 px の穴で実測すると、弦からの最大偏差は最近傍伝播で 0.24 nm、
inpainting で 0.20 nm。ところがデトレンド前は**3.93 nm** であった。フィット
は `BGCalibrator._fit_trend_surface` が行う。

`_fit_trend_surface` は平面ではなく**2 次曲面**をフィットする。実際の走査は
傾いているだけでなく皿状に歪んでいるためであり、2 次にすることで繊維の穴を
跨ぐ充填残差が 0.68 nm（平面）から 0.24 nm へ減少した。2 次項を作る前に座標を
$[-1, 1]$ へ正規化し、設計行列の条件数を良好に保つ。背景画素の配置が退化して
いる場合（たとえば全点が 1 行に載る場合）、`numpy.linalg.lstsq` はランク落ち
でも黙って解を返してしまうため、ランクを明示的に検査し、2 次 → 平面 → 背景の
平均レベル、の順にフォールバックする。

座標を $x_n, y_n \in [-1, 1]$ へ正規化すると、フィットする曲面は

$$
T(x, y) = a\,x_n^2 + b\,y_n^2 + c\,x_n y_n + d\,x_n + e\,y_n + g
$$

であり、背景画素（`valid_mask`）だけを使って最小二乗で解く。

```python
# source: lib/bg_calibrator.py::BGCalibrator._fit_trend_surface
h, w = image.shape
y_grid, x_grid = np.mgrid[0:h, 0:w]
x_n = x_grid / max(w - 1, 1) * 2.0 - 1.0
y_n = y_grid / max(h - 1, 1) * 2.0 - 1.0
ones = np.ones_like(x_n)
z = image[valid_mask]
for terms in (
    (x_n * x_n, y_n * y_n, x_n * y_n, x_n, y_n, ones),
    (x_n, y_n, ones),
):
    design = np.column_stack([t[valid_mask] for t in terms])
    coef, _residuals, rank, _singular = np.linalg.lstsq(design, z, rcond=None)
    if rank == design.shape[1]:
        return sum(c * t for c, t in zip(coef, terms))
return np.full(image.shape, float(np.mean(z)), dtype=np.float64)
```

### 1.3 `trendfill` — 既定の方式

名前は動作そのものを表す。トレンドを引き、穴を埋める。バージョン 1.0.0 まで
は `inpaint` と呼ばれており、当時の充填は OpenCV の Navier–Stokes inpainting
だった。`bg_calibrator.BG_METHOD_ALIASES` が旧綴りを現在名へ変換するので、
保存済みパラメータファイルは今も動作する。

`_call_trendfill` は以下の 3 手順を実行し、結果を減算する。

```python
# source: lib/bg_calibrator.py::BGCalibrator._call_trendfill
self._detect_fiber_mask(image.original_image)
self.bg_only, self.bg_sm = self._bg_generate(image.original_image, self.tri_difx_fill, self.tri_dify_fill)
...
calibrated_image = self._bg_calibrate(image.original_image, self.bg_sm)
if self.apply_median:
    calibrated_image = cv2.medianBlur(calibrated_image.astype(np.float32), ksize=3)
image.calibrated_image = calibrated_image
```

#### 手順 1 — 勾配統計から繊維画素を見つける

`BGCalibrator._detect_fiber_mask` が 4 つのヘルパーを順に実行する。

```python
# source: lib/bg_calibrator.py::BGCalibrator._detect_fiber_mask
self.dif_x, self.dif_y = self._difXY(original)
self.histx, self.histy, self.outx, self.outy = self._bg_fit(self.dif_x, self.dif_y)
self.tri_difx, self.tri_dify = self._dif_sep(self.dif_x, self.dif_y, self.outx, self.outy)
self.tri_difx_fill, self.tri_dify_fill = self._extract_fiber(self.tri_difx, self.tri_dify)
```

`_difXY` は各軸方向の 1 次差分 $\Delta_x$、$\Delta_y$ を取る。絶対値の大きい
差分はエッジを示し、この試料では繊維の側面を意味する。

```python
# source: lib/bg_calibrator.py::BGCalibrator._difXY
dif_x = image[:, 1:] - image[:, 0:-1]
dif_y = image[1:, :] - image[0:-1, :]
return dif_x, dif_y
```

`_bg_fit` は各差分画像を 150 ビンのヒストグラムにし、`lmfit` で**ガウス関数
＋線形ベースライン**をフィットする。ガウス成分が*背景*集団、すなわちゼロ近傍
に中心を持つ基板のノイズである。繊維の側面は裾に現れる。X と Y を独立に
フィットするのは、AFM の低速走査軸がノイズ特性を異にし、$\sigma$ が広がり
やすいためである。

フィットの初期値は、差分の中央値と頑健な幅（四分位範囲を 1.349 で割った値）
である。Y のフィットは `dif_y` に対する同じコードである。

```python
# source: lib/bg_calibrator.py::BGCalibrator._bg_fit
histx = np.histogram(np.ravel(dif_x), bins=bin_n)
...
h_arrayx = (histx[1][1:] + histx[1][:-1]) / 2
...
bg = PolynomialModel(prefix='bg_', degree=1)
pV1 = GaussianModel(prefix='pv1_')
model = pV1 + bg
pars_x = model.make_params()
pars_x['bg_c0'].set(0)
pars_x['bg_c1'].set(0)
pars_x['pv1_amplitude'].set(dif_x.size / 10)
pars_x['pv1_center'].set(np.median(dif_x))
pars_x['pv1_sigma'].set((np.percentile(dif_x, 75) - np.percentile(dif_x, 25)) / 1.349)
outx = model.fit(histx[0], pars_x, x=h_arrayx)
```

`_dif_sep` はフィットで得た中心 $\mu$ と幅 $\sigma$ を用いて、各差分画像を
**3 値マップ**へ変換する。

$$
\text{tri} = \begin{cases}
+1 & \Delta > \mu + f\sigma \\
0 & \text{それ以外} \\
-1 & \Delta < \mu - f\sigma
\end{cases}
$$

ここで $f$ が `threshold_factor`（既定 2.0）である。すなわち $\pm 1$ は
「この段差は基板ノイズにしては大きすぎる」ことを表し、固定の nm 値ではなく
画像ごとに較正される。

Y のマップも Y のフィットから同じ方法で作る。

```python
# source: lib/bg_calibrator.py::BGCalibrator._dif_sep
outx_min = outx.best_values['pv1_center'] - self.threshold_factor * outx.best_values['pv1_sigma']
outx_max = outx.best_values['pv1_center'] + self.threshold_factor * outx.best_values['pv1_sigma']
...
tri_difx = np.where(dif_x < outx_min, -1, 0) + np.where(dif_x > outx_max, 1, 0)
```

続いて `_extract_fiber` が各行（X 用）と各列（Y 用）を走査し、3 値マップを
ランレングス符号化して、走査線を横切るリッジが生む 2 つの符号パターンを
探す。

- **パターン 1 — `[+1, 0, -1]`**: 側面を上り、頂上で平坦になり、反対側の
  側面を下る。平坦区間が `fiber_detect_factor`（既定 10）より短いとき採用
  する。つまり頂上が繊維とみなせる程度に狭い場合である。
- **パターン 2 — `[+1, -1]`**: 平坦な頂上が分解されない鋭いリッジ。スパンが
  `noise_detect_factor`（既定 10）を超えるとき採用する。1 画素のノイズ
  スパイクを排除しているのがこの条件である。

パターンの外側境界の間にある画素がすべて繊維としてマークされる。X と Y の
結果は次の手順で和集合として統合される。

コードでは、`l_arr` が各ランの値を、`arg_arr` がそのランの開始位置を持つ。
パターン 1 は 0 のランが `fiber_detect_factor` より短いとき、パターン 2 は +1 の
ランの開始から −1 の次のランの開始までが `noise_detect_factor` を超えるときに
採用する。Y の走査は行と列を入れ替えた同じコードである。

```python
# source: lib/bg_calibrator.py::BGCalibrator._extract_fiber
tri_difx_fill = np.zeros(tri_difx.shape)
for j in range(tri_difx.shape[0] - 1):
    row = tri_difx[j, :]
    change_pos = np.where(np.diff(row) != 0)[0]
    l_arr = np.empty(len(change_pos) + 1, dtype=row.dtype)
    l_arr[0] = row[0]
    l_arr[1:] = row[change_pos + 1]
    arg_arr = np.empty(len(change_pos) + 1, dtype=np.intp)
    arg_arr[0] = 0
    arg_arr[1:] = change_pos + 1
    n = len(l_arr)
    if n < 4:
        continue
    mask1 = (l_arr[:-3] == 1) & (l_arr[1:-2] == 0) & (l_arr[2:-1] == -1)
    gap1_ok = (arg_arr[2:-1] - arg_arr[1:-2]) < self.fiber_detect_factor
    for vi in np.where(mask1 & gap1_ok)[0]:
        tri_difx_fill[j, arg_arr[vi]:arg_arr[vi + 3] - 1] = 1
    mask2 = (l_arr[:-3] == 1) & (l_arr[1:-2] == -1)
    gap2_ok = (arg_arr[2:-1] - arg_arr[:-3]) > self.noise_detect_factor
    for vi in np.where(mask2 & gap2_ok)[0]:
        tri_difx_fill[j, arg_arr[vi]:arg_arr[vi + 2] - 1] = 1
```

#### 手順 2 — マスクの整理と膨張

`_bg_generate` では、マスクを使う前に 2 つの補正を行う。

**小成分の除去。** パターン 2 は 2〜10 画素程度のノイズ特徴にも反応し、
ノイズの多い画像や広視野画像では画面全体に密に散らばる。8 連結成分のうち
`min_mask_component_area`（既定 10）未満のものを除去する。これが無いと、
以下の膨張が 1 つの偽検出を $(2d+1)^2$ の穴へ拡大し、再構成背景がゴマ塩状
となって、タイル状・細胞状のアーティファクトとして現れる。

**膨張。** マスクを `mask_dilation` px（既定 3）膨張させる。`_extract_fiber`
が拾いきれない繊維の*肩*の画素には残留する繊維高さがあり、背景プールに残す
と推定値が底上げされ、繊維の両脇で過剰減算——暗いハロー——を生む。

`tri_difx_fill[1:, :]` と `tri_dify_fill[:, 1:]` は、和を取る前に X と Y の
マップを切り詰め後の画像の格子へ揃える。小成分の除去が行われるのは、膨張が
有効（`mask_dilation` > 0）で、かつ `min_mask_component_area` が 1 より大きい
ときだけである。

```python
# source: lib/bg_calibrator.py::BGCalibrator._bg_generate
raw_mask = (np.abs(tri_difx_fill[1:, :]) + np.abs(tri_dify_fill[:, 1:])) > 0
if self.mask_dilation > 0 and self.min_mask_component_area > 1:
    n_cc, cc_labels, cc_stats, _cc_centroids = cv2.connectedComponentsWithStats(
        raw_mask.astype(np.uint8), connectivity=8,
    )
    keep = np.zeros(n_cc, dtype=bool)
    if n_cc > 1:
        keep[1:] = cc_stats[1:, cv2.CC_STAT_AREA] >= self.min_mask_component_area
    raw_mask = keep[cc_labels]
if self.mask_dilation > 0:
    kernel = np.ones(
        (self.mask_dilation * 2 + 1, self.mask_dilation * 2 + 1),
        dtype=np.uint8,
    )
    fiber_mask = cv2.dilate(raw_mask.astype(np.uint8), kernel).astype(bool)
else:
    fiber_mask = raw_mask
```

#### 手順 3 — 充填・平滑化・減算

マスクされた画素は**最近傍の背景候補画素**の値で埋める。探索には
`scipy.ndimage.distance_transform_edt` を使う。背景画素にとっての最近傍
背景画素は自分自身なので、実データはそのまま厳密に保存され、明示的な復元
処理を必要としない。

充填後の曲面を Savitzky–Golay フィルタ（`savgol_window` 既定 31、
`savgol_polyorder` 既定 1）で平滑化し、トレンドを足し戻し、`_bg_calibrate`
が元画像から減算する。

`signal.savgol_filter` は最後の軸に沿って働くため、平滑化は各行（X 方向）に
沿ってだけ行われる。

```python
# source: lib/bg_calibrator.py::BGCalibrator._bg_generate
crop = original[1:, 1:]
bg_only = np.where(~fiber_mask, crop, float('nan'))
valid_mask = ~fiber_mask
if not valid_mask.any():
    return bg_only, np.zeros_like(crop, dtype=np.float64)
bg_trend = self._fit_trend_surface(crop, valid_mask)
detrended = crop - bg_trend
nearest_idx = distance_transform_edt(
    fiber_mask, return_distances=False, return_indices=True,
)
bg_int = detrended[tuple(nearest_idx)]
bg_sm = signal.savgol_filter(
    bg_int, self.savgol_window, self.savgol_polyorder,
) + bg_trend
return bg_only, bg_sm
```

```python
# source: lib/bg_calibrator.py::BGCalibrator._bg_calibrate
height_bgcalib = original[1:, 1:] - bg_sm
return height_bgcalib
```

> **充填法を変更した理由。** Navier–Stokes inpainting は細い傷の修復を想定
> した境界伝播法である。`inpaintRadius=3` では穴の左右それぞれの境界値を
> 平坦に内側へ伸ばし、中央で段差になっていた（幅 21 px の穴で実測 ±4 nm）。
> `savgol_polyorder <= 1` のとき Savitzky–Golay は X 方向の単純移動平均その
> ものになるため、この段差が穴から窓半分以内にある本物の背景画素の推定値へ
> 漏れ出し、反対称のハローを生んでいた。上り側に溝、下り側に尾根である。
> 尾根は**+0.76 nm** に達し、二値化しきい値の既定 0.3 nm を超えるため、実際
> の繊維に並走する 2 本目の繊維として抽出されていた。

### 1.4 `tophat` — 高速・マスク不要

`_call_tophat` は背景を、直径 `tophat_se_size`（既定 25 px）の楕円構造要素
による形態学的 **opening** として推定する。opening は円盤より細い明るい構造
を除去するので、残るものが背景である。残差 `original - opening` が典型的な
white top-hat 変換にあたる。

ここではトレンド曲面を繊維も含む全画素でフィットし、デトレンドした画像に
opening をかけ、X 方向に平滑化してからトレンドを戻す。

```python
# source: lib/bg_calibrator.py::BGCalibrator._call_tophat
se = cv2.getStructuringElement(
    cv2.MORPH_ELLIPSE,
    (self.tophat_se_size, self.tophat_se_size),
)
bg_trend = self._fit_trend_surface(
    original, np.ones(original.shape, dtype=bool),
)
opened_detrended = cv2.morphologyEx(
    (original - bg_trend).astype(np.float32), cv2.MORPH_OPEN, se,
).astype(np.float64)
self.bg_open = opened_detrended + bg_trend
self.bg_sm = signal.savgol_filter(
    opened_detrended, self.savgol_window, self.savgol_polyorder,
) + bg_trend
calibrated_image = original[1:, 1:] - self.bg_sm[1:, 1:]
calibrated_image -= np.median(calibrated_image)
```

省略できない要点が 2 つある。

**デトレンドした写しに opening をかける。** opening は画像内部では平面を
再現するが、構造要素の半径以内の境界域では再現しない。そこでは収縮が切り
詰められた近傍から最小値を取り、膨張が復元できないからである。0.34 nm/px の
傾斜と直径 25 px の要素では、上り側の端に高さ約**4 nm** の帯が残る。二値化
しきい値 0.3 nm を大きく超えるため、走査端そのものが繊維として抽出されて
いた。

**その後に中央値で再センタリングする。** opening は*下側包絡線*の推定量で
あり、ノイズのある基板では局所極小に張り付く。そのため減算後の基板レベルは
ノイズ包絡の深さ分だけ正側に浮く。画像中央値を引くことで 0 nm へ戻し、
`global_threshold`、`low_threshold`、`bp_height` が、ノイズの中央を通る補間系
の方式と同じ意味を持つようにする。繊維被覆率が約半分未満であれば中央値は
頑健である。

本方式は繊維マスクを作らないため、リッジ検出系の中間配列はオブジェクトに
残らない。前回実行の値が黙って参照される事故を避けるため、明示的に `None`
が設定される。

### 1.5 `spline1d` — ラインノイズ主体の走査向け

`_call_spline1d` は `trendfill` の繊維マスクを流用したうえで、`spline1d_axis`
が指す軸に沿って、各ラインを次数 `spline1d_degree`（既定 2）の 1 次元
B スプラインで独立に埋める。各**列**を補間する（`'y'`）と横縞——フィード
バックループのドリフトが生むライン間オフセット——が均され、各**行**を補間
する（`'x'`）と縦縞が対象になる。

既定の軸は `'x'` である。有効サンプルが `spline1d_degree` + 1 個未満のライン、
または次数が 2 未満の場合は、代わりに線形で埋める。

ライン端には意図的に**形を外挿しない**。各ラインの最初／最後の有効サンプルより
外側は片側にしか背景データが無いため、1 次元手法がそこに置く形——スプライン
自身の外挿や線形の傾き——はそのライン単独で当てたものになる。その誤差は区間が
長いほど増え、隣接ラインと無相関なので、各ラインが自前の帯を描いてしまう。
`_spline1d_fill` は代わりに、各端の区間にわたって**そのライン自身の最近傍
`end_window` 個の背景サンプルの平均**を保持する。`end_window` には
`savgol_window`（既定 31）を渡す。デトレンド後の画像でライン固有に残る量は
実質的に走査ラインのオフセットであり、ライン方向に一定なので、水準を保持すれば
傾きを外挿せずにこれを推定できる。多数のサンプルを平均するのは、その水準に
画素ノイズを持ち込まないためである。有効サンプルが 2 点未満のラインだけは
埋めずに残し、その画素を 2 次元の最近傍背景画素から埋める。

```python
# source: lib/bg_calibrator.py::BGCalibrator._call_spline1d
self._detect_fiber_mask(original)
self.bg_only, _ = self._bg_generate(original, self.tri_difx_fill, self.tri_dify_fill)
...
bg_trend = self._fit_trend_surface(crop, valid_mask)
detrended = np.where(valid_mask, crop - bg_trend, float('nan'))
bg_int = self._spline1d_fill(
    detrended, axis=self.spline1d_axis, order=self.spline1d_degree,
    end_window=self.savgol_window,
)
unfilled = np.isnan(bg_int)
if unfilled.any():
    nearest_idx = distance_transform_edt(
        ~valid_mask, return_distances=False, return_indices=True,
    )
    nearest = np.where(valid_mask, crop - bg_trend, 0.0)[tuple(nearest_idx)]
    bg_int = np.where(unfilled, nearest, bg_int)
bg_int = bg_int + bg_trend
...
self.bg_sm = signal.savgol_filter(bg_int, self.savgol_window, self.savgol_polyorder)
calibrated_image = original[1:, 1:] - self.bg_sm
```

```python
# source: lib/bg_calibrator.py::BGCalibrator._spline1d_fill
if n_valid < 2:
    continue
s = pd.Series(line)
if n_valid >= order + 1 and order >= 2:
    filled = s.interpolate(method='spline', order=order,
                           limit_direction='both')
else:
    filled = s.interpolate(method='linear', limit_direction='both')
filled = filled.to_numpy(copy=True)
valid_pos = np.flatnonzero(valid)
first, last = valid_pos[0], valid_pos[-1]
k = max(1, min(end_window, n_valid))
filled[:first] = np.mean(line[valid_pos[:k]])
filled[last + 1:] = np.mean(line[valid_pos[-k:]])
```

### 1.6 方式の選び方

| `bg_method` | 使う場面 | コスト |
|---|---|---|
| `trendfill`（既定） | 一般用途。繊維を背景プールから除外するため、繊維自体を削り込まない。 | 最も高い。`lmfit` のヒストグラムフィットが支配的。 |
| `tophat` | 手早い確認。あるいは特殊な試料でリッジ検出が期待どおり働かない場合。 | 低い。 |
| `spline1d` | ラインノイズ（フィードバック不良、走査線オフセット）が支配的な走査。 | 中程度。 |

`spline2d`（テンソル積 B スプライン曲面）は 1.0.0 以降で**削除**された。
全テスト画像において全方式中で最大の背景残差を残し、それを改善しうる平滑化
係数が GUI から到達できなかったためである。`bg_calibrator.BG_METHOD_REMOVED`
に名前として記録されており、生き残った方式へ読み替えることはしない。黙って
置換すると、保存済み `_param.json` が再現する数値が変わってしまう。

---

## 2. 二値化

**コード:** `lib/segmenter.py` — `Segmenter.__call__`。
**読む:** `calibrated_image`。**書く:** `binarized_image`。

この段はフィルタの連鎖である。調整時に各段の出力を確認できるよう、それぞれ
独立したメソッドになっている。

```text
_binaryzation             -> binary_image
_remove_small_fragments   -> no_small_binary_image
_remove_nonlinear_objects -> no_linear_binary_image
_remove_connecting_fragments（任意） -> no_connecting_binary_image
remove_low_component      -> no_low_binary_image
_recover_missed_ridges（任意）      -> ridge_recovered_image
closing                   -> binarized_image
```

`Segmenter.__call__` はこれらを次の順に結線している。

```python
# source: lib/segmenter.py::Segmenter.__call__
self.binary_image = self._binaryzation(
    image.calibrated_image, self.global_threshold, self.wsize_localbin
)
self.no_small_binary_image = self._remove_small_fragments(self.binary_image, self.area_min)
self.no_linear_binary_image = self._remove_nonlinear_objects(
    self.no_small_binary_image, self.h_length, self.h_sratio
)
if self.apply_no_connecting:
    self.no_connecting_binary_image = self._remove_connecting_fragments(
        self.no_linear_binary_image
    )
else:
    self.no_connecting_binary_image = self.no_linear_binary_image
self.no_low_binary_image = self.remove_low_component(
    image.calibrated_image, self.no_connecting_binary_image
)
self.ridge_recovered_image = self._recover_missed_ridges(
    image.calibrated_image, self.no_low_binary_image, nm_per_px,
)
recovered_union = self.no_low_binary_image | self.ridge_recovered_image
no_small_binary_image4 = closing(recovered_union).astype(bool)
image.binarized_image = no_small_binary_image4
```

### 2.1 2 つのしきい値の論理積

`_binaryzation` は画素に**両方**の検定を要求する。

$$
\text{mask} = (h > t_{\text{global}}) \;\wedge\; (h > t_{\text{local}}(x,y))
$$

大域しきい値 `global_threshold`（既定 0.3 nm）は基板からの絶対高さである。
背景補正が不可欠になるのはこの値のためである。局所しきい値は
`skimage.filters.threshold_local` を窓幅 `wsize_localbin` px（既定 17）で
適用したもので、残存する緩やかな変動に追随する。

両方を要求するのは意図的である。局所検定だけでは何もない領域（ノイズ同士
しか比較対象が無い）でノイズを持ち上げてしまい、大域検定だけでは局所的に
沈んだ領域にある繊維を取りこぼす。

`skimage.filters.threshold_local` は既定の引数で呼ぶため、局所しきい値は窓内のガウス重み付き
平均（オフセット 0）である。

```python
# source: lib/segmenter.py::Segmenter._binaryzation
binary_global = image > global_threshold
local_threshold = threshold_local(image, wsize_localbin)
binary_local = image > local_threshold
binary_final = binary_global & binary_local
return binary_final
```

### 2.2 面積フィルタ

`_remove_small_fragments` は 8 連結成分のうち面積が `area_min`（既定
100 px²）以下のものを除去し、続けて 3×3 の中央値フィルタを適用する。これに
より孤立した単一画素が消え、成分の縁のギザつきが均される。

```python
# source: lib/segmenter.py::Segmenter._remove_small_fragments
out_binary_image = binary_image.copy()
n_labels, label_image, stats, centers = cv2.connectedComponentsWithStats(
    np.uint8(out_binary_image), 8
)
areas = stats[:, cv2.CC_STAT_AREA]
small_labels = np.where(areas <= area_min)[0]
mask_remove = np.isin(label_image, small_labels)
out_binary_image[mask_remove] = 0
out_binary_image = cv2.medianBlur(out_binary_image.astype(np.float32), ksize=3)
return out_binary_image.astype(bool)
```

### 2.3 直線性フィルタ

`_remove_nonlinear_objects` は成分が*線*らしいかを問う。繊維は線らしく、
汚染粒子や探針アーティファクトはそうではない。

- 面積 1000 px² 以上の成分は検定せずに保持する。その大きさなら答えは自明で
  ある。
- バウンディングボックスが両方向とも `h_length`（既定 20 px）未満の成分は
  除去する。必要な長さの線を含みえないためである。
- それ以外は成分のバウンディングボックスに Canny エッジ検出をかけ、Hough
  変換に通す。スコアは

  $$
  s_{\text{ratio}} = \frac{\sum \text{Hough ピークの投票数}}{\sum \text{エッジ画素数}}
  $$

  であり、「この物体の輪郭のうち直線で説明できる割合はどれだけか」を表す。
  $s_{\text{ratio}} <$ `h_sratio`（既定 0.5）*かつ*画素数が 1000 未満の成分
  を除去する。

エッジマップは、外接矩形内のマスク全体ではなく対象成分自身の画素
（`label_image[bbox] == i`）から作る。外接矩形は軸に平行なので、斜めに走る
繊維の矩形は大きくスカスカで隣接物が入り込みやすい。マスク全体を切り出すと
それらの輪郭が $s_{\text{ratio}}$ の分子・分母の双方に入り、成分の判定が
「たまたま近くに何があったか」で決まりえた。

```python
# source: lib/segmenter.py::Segmenter._remove_nonlinear_objects
for i in range(1, n_labels):
    left, top, width, height, area = stats[i]
    if area >= 1000:
        continue
    if max(width, height) < self.h_length:
        out_binary_image[label_image == i] = 0
        continue
    target = label_image[
        top : top + height, left : left + width
    ] == i
    target_edge = canny(target, sigma=0, low_threshold=0, high_threshold=1)
    h, theta, d = hough_line(target_edge)
    accums, _, _ = hough_line_peaks(
        h, theta, d,
        min_distance=max(1, linegap),
        min_angle=1,
        threshold=h_length,
    )
    if len(accums) > 0:
        total_length = float(np.sum(accums))
    else:
        total_length = 0.0
    s_ratio = total_length / (np.sum(target_edge) + _DENOM_EPS)
    self.h_sratio_list.append(s_ratio)
    if s_ratio < h_sratio and np.sum(target) < 1000:
        out_binary_image[label_image == i] = 0
```

> **これは 1.0.0 以降の変更である。** 実スキャン 22 枚（3318 成分、うち直線性
> 判定の対象 1726 成分）で測定したところ、外接矩形に隣接成分が入っていたのは
> 341 成分で、そのうち 1 スキャンの 1 成分だけが判定を変えていた。最終的な
> 二値化マスクは全スキャンでビット単位に一致し、厳密回帰テストの golden 値も
> 動かなかったため、解析出力は変わらない。詳細な記録は `CHANGELOG.md` にある。

もう 1 点。Hough ピークの `threshold` 引数には `h_length` を渡しているため、
このパラメータは画素単位の長さではなく最小投票数（線長の代理指標）として働く。
また `target` が対象成分のみになったことで、その画素数は `area` と等しくなり、
上の `area >= 1000` ガードが既に上限を与えている。したがって
`np.sum(target) < 1000` の項は、何かを決めるものではなく規則を明示するもので
ある。

### 2.4 弱連結の整理（既定では無効）

`_remove_connecting_fragments` はマスクを収縮させ、面積 `area_min_connecting`
px（既定 3）以下の成分を除去し、膨張で戻して closing する。狙いは 1 画素幅の
橋でつながった断片を切り離すことである。実行されるのは `apply_no_connecting`
が真のときだけで、これは既定では**無効**である。

```python
# source: lib/segmenter.py::Segmenter._remove_connecting_fragments
out_binary_image = binary_image.copy()
out_binary_image = binary_erosion(out_binary_image)
n_labels, label_image, stats, centers = cv2.connectedComponentsWithStats(
    np.uint8(out_binary_image), 8
)
for i in range(1, n_labels):
    *_, area = stats[i]
    if area <= self.area_min_connecting:
        out_binary_image[label_image == i] = 0
out_binary_image = binary_dilation(out_binary_image)
out_binary_image = closing(out_binary_image).astype(bool)
return out_binary_image
```

> **これは 1.0.0 以降の変更である。** 成分ループは `range(n_labels - 1)` で
> ラベル `0 .. n-2` を走査していた。すなわち背景ラベル 0 に入り、最大ラベルへは
> 到達しなかった。OpenCV はラスタ順にラベルを振るため最大ラベルは最も下方の
> 成分であり、画像ごとにちょうど 1 個の成分が、その大きさとは無関係な理由で
> この整理を免れていた。現在は `range(1, n_labels)` である。ラベル 0 に入るのは
> 無害だった（面積がしきい値を満たさず、背景画素の消去は無操作）ため、問題は
> 取りこぼしの側だけである。この経路は既定で無効なので記録済みの解析では一度も
> 実行されておらず、強制的に有効化して実スキャン 22 枚で測ると、3 枚で除去対象
> の成分を 1 個ずつ取りこぼしていた（いずれも 1〜3 画素）。

### 2.5 高さフィルタ

`remove_low_component` は、較正済み画像上での**最大**高さが `low_threshold`
（既定 1.8 nm）未満である成分を除去する。平均ではなく最大を使うことで、
本物の細い繊維が残り、幅広く低い滲みが捨てられる。

最大値は `scipy.ndimage.maximum` で成分ごとに取る。

```python
# source: lib/segmenter.py::Segmenter.remove_low_component
labels = np.arange(1, n_labels)
max_heights = ndi_maximum(height_image, labels=label_image, index=labels)
low_labels = labels[np.asarray(max_heights) < self.low_threshold]
if low_labels.size > 0:
    out_binary_image[np.isin(label_image, low_labels)] = 0
return out_binary_image
```

### 2.6 リッジ回収（既定では無効）

`_recover_missed_ridges` は、しきい値処理の連鎖が*完全に*取りこぼした繊維を
狙う 2 巡目である。`ridge_recovery` が真で、かつ画素サイズが既知の場合に
のみ実行される。設定値が物理長であるためである。

1. マルチスケールの **Frangi** 血管強調フィルタを、`ridge_min_width_nm` から
   `ridge_max_width_nm` を画素へ換算した範囲の等比 5 スケールで実行する。
   物理単位で扱うため、1 つの設定値がどの走査解像度でも同じ構造を意味する。
2. 応答を**ヒステリシス**で二値化する。高い側は大津法、低い側は三角法で
   決める。リッジ応答に対するヒステリシスは、生の振幅に対する同じ方式と違い
   機能する。応答は繊維間でほぼ 0 まで落ちるため、領域が画像全体へ浸透せず
   境界で止まるからである。
3. 採用済みマスクは連結成分処理の**前**に差し引く。既存マスクに一切触れない
   候補成分だけを採る方式では、長い繊維が検出済みの網目にどこか一点でも接した
   瞬間に丸ごと捨てられ、しかも長い繊維ほど接しやすい。ある 10 µm 走査での
   実測では、マスク外に 100 nm 以上の実体を持つ候補成分が 56 個あり（最大
   1476 nm）、その規則はその全てを捨てていた。
4. 残った成分は、そのスケルトン長が `ridge_min_length_nm`（既定 100 nm）に
   達するものだけ採用する。100 nm を下回るあたりから、候補を粒子の裾や探針
   アーティファクトと目視で区別できなくなる。

既定で無効なのは、保存済みパラメータファイルが書かれた当時の数値を再現でき
るようにするためである。有効時は Frangi フィルタが本段の処理時間を占める。

コードでは、最小のスケールは 0.6 px を下回らず、最大のスケールは最小の
1.5 倍以上になる。三角法のレベルが大津法のレベルを下回らない場合、低い側の
レベルは高い側の 0.3 倍に置き換える。

```python
# source: lib/segmenter.py::Segmenter._recover_missed_ridges
if not self.ridge_recovery or not nm_per_px or nm_per_px <= 0:
    return empty
lo = max(0.6, self.ridge_min_width_nm / nm_per_px)
hi = max(lo * 1.5, self.ridge_max_width_nm / nm_per_px)
sigmas = np.geomspace(lo, hi, 5)
response = np.nan_to_num(
    frangi(calibrated_image, sigmas=sigmas, black_ridges=False)
)
if not np.any(response > 0):
    return empty
try:
    high = threshold_otsu(response)
    low = threshold_triangle(response)
except ValueError:
    return empty
if not low < high:
    low = high * 0.3
candidate = apply_hysteresis_threshold(response, low, high)
outside = candidate & ~binary_image.astype(bool)
if not outside.any():
    return empty
n_labels, labels = cv2.connectedComponents(outside.astype(np.uint8), connectivity=8)
keep = [
    label for label in range(1, n_labels)
    if skeletonize(labels == label).sum() * nm_per_px >= self.ridge_min_length_nm
]
if not keep:
    return empty
return np.isin(labels, keep)
```

### 2.7 Closing

最後に形態学的 closing で 1 画素の隙間を橋渡しする。リッジ回収をその*前*に
実行するのは意図的で、既存成分の隣で終わる回収セグメントが独立した短繊維と
して残らず、closing で取り込まれるようにするためである。

---

## 3. 細線化

**コード:** `lib/skeletonizer.py`（形態処理は `lib/imp_tools.py`）。
**読む:** `binarized_image`、`calibrated_image`。
**書く:** `skeleton_image`、`label_image`、`nLabels`、`data`、`ep`、`bp`。

目標は繊維 1 本につき 1 画素幅の中心線を得ることである。難しいのは、細線化が
*マスク*に忠実である一方、マスクには欠陥があるという点である。内部の穴、幅の
揺らぎ、繊維先端の低い裾などである。各欠陥はスケルトン上の位相的特徴になり、
後段の追跡がすべての分岐点で繊維を切断するため、アーティファクト由来の分岐点
は単にノイズを加えるのではなく、**実在の繊維を断片へ分割する**。この段の大半
は、その分割を引き起こすアーティファクトの除去に充てられている。

`Skeletonizer.__call__` は以下を順に実行する。

```python
# source: lib/skeletonizer.py::Skeletonizer.__call__
init_skeleton_image = thin_ignoring_image_border(image.binarized_image)
...
self.set_low_bp_coor(image.calibrated_image, init_skeleton_image, self.bp_height)
self.get_close_eps()
nobranch_image = self.prune_branches(image.calibrated_image, init_skeleton_image)
...
nobranch_skeleton_image = skeletonize(nobranch_image).astype(np.uint8)
...
cleaned_skeleton_image = collapse_skeleton_loops(
    nobranch_skeleton_image, self.max_loop_area, image.calibrated_image
)
cleaned_skeleton_image = prune_short_spurs(
    cleaned_skeleton_image, self.spur_length
)
cleaned_skeleton_image = prune_terminal_hooks(
    cleaned_skeleton_image, image.calibrated_image
)
...
nosmall_skeleton_image = self.remove_small_and_ring(cleaned_skeleton_image)
...
image.skeleton_image = nosmall_skeleton_image
...
image.ep = imp_tools.endPoints(nosmall_skeleton_image)
image.bp = imp_tools.branchedPoints(nosmall_skeleton_image)
```

### 3.1 画像端で繊維を切らずに細線化する

`thin_ignoring_image_border` は画像端を `DEFAULT_BORDER_PAD` = 12 px 外側へ
複製し、細線化してから切り戻す。

`skimage.morphology.thin` は配列外をすべて背景として扱うため、視野外へ抜ける
繊維は配列端で平らに切断された形状となり、その切断端の medial axis は切り口
の近い側の角へ向かって折れる。追跡線は末端の数画素で稜線から外れる。同梱
スキャンでの実測は約 2 px であり、繊維中央部の約 0.5 px と対比される。端を
複製すると繊維は打ち切られず外側へ延長されるため、この折れが消える。12 px の
縁帯より内側のスケルトンは、本補正の有無で完全に一致する。

一方で複製は、端を横切らず端に*沿って*延びる塊を太らせ、その軸を画像外へ
押し出すことがある。そこで、パディング版でスケルトンが空になる連結成分は素の
細線化結果を採用する。本補正で繊維が失われることはない。

```python
# source: lib/skeletonizer.py::thin_ignoring_image_border
mask = (np.asarray(binary_image) > 0).astype(np.uint8)
plain = thin(mask).astype(np.uint8)
if pad <= 0:
    return plain
extended = np.pad(mask, pad, mode='edge')
padded = thin(extended).astype(np.uint8)[pad:-pad, pad:-pad]
n_labels, labels = cv2.connectedComponents(mask)
plain_counts = np.bincount(labels[plain > 0], minlength=n_labels)
padded_counts = np.bincount(labels[padded > 0], minlength=n_labels)
lost = np.nonzero((plain_counts > 0) & (padded_counts == 0))[0]
lost = lost[lost != 0]
if lost.size:
    padded = np.where(np.isin(labels, lost), plain, padded).astype(np.uint8)
return padded
```

### 3.2 高さゲート付きの枝刈り

幾何ではなく高さを使う唯一のクリーニング段である。

`set_low_bp_coor` は、較正済み高さを `bp_height`（既定 10 nm）と比較して、
スケルトンの分岐点を**低い**ものと**高い**ものに分ける。繊維の高さにある
分岐点は 2 本の実在の繊維が交差する場所であり、基板付近にある分岐点は
マスクが偽の突起を生やした場所である。

```python
# source: lib/skeletonizer.py::Skeletonizer.set_low_bp_coor
all_bps = imp_tools.branchedPoints(init_skeleton_image)
low_bp_coor = np.where(all_bps & (calibrated_image < bp_height))
high_bp_coor = np.where(all_bps & (calibrated_image >= bp_height))
```

`get_close_eps` は、低い分岐点から `branch_length` px（既定 12）以内にある
端点を探す。短い偽の枝でありうるのはそれらだけである。

近傍は、各低分岐点の周りのサイズ $2k$ の `scipy.ndimage.maximum_filter` である
（$k$ = `branch_length`）。

```python
# source: lib/skeletonizer.py::Skeletonizer.get_close_eps
all_eps_image = imp_tools.endPoints(self._init_skeleton_image)
_low_bps_image = np.zeros_like(self._init_skeleton_image, dtype=np.uint8)
_low_bps_image[self._coor_low_bps] = 1
k = self.branch_length
dilated_low_bps = maximum_filter(
    _low_bps_image.astype(float), size=2 * k, mode='constant', cval=0, origin=0
)
close_eps = all_eps_image & (dilated_low_bps > 0).astype(np.uint8)
self._coor_close_eps = np.where(close_eps)
```

`track_branches` は各端点からスケルトンを最大 `branch_length` ステップ辿る。
探索が低い分岐点に到達した場合、または分岐点に到達しないまま行き止まりに
なった場合（孤立した短片）、その腕を**刈る**。高い分岐点に接した場合と
ステップ上限を使い切った場合は、短い低分岐であることが確認できないため
**保持**する。

コードでは `x` が行、`y` が列である。各ステップでは、まず行き止まりの判定、
次に低い分岐点の判定、最後に高い分岐点の判定を行い、いずれも現在の画素の 3×3
近傍で調べる。腕を刈る場合は、それまでに辿った画素を枝として記録する。

```python
# source: lib/skeletonizer.py::Skeletonizer.track_branches
def touches(mask: np.ndarray, row: int, col: int) -> bool:
    return bool(mask[max(0, row - 1): row + 2, max(0, col - 1): col + 2].any())
starts_x, starts_y = self._coor_close_eps
bl = self.branch_length
for start_x, start_y in zip(starts_x, starts_y):
    if not (bl <= start_x <= height - bl and bl <= start_y <= width - bl):
        continue
    x, y = int(start_x), int(start_y)
    xtrack = [x]
    ytrack = [y]
    visited = {(x, y)}
    for _ in range(bl):
        next_pixels = [
            (x + dx, y + dy)
            for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if (dx, dy) != (0, 0)
            and 0 <= x + dx < height and 0 <= y + dy < width
            and skeleton[x + dx, y + dy]
            and (x + dx, y + dy) not in visited
        ]
        if not next_pixels:
            branches_coor_x += xtrack
            branches_coor_y += ytrack
            break
        if touches(image_low_bps, x, y):
            branches_coor_x += xtrack
            branches_coor_y += ytrack
            break
        if touches(image_high_bps, x, y):
            break
        x, y = next_pixels[0]
        visited.add((x, y))
        xtrack.append(x)
        ytrack.append(y)
```

この探索には意図的な性質が 2 つあり、どちらも実際の不具合への修正である。

- 探索は画像全体を明示的な境界判定で辿る。従来の局所切り出し内での探索では、
  探索が切り出しの端に達した時点で近傍が空と読めてしまい、行き止まり規則が、
  単に切り出しの外へ続いていただけの繊維先端を最大 `branch_length` 画素削除
  していた。高さを問わないため、`bp_height` を大きく上回る繊維でも起きた。
- 各探索は自前の訪問済み集合を持つ。共有の作業画像を消し込む方式では、先に
  処理した端点の探索が後続の探索から骨格を隠すため、結果が端点の処理順に
  依存していた。

走査端から `branch_length` 以内の端点は対象外である。端の近くで終わる腕は
枝の先端ではなく、視野外へ抜ける繊維だからである。

枝刈り後のマスクは再細線化して 1 画素幅へ戻す。

```python
# source: lib/skeletonizer.py::Skeletonizer.prune_branches
branches_image = self.calc_branches_image(calibrated_image, init_skeleton_image)
return init_skeleton_image - branches_image
```

### 3.3 ループアーティファクトを潰す

`collapse_skeleton_loops` は、スケルトンに**囲まれた**背景領域を探す。
8 連結スケルトンの位相的補集合である 4 連結でラベル付けするため、バウンディング
ボックスが画像端に接しない成分が真の穴である。面積が `max_loop_area`
（既定 100 px）以下の穴を充填し、再細線化することで二重経路を 1 本の線へ
戻す。

二値マスク内部の穴はトポロジー保存細線化で二重経路として残り、ループ 1 つが
連続繊維上に分岐点を 2〜3 個作る。再細線化は既に細い線に対して不動点なので、
充填箇所から離れた画素は動かず、座標キーによる照合はそのまま有効である。

これが 2 本の実在の繊維を融合させないよう、**高さガード**を設けている。
ループアーティファクトは繊維本体の内側にあるため内部は高いままで、同梱
スキャンでは周囲リッジ高の 40〜90 % である。別々の 2 本が 2 点で接触して囲む
細長い隙間は背景レベルの画素（リッジ高の約 10 %）を含む。囲みを充填するのは、
内部の中央値高さが周囲リッジの中央値の `DEFAULT_LOOP_HEIGHT_RATIO` = 0.3 以上
のときだけであり、この値は両者の間に双方向の余裕を持って位置する。誤って
充填すると 2 本が融合し、その間の溝の中央に経路が捏造される。

リングは穴の 5×5 膨張の内側にあるスケルトン画素であり、2 つの高さはいずれも
中央値である。

```python
# source: lib/skeletonizer.py::collapse_skeleton_loops
inv = (skel == 0).astype(np.uint8)
n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
    inv, connectivity=4
)
height, width = skel.shape
fill_labels = []
for i in range(1, n_labels):
    x, y, cw, ch, area = stats[i]
    if not (area <= max_loop_area and x > 0 and y > 0
            and x + cw < width and y + ch < height):
        continue
    if calibrated_image is not None:
        x0, y0 = max(0, x - 2), max(0, y - 2)
        x1, y1 = min(width, x + cw + 2), min(height, y + ch + 2)
        hole_local = labels[y0:y1, x0:x1] == i
        dilated = cv2.dilate(
            hole_local.astype(np.uint8), np.ones((5, 5), np.uint8)
        )
        ring = (dilated > 0) & ~hole_local & (skel[y0:y1, x0:x1] > 0)
        cal_local = calibrated_image[y0:y1, x0:x1]
        if ring.any():
            interior_h = float(np.median(cal_local[hole_local]))
            ridge_h = float(np.median(cal_local[ring]))
            if interior_h < min_height_ratio * ridge_h:
                continue
    fill_labels.append(i)
if not fill_labels:
    return skel
filled = (skel > 0) | np.isin(labels, fill_labels)
return skeletonize(filled).astype(np.uint8)
```

### 3.4 短いスパーを刈る

`prune_short_spurs` は、端点から出発して分岐点に到達する、`spur_length`
（既定 12 px）より短い行き止まりの腕を除去する。

§3.2 と違い**純粋に幾何的**であり、それが要点である。繊維本体から生えた
スパーは繊維の高さにあるため高さしきい値では実在の交差と区別できないが、
長さの上限なら区別できる。実在の繊維の腕がそこまで短いことは稀だからである。
到達範囲に分岐点が無い孤立した短片は保持し、端点が画像端から
`border_margin` = 2 px 以内にある腕は決して刈らない。理由は上と同じで、
走査端の直前で接触する 2 本の繊維は真の合流点を作っており、その短い腕を刈る
と 2 本が融合してしまう。

合流点とは、スケルトン上の隣接画素を 3 つ以上持つ分岐点である
（`_junction_degree`）。探索は分かれ道で刈らずに止まり、スパーが 1 本も除去され
なくなるまでパス全体を繰り返す。

```python
# source: lib/skeletonizer.py::prune_short_spurs
while True:
    bp = imp_tools.branchedPoints(skel).astype(bool)
    if not bp.any():
        return skel
    ep_mask = imp_tools.endPoints(skel).astype(bool) & (skel > 0)
    removed = False
    for sy, sx in zip(*np.where(ep_mask)):
        if (sy < border_margin or sx < border_margin
                or sy >= height - border_margin
                or sx >= width - border_margin):
            continue
        path = [(int(sy), int(sx))]
        cy, cx = int(sy), int(sx)
        while len(path) <= max_length:
            candidates = []
            hit_junction = False
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if not (0 <= ny < height and 0 <= nx < width):
                        continue
                    if not skel[ny, nx] or (ny, nx) in path:
                        continue
                    if bp[ny, nx] and _junction_degree(skel, ny, nx) >= 3:
                        hit_junction = True
                    else:
                        candidates.append((ny, nx))
            if hit_junction:
                for py, px in path:
                    skel[py, px] = 0
                removed = True
                break
            if len(candidates) != 1:
                break
            cy, cx = candidates[0]
            path.append((cy, cx))
    if not removed:
        return skel
```

### 3.5 末端フックを切除する

`prune_terminal_hooks` は、上の 3 パスがいずれも検出できない欠陥を扱う。
セグメンテーションが繊維先端の低く広がった「裾」をマスクに含めると、細線化は
その medial axis を裾へ辿って周縁を回り込み、**分岐点を持たないフック**を
残す。枝刈りは分岐点を必要とし、スパー除去は合流点を必要とし、ループ潰しは
閉じた穴を必要とする。フックはそのいずれも持たない。

フックは端点近傍の方向反転で認識する。端から `DEFAULT_HOOK_LENGTH` = 12 px
以内で頂点内角が `DEFAULT_HOOK_APEX_ANGLE_DEG` = 120 度未満になる場合である。
切除するのは、較正高さが隣接する本体の中央値高さの
`DEFAULT_HOOK_HEIGHT_RATIO` = 0.5 未満に落ちた画素だけである。同梱スキャン
ではフック画素は本体高の 19〜42 %、実在の折れ末端や合流部の蛇行は 55〜113 %
であり、0.5 が両者を分離する。本当に折れ曲がった繊維末端は繊維の高さを保つ
ため、決して切られない。

頂点角 120 度はキンク判定しきい値 150 度よりはるかに鋭いため、キンク検出に
干渉しない。切除量は見つかった最深の反転頂点までに制限され、まっすぐ薄れて
いく末端が短くされることはない。

（誤りを含む）マスクを所与とすればフックは裾の忠実な medial axis であるため、
細線化文献の二値形状のみの有意性測度では同定できない。欠けている情報は高さ
データだからである。判定基準は代わりにグレースケール誘導の繊維トレースに従う。
繊維の中心線は高さの稜線上になければならない、という基準である。

コードでは、各端点からの経路（`_walk_from_endpoint`）を最大 30 px 辿る。
経路の添字 $j \le 12$ における頂点角は、6 ステップ先の点（$j + 6$）へのベクトルと、
端点へ戻るベクトルのなす角である。角度が 120 度未満となる最も深い $j$ が頂点で
ある。本体の高さは頂点より後の 12 画素の中央値で（4 画素以上が必要）、先頭の
画素を、高さがその半分未満である間だけ、頂点を越えない範囲で除去する。

```python
# source: lib/skeletonizer.py::DEFAULT_HOOK_LENGTH, DEFAULT_HOOK_APEX_ANGLE_DEG, DEFAULT_HOOK_HEIGHT_RATIO, _HOOK_DIRECTION_WINDOW, _HOOK_BODY_WINDOW
DEFAULT_HOOK_LENGTH = 12
DEFAULT_HOOK_APEX_ANGLE_DEG = 120.0
DEFAULT_HOOK_HEIGHT_RATIO = 0.5
_HOOK_DIRECTION_WINDOW = 6
_HOOK_BODY_WINDOW = 12
```

```python
# source: lib/skeletonizer.py::prune_terminal_hooks
path = _walk_from_endpoint(skel, int(sy), int(sx), walk_cap)
n = len(path)
py = np.array([p[0] for p in path], dtype=float)
px = np.array([p[1] for p in path], dtype=float)
apex = -1
for j in range(1, min(max_hook_length, n - _HOOK_DIRECTION_WINDOW - 1) + 1):
    body_y = py[j + _HOOK_DIRECTION_WINDOW] - py[j]
    body_x = px[j + _HOOK_DIRECTION_WINDOW] - px[j]
    end_y = py[0] - py[j]
    end_x = px[0] - px[j]
    norm_body = float(np.hypot(body_y, body_x))
    norm_end = float(np.hypot(end_y, end_x))
    if norm_body == 0.0 or norm_end == 0.0:
        continue
    cos_apex = (body_y * end_y + body_x * end_x) / (norm_body * norm_end)
    angle = float(np.degrees(np.arccos(np.clip(cos_apex, -1.0, 1.0))))
    if angle < max_apex_angle_deg:
        apex = j
if apex < 0:
    continue
body_px = path[apex + 1: apex + 1 + _HOOK_BODY_WINDOW]
if len(body_px) < 4:
    continue
body_median = float(np.median(
    [calibrated_image[p] for p in body_px]
))
threshold = max_height_ratio * body_median
if threshold <= 0.0:
    continue
run = 0
while run < apex and calibrated_image[path[run]] < threshold:
    run += 1
for i in range(run):
    skel[path[i]] = 0
```

### 3.6 微小成分とリング成分の除去

`remove_small_and_ring` は `min_area`（既定 10 px）未満の成分と、**端点を
まったく持たない**成分を除去する。端点の無い成分は閉じたリングであり、どの
繊維追跡もこれを辿れない。

```python
# source: lib/skeletonizer.py::Skeletonizer.remove_small_and_ring
returned_image = np.copy(skeleton_image)
nLabels, label_Images, data, center = cv2.connectedComponentsWithStats(returned_image)
ep = imp_tools.endPoints(returned_image)
ring_frac_label = np.setdiff1d(np.arange(1, nLabels), label_Images[ep > 0])
areas = np.array([data[i][4] for i in range(1, nLabels)])
small_labels = np.nonzero(areas < self.min_area)[0] + 1
remove_labels = np.union1d(small_labels, ring_frac_label)
if remove_labels.size > 0:
    returned_image[np.isin(label_Images, remove_labels)] = 0
return returned_image
```

### 3.7 端点と分岐点

`imp_tools.endPoints` と `imp_tools.branchedPoints` は、各スケルトン画素を
3×3 近傍パターン集合との hit-or-miss マッチング（`cv2.MORPH_HITMISS`）で
分類する。パターンと回転順は元のラボコードのものを保持している。得られた
`ep` / `bp` マップはバンドルに保存され、下流の追跡と
`measure.isolated_fiber_flags` の孤立判定が参照する。

スケルトンには先に背景画素 1 つ分のパディングを付けるため、画像の縁にある
画素は、走査がそこで終わっているものとして分類される。

```python
# source: lib/imp_tools.py::_hitmiss_union, branchedPoints, endPoints
padded = np.pad(skel, pad_width=1, mode='constant', constant_values=0).astype(np.uint8)
hits = np.zeros_like(padded, dtype=np.uint8)
for p in patterns:
    hits |= cv2.morphologyEx(padded, cv2.MORPH_HITMISS, p)
return np.ascontiguousarray(np.where(hits > 0, 1, 0).astype(np.uint8)[1:-1, 1:-1])
...
return _hitmiss_union(skel, _BRANCH_PATTERNS)
...
return _hitmiss_union(skel, _END_PATTERNS)
```

---

## 4. キンク検出

**コード:** `lib/kink_detector.py` — `KinkDetector.__call__` と
`KinkDetector.kinks_on_line`。判定は `lib/centerline.py` が作る線（§4.2）の上で
行う。
**読む:** `skeleton_image`、`calibrated_image`、`bp`。**書く:** ラベルごとの
キンク配列、端のそばで判定しなかった折れ（§4.4）、およびその平坦化版。

キンクとは繊維の**局在した鋭い折れ**であり、滑らかな曲率とは区別される。
これを検出するには何を鋭いとみなすかを決める必要があり、さらに見落とされ
やすい点として、どの尺度で見るかを決める必要がある。中心線を 1 画素ずつ辿れば
鋭く見える折れも、繊維の尺度で見れば緩やかな曲がりでありうる。ここでの尺度は
繊維の見かけ幅 $W$（§4.2）であり、それは探針が画像に残す分解能でもある。

`KinkDetector.__call__` は、追跡した各成分の中心線を置いて判定する。キンクは
`placed.x`、`placed.y` の上で判定し、同じ添字のスケルトン画素に保存する。

```python
# source: lib/kink_detector.py::KinkDetector.__call__
no_bp_skel = imp_tools.remove_bp(image.skeleton_image)
no_Lcorner_skel = imp_tools.remove_Lcorner(no_bp_skel)
nLabels, label_image, data, center = cv2.connectedComponentsWithStats(no_Lcorner_skel)
branch_points = getattr(image, "bp", None)
if branch_points is None:
    branch_points = imp_tools.branchedPoints(image.skeleton_image)
...
for label in range(1, nLabels):
    x, y, w, h, area = data[label]
    sub_label = label_image[y:y+h, x:x+w]
    target_image = (sub_label == label).astype(np.uint8)
    try:
        _xtrack_local, _ytrack_local = imp_tools.tracking(target_image)
...
    _xtrack = _xtrack_local + x
    _ytrack = _ytrack_local + y
    placed = place_centerline(
        image.calibrated_image, _xtrack, _ytrack, branch_points,
    )
...
    judged = self.judge_line(placed.x, placed.y, placed.width_px)
...
    all_kink_coordinate_x.extend(_xtrack[kink_indices])
    all_kink_coordinate_y.extend(_ytrack[kink_indices])
    all_kink_angles.extend(list(kink_angles))
    all_kink_excess.extend(list(judged.kink_excess))
    unjudged_point_x.extend(_xtrack[unjudged_indices])
    unjudged_point_y.extend(_ytrack[unjudged_indices])
```

### 4.1 追跡可能なトラックを用意する

`imp_tools.remove_bp` は各分岐点の周囲 $(2r+1)$ 正方近傍（$r$ =
`remove_size` = 1）を消去し、交差でスケルトンを切断して、残る各成分が
分岐の無い 1 本の線になるようにする。`min_area` = 10 px 未満の成分は捨てる。
続く `imp_tools.remove_Lcorner` が、偽の折れとして登録されかねない 2 画素の
L 字コーナーアーティファクトを除去する。

各連結成分は `imp_tools.tracking` が端から端まで追跡し、片方の端点からもう
一方へ歩いて画素座標を**順序どおりに**返す。端点がちょうど 2 個でない成分は
追跡できないため、画像全体を中断せず、ログに記録してスキップする。

`imp_tools.remove_Lcorner` のパターンでは、1 のセルはスケルトン、0 のセルは
背景でなければならない。したがって除去されるのは、2 本の腕が直交方向の隣接
画素である L 字の角の画素であり、L 字は斜めの段差になる。`imp_tools.tracking`
はラスタ順で先に来る端点から出発し、各ステップで 3×3 窓のラスタ順で最初に
残っている隣接画素へ進み、離れる画素を消去する。

```python
# source: lib/imp_tools.py::remove_bp
bp = branchedPoints(imgcopy)
bp_coor = np.where(bp)
for bp_x, bp_y in zip(bp_coor[0], bp_coor[1]):
    imgcopy[
    max(int(bp_x) - remove_size, 0): bp_x + remove_size + 1,
    max(int(bp_y) - remove_size, 0): bp_y + remove_size + 1,
    ] = 0
if min_area != 0:
    tmp_nlabels, tmp_label_image = cv2.connectedComponents(np.uint8(imgcopy))
    sizes = np.bincount(tmp_label_image.ravel())
    small_mask = sizes < min_area
    small_mask[0] = False
    imgcopy[small_mask[tmp_label_image]] = 0
```

```python
# source: lib/imp_tools.py::remove_Lcorner
corner = np.array([[0, 1, 0],
                   [1, 1, 0],
                   [0, 0, 0]])
...
for corner_pattern in [corner, corner2, corner3, corner4]:
    h = cv2.morphologyEx(src, cv2.MORPH_HITMISS, _to_cv2_hitmiss_kernel(corner_pattern))
    hits += np.where(h > 0, 1, 0).astype(np.uint8)
Lremoved_img = imgcopy - hits
```

```python
# source: lib/imp_tools.py::tracking
ep = endPoints(imgcopy)
ep_y, ep_x = np.where(ep)
if len(ep_y) != 2:
    raise ValueError(
        "tracking requires exactly 2 endpoints; "
        f"detected {len(ep_y)} endpoint(s)"
    )
...
for i in range(np.sum(imgcopy)):
    imgcopy[y, x] = 0
    window = imgcopy[y - 1: y + 2, x - 1: x + 2]
    direction_y, direction_x = np.where(window != 0)
    if len(direction_y) == 0:
        break
    dy = int(direction_y[0]) - 1
    dx = int(direction_x[0]) - 1
    y += dy
    x += dx
    xtrack.append(x)
    ytrack.append(y)
    if x == ep_x_end and y == ep_y_end:
        break
```

キンク検出——および同じ追跡経路を共有する高さサンプリング——が分岐点近傍を
除外しているのはこのためである。交差部の高さはどの 1 本の繊維にも属さない。

### 4.2 繊維の線を高さの上に置く

**コード:** `lib/centerline.py` — `centerline.half_max_centerline`。

追跡したスケルトンは、どの画素が 1 本の繊維をなし、どの順に並ぶかを決めるが、
繊維が*どこを*通るかの推定としては不十分である。スケルトンは二値化マスクの
medial axis であり、2 本のマスク境界の中間を通る。近傍物・分岐部の裾・背景の
凹凸がマスクを片側に広げると軸はそれに従い、さらに 8 連結の画素鎖が階段を
上乗せする。その画素の上で判定すると、マスクがたまたま広がっただけのまっすぐな
繊維が折れを報告する。同梱の高等植物 TOC スキャンの Y 字の下では、スケルトンが
折れていない繊維に 118 度の「キンク」を生んだ。

そこで各スケルトン点を繊維の高さの上へ移す。

1. `centerline.measure_apparent_width` が繊維の見かけ幅 $W$ を測る。トラックに
   沿った高さ断面の半値全幅の、トラック全体での中央値である。以下の長さはすべて
   $W$ の倍数なので、この処理はどの走査サイズでも同じ意味を持つ。
2. $W/4$ で平滑化したトラックのコピーが、各点の動ける方向、すなわち繊維の
   法線を与える。点そのものを平滑化位置へ動かすことは決してない。そうすると
   本物のコーナーが丸まるためである。
3. `centerline.refine_centerline` はその法線に沿って、トラックから高さの最寄りの
   極大へ坂を上る。射程内で最も明るい点へではないため、より明るい隣の繊維に線を
   奪われない。そして点を、**断面が最大値の半分まで下がる 2 つの位置の中点**に
   置く。
4. この 1 本の繊維の位置を決められない断面——分岐点から $W$ 以内、断面幅が
   $1.5\,W$ を超える（2 本が並んでいる）、見つけた極大がトラックの載る断面の
   ものでない、断面が弱すぎる——は信頼できないと印を付け、そのオフセットは測らず
   に周囲の信頼できる点から補間する。オフセットは $W/4$ の一次罰則でトラックに
   沿ってつなぐ。

この計算の各手順は、コードとともに [GUI04 のファイバー計測](gui04_measurements.ja.md)
§2 で説明している。キンク検出も同じ関数を呼ぶ。

```python
# source: lib/centerline.py::place_centerline
width, measured = measure_apparent_width(height, x, y, return_measured=True)
lx, ly, reliable, crest = _refine(height, x, y, width, branch_points)
return CenterlineResult(lx, ly, float(width), bool(measured), reliable, crest)
```

結果はスケルトン点ごとにちょうど 1 点を持つ。これにより、線上で判定したキンクを
バンドルのスケルトン画素に保存でき、描画・計測にはすべて線を使いながら、除外と
連結は引き続きスケルトン画素を参照できる。

**線を置くときに併せて報告するもの。** `centerline.place_centerline` は線と
ともに、その上に組み立てる数値が依存する 3 つのものを
`centerline.CenterlineResult` として返す。

- **$W$ と、それが測定値かどうか。** キンク規則の長さはすべて $W$ の倍数であり、
  $W$ は繊維の幅であると同時に探針による広がりでもある。したがって $W$ は、その
  繊維のキンクを判定した物理尺度である。使える半値区間を持つ断面が少なすぎる
  ときは `centerline.FALLBACK_WIDTH_PX`（8 px）を代用するが、これは繊維の幅の
  倍数ではなく画素数なので、代用したことを隠さず報告する。各繊維は自身の $W$
  （`Fiber.width_px`、`Fiber.width_measured`）をファイバー一覧と CSV へ運び、
  バンドルは画像の $W$ の中央値と代替値を使った成分数を記録する
  （`bundle_schema.APPARENT_WIDTH_KEY`）。
- **どの点を位置決めできたか。** 手順 4 で補間された点は直線区間の上にあり、
  そこにキンクも曲率も見つからない。点ごとのフラグ（`Fiber.line_reliable`）は、
  線のうち実際に繊維上で位置決めできた割合として一覧と CSV に届く。
- **頂点高さ。** 各点での繊維の高さは、線の位置で補間した画像値ではなく**断面の
  最大値**（`CenterlineResult.crest`）である。線は半値中点にあり、非対称な断面
  では頂部の上ではなく脇に来るうえ、双線形補間は画素中心の間にある頂点に届か
  ない。断面を決められなかった点では、補間された点から $W/4$ 以内の最大値を
  使う。`Fiber.height`、高さプロファイル、すべての高さ統計はこの頂点高さを読む。

**なぜ 1/4 幅か。** 平滑化の尺度は、2 つの特徴がどこまで近づくと線がそれらを
1 つに平均してしまうかを決める。半幅では、線は近接したコーナーを丸めた。
コーナー位置が既知の合成スキャン（画素 2 nm、$W$ = 8 px）では、数幅離れた同じ
向きの 60 度コーナー 2 つを、§4.3 のキンク規則が 16 例中 2 例で 1 つの折れと
判定し、コーナー頂点から線までの距離の中央値は 1.10〜1.51 px であった。1/4 幅
では 1 つにまとめられた組は無く、その距離は 0.77〜1.21 px に下がった。真の
中心線までの距離の中央値は 0.11 px のままであった。

**なぜ半値中点か。** 自明な代替である各断面の頂点は、ねじれたフィブリルで最も
大きくずれる推定量である。断面が異方性のフィブリルは、ねじれに伴って最も高い縁を
交互の側に向ける。合成のねじれリボン（直線軸上の 4×2〜16×3 nm の長方形断面）では、
頂点は半値中点の 1.2〜1.8 倍軸から離れ、§4.3 のキンク規則はそうしたリボン 6 本の
いずれにもキンクを報告しなかった。1/4 高さの中点はリボンでは軸により近かったが、
細く低い繊維では、半値のレベルが上回っている背景の凹凸に最大 3.8 nm 引かれた。
探針が太い場合、ねじれたフィブリルのずれは画像そのものに入っており、高さから読む
どの線でも取り除けない。

球状の探針で描画した合成スキャン 60 枚（画素 2 nm、$W$ = 8 px。コーナー・
ジグザグ・コーナーの 2 連・円弧・蛇行・交差・分岐）の解析的中心線に対し、真の
中心線までの距離の中央値はこの線で 0.11 px、スケルトンで 0.29 px、95 パーセン
タイルはそれぞれ 0.35 px と 0.90 px である。この線に沿って測った輪郭長は、それら
のスキャンのどの群でも真の長さの −1.5〜+0.5 % に収まり、スケルトンの補正済み
チェーンコード長では −1.4〜+2.5 % であった。

GUI01 がキンクを判定するときと、バンドルを開くとき
（`fiber_tracking_image.FiberTrackingImage`）とで同じ関数が線を作るため、表示される
キンクとそれが載る線は 1 つの計算から来る。形式 1.0 のバンドルはスケルトン上で
判定されており、再解析されるまでスケルトントラック上に組み立てる
（`bundle_schema.centerline_from_meta`）。

### 4.3 各折れを超過回転で判定する

**コード:** `KinkDetector.judge_line`（`KinkDetector.kinks_on_line` はその
タプル形式）。

規則は線の向き $\theta(s)$ を扱う。弧長 $s$ の 0.5 px ごとに再サンプリングし、
$\sigma = W/4$ のガウスで平滑化する（`kink_detector._heading_profile`）。位置 $p$
では、窓の内側の回転を、そのすぐ外側での繊維自身の回転と比べる。

$$
T(p) = \theta(p + c) - \theta(p - c), \qquad c = 0.75\,W
$$

$$
r_{\text{L}} = \frac{\theta(p - c) - \theta(p - c - f)}{f}, \qquad
r_{\text{R}} = \frac{\theta(p + c + f) - \theta(p + c)}{f}, \qquad f = W
$$

$$
E(p) = |T(p)| - 2c \, \max\bigl(0,\ \min(\sigma_T r_{\text{L}},\ \sigma_T r_{\text{R}})\bigr),
\qquad \sigma_T = \operatorname{sgn} T(p)
$$

$E$ が**超過回転**である。窓の中の回転のうち、脇で繊維がすでに回っていた率を
超えた分を表す。折れは

$$
E \ge 180^\circ - \theta_{\text{max}}
$$

のときキンクとする。$\theta_{\text{max}}$ は `kinkangle_deg`、既定 150 度なので、
既定では 30 度の超過回転を要求する。しきい値を内角で書くのは、以前の規則での
`kinkangle_deg` の意味を保つためであり、`pipeline.build_stages` が検出器向けに
ラジアンへ変換する。キンクとして*保存する*角度はこれとは別に、腕から測る
（下の「報告する角度」参照）。

コードでは、`_heading_profile` が向きを再サンプリングし、差分を取り、平滑化
する。`excess_profile` は任意の位置で $T$ と $E$ を評価する。端の近くでは脇の区間
が線の範囲に切り詰められるが、割る数は $f$ のままである。位置 $p$ を採用するのは、
両端から $c$ 以上離れていて、$|T(p)|$ がしきい値に達し、かつ $E(p)$ がしきい値と
ノイズ床の両方に達する場合だけである（`NOISE_SIGMAS` が 0 の間、ノイズ床は 0）。
しきい値はラジアンで $\pi - \theta_{\text{max}}$（`turn_threshold`）である。

```python
# source: lib/kink_detector.py::_CORE_WIDTHS, _FLANK_WIDTHS, _HEADING_SIGMA_WIDTHS
_CORE_WIDTHS = 0.75
_FLANK_WIDTHS = 1.0
_HEADING_SIGMA_WIDTHS = 0.25
```

```python
# source: lib/kink_detector.py::_heading_profile
seg = np.hypot(np.diff(x), np.diff(y))
keep = np.concatenate([[True], seg > 1e-9])
orig = np.nonzero(keep)[0]
x, y = x[keep], y[keep]
if x.size < 2:
    return None
s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
length = float(s[-1])
su = np.arange(0.0, length + 1e-9, _HEADING_STEP_PX)
if su.size < 2:
    return None
xu = np.interp(su, s, x)
yu = np.interp(su, s, y)
theta = np.unwrap(np.arctan2(np.diff(yu), np.diff(xu)))
sm = su[:-1] + 0.5 * _HEADING_STEP_PX
heading = _smooth_extrapolated(
    theta, _HEADING_SIGMA_WIDTHS * width / _HEADING_STEP_PX,
)
return orig, s, length, sm, heading
```

```python
# source: lib/kink_detector.py::KinkDetector.judge_line
width = float(width_px)
c = _CORE_WIDTHS * width
f = _FLANK_WIDTHS * width
profile = _heading_profile(x, y, width)
...
turn_threshold = max(np.pi - float(self.threshold_angle_from_decomposed_indices), 0.0)
curvature = np.abs(np.gradient(heading, _HEADING_STEP_PX))
curvature_floor = _CURVATURE_FLOOR_FRAC * turn_threshold / (2.0 * c)
radius = _SUPPRESS_WIDTHS * width
def excess_profile(p: NDArray) -> Tuple[NDArray, NDArray]:
    core = np.interp(p + c, sm, heading) - np.interp(p - c, sm, heading)
    sense = np.sign(core)
    left = (np.interp(p - c, sm, heading)
            - np.interp(np.maximum(sm[0], p - c - f), sm, heading)) / f
    right = (np.interp(np.minimum(sm[-1], p + c + f), sm, heading)
             - np.interp(p + c, sm, heading)) / f
    background = np.maximum(0.0, np.minimum(sense * left, sense * right))
    return core, np.abs(core) - 2.0 * c * background
grid = sm[(sm >= c) & (sm <= length - c)]
...
def excess_at(p: float) -> Optional[float]:
    if p < c or p > length - c:
        return None
    core, excess = excess_profile(np.array([p]))
    if abs(float(core[0])) < turn_threshold:
        return None
    excess = float(excess[0])
    return excess if excess >= max(turn_threshold, floor) else None
```

**なぜ回転ではなく超過か。** 窓の回転だけでは、キンクだけでなく曲率も報告して
しまう。半径 $3\,W$ の円弧は $1.5\,W$ の間に既に 29 度回る。円弧は窓の中でも
両脇でも同じ率で回るため超過はほぼ 0 になり、まっすぐな腕に挟まれたコーナーは
回転をすべて残す。両脇の率の*小さい方*を使うのは、曲線の終わりにあるコーナー
では脇の一方が曲がり、もう一方がまっすぐであり、それでもコーナーはコーナー
だからである。逆向きに回る脇（段差の 2 つ目の折れ）は背景に何も寄与しない。

**候補。** $E$ は、曲率 $|d\theta/ds|$ の極大のうち、しきい値ちょうどの折れが窓
全体で持つ平均曲率の半分に達するものの位置で評価する。ノイズで曲率のピークが
2 つに割れたコーナーや、回転がそのまま曲線へ続くコーナーは、中心に曲率の極大を
1 つも持たない。そのため、$0.75\,W$ 以内に曲率の極大が通過していない場所では
$|T|$ そのものの極大も加える。同梱スキャンでは、これが無いと目に見えるコーナーを
2 件見落とした。$0.75\,W$ より近い候補は 1 つの折れとし、超過回転の大きい方を
残す。

曲率の下限は $0.5 \times (\pi - \theta_{\text{max}}) / (2c)$
（`_CURVATURE_FLOOR_FRAC` = 0.5）である。$|T|$ の極大は両端から $c$ 以上離れた
サンプル（`grid`）の上で探し、抑制は超過回転の大きい順に候補を残す。

```python
# source: lib/kink_detector.py::KinkDetector.judge_line
fine: List[Tuple[float, float]] = []
for i in range(1, curvature.size - 1):
    if (curvature[i] >= curvature[i - 1] and curvature[i] > curvature[i + 1]
            and curvature[i] >= curvature_floor):
        excess = excess_at(float(sm[i]))
        if excess is not None:
            fine.append((excess, float(sm[i])))
coarse: List[Tuple[float, float]] = []
if grid.size >= 3:
    window_turn = np.abs(np.interp(grid + c, sm, heading)
                         - np.interp(grid - c, sm, heading))
    for i in range(1, grid.size - 1):
        if (window_turn[i] >= window_turn[i - 1]
                and window_turn[i] > window_turn[i + 1]
                and window_turn[i] >= turn_threshold):
            p = float(grid[i])
            excess = excess_at(p)
            if excess is not None and all(abs(p - q) > radius for _, q in fine):
                coarse.append((excess, p))
kept: List[Tuple[float, float]] = []
for excess, p in sorted(fine + coarse, key=lambda t: -t[0]):
    if all(abs(p - q) > radius for _, q in kept):
        kept.append((excess, p))
```

**尺度。** 規則の長さはすべて $W$ の倍数であり、$W$ は画像の分解能でもある。
探針はどの繊維も約 $W$ に広げるため、繊維自体がどれほど鋭く曲がってもコーナーは
線の上で約 $W$ を占め、それよりずっと近い 2 つの折れは見分けられない。合成
ジグザグ（画素 2 nm、$W$ = 8 px）では、1.5〜3 $W$ 離れたコーナーはすべて見つかり
（30 件中 30 件）、1 $W$ 離れたコーナーは 10 件中 4 件だった。規則には画素数で
決まる量が無いため、同じ繊維を別の画素サイズで走査しても同じキンクが得られる。
`kink_decompose_px` はもう使わない（§4.6）。

**何を報告し、どれほど確かか。** 同梱スキャンの高さ画像に、検出器の出力を一切
表示せずに目視で印を付けた基準（5 スキャンで明瞭なキンク 64 件）に対し、この
規則は 60 件を見つけ、1 件を印から 1〜2 幅の位置に置き、3 件を見落とし、どの印
とも一致しない折れを 60 件報告した。置き換えた折れ線規則はスケルトントラック上
で、53 件を見つけ、5 件をずらし、6 件を見落とし、79 件を報告した。合成スキャン
では、直線の繊維、半径 3〜10 $W$ の円弧、交差、分岐、ねじれリボンには折れを 1 つ
も報告せず、40 度以上の孤立コーナーはすべて見つけた。最も小さい曲率半径が
1.6〜1.8 $W$ の正弦波状の蛇行では 12 件の折れを報告した。半径が約 $2.9\,W$ を
下回ると窓だけで 30 度を超えて回り、曲率が速く変わる場所では脇がそれを説明
しきれないためである。折れ線規則は同じ円弧と蛇行で 31 件を報告した。規則の長さ
のどれか 1 つを隣の値（$c$ = 0.6 または 0.9 $W$、$f$ = 0.75 または 1.5 $W$、向きの
平滑化 0.15 または 0.35 $W$、§4.4 の端の範囲 1.0 または 2.0 $W$、抑制半径 0.5
または 1.0 $W$）に変えても、見つかる明瞭なキンクは 59〜62 件にとどまった。

**報告する角度。** 検定する量は超過回転であり、探針と線が頂点を丸めるため、
鋭いコーナーでは低めに読む。40 度・60 度・90 度・120 度回る孤立した合成
コーナーの超過回転は、それぞれ 37〜38 度、52〜56 度、83〜84 度、101〜110 度と
読まれた。そのため、しきい値をわずかに上回る折れが下回ることがある。テスト
スイートで 33.5 度に描いた折れは 28.7 度と読まれる。したがって*保存する*角度
（`ka`）は、180° から超過回転を引いた値ではなく、折れの両脇の 2 本の**腕**の
なす内角である（`KinkDetector.judge_line`）。各腕の向きは、頂点
から半幅先（丸めの外側）から始まる 1 幅の区間にわたる向きの平均で、段差の
2 つ目のコーナーが 1 つ目の腕に入らないよう次の折れの手前で打ち切る。10 nm の
探針で描画した内角 120・140・145 度の合成コーナー（`scripts/kink_rule_sweep.py`）
では、腕の角度の誤差の中央値は見かけ幅 5.5 px で 1.9 度、11 px で 1.1 度であり、
180° から超過回転を引いた値では 7.5 度と 2.5 度であった。超過回転は角度の隣に
`ke` として保存し（§4.5）、検定した量と幾何の両方がバンドルとともに移動する。

**腕の角度の計算方法。** 長さ $L$ の線上の弧長位置 $p$ にある折れについて、
$g = 0.5\,W$（`_ARM_GAP_WIDTHS`）、$a = 1.0\,W$（`_ARM_LENGTH_WIDTHS`）と
すると、2 本の腕は弧長の区間

$$
A_{\text{L}} = \bigl[\max(s_0,\ p - g - a,\ p_{\text{prev}} + g),\ p - g\bigr],
\qquad
A_{\text{R}} = \bigl[p + g,\ \min(s_1,\ p + g + a,\ p_{\text{next}} - g)\bigr]
$$

である。$s_0$ と $s_1$ は最初と最後の向きのサンプルの位置（始端から 0.25 px、
終端から 0.25〜0.75 px 内側）、
$p_{\text{prev}}$ と $p_{\text{next}}$ はその線上に残した最寄りの他の折れ
（判定したかどうかを問わない）で、無ければ省く。各腕の向き $\bar\theta$ は、
区間内の等間隔な 16 点で平滑化した向きを標本化した平均であり、内角は

$$
\phi = \max\bigl(0,\ \pi - |\bar\theta_{\text{R}} - \bar\theta_{\text{L}}|\bigr)
$$

である。どちらかの区間が $0.25\,W$（`_ARM_MIN_WIDTHS`）より短い場合——2 つの折れが
近すぎて間に腕が残らない場合——は、代わりに $\phi = \pi - E$ を保存する。角度は
その後 $[10^{-6},\ \pi - 10^{-6}]$ rad にクリップし、弧長で $p$ に最も近い線の点に、
ラジアンで `ka` として書き込む。2 つの折れが同じ点に落ちた場合は、超過回転の
大きい方を残す。折れがキンクかどうかを決めるのは角度ではなく $E$ なので、保存
された角度が `kinkangle_deg` 以下になる保証はない。

`measure.compute_fiber_stats` は角度を度へ変換し（`FiberStats.kink_angles_deg`）、
ファイバー CSV にはこれが入る。`measure.fiber_kink_angle` はその中央値を、GUI03 が
ヒストグラムにするファイバーごとの 1 つの値とする。

```python
# source: lib/kink_detector.py::_ARM_GAP_WIDTHS, _ARM_LENGTH_WIDTHS, _ARM_MIN_WIDTHS
_ARM_GAP_WIDTHS = 0.5
_ARM_LENGTH_WIDTHS = 1.0
_ARM_MIN_WIDTHS = 0.25
```

```python
# source: lib/kink_detector.py::_arm_interior_angle
gap = _ARM_GAP_WIDTHS * width
arm = _ARM_LENGTH_WIDTHS * width
left_lo = max(float(sm[0]), p - gap - arm)
if prev_bend is not None:
    left_lo = max(left_lo, prev_bend + gap)
left_hi = p - gap
right_lo = p + gap
right_hi = min(float(sm[-1]), p + gap + arm)
if next_bend is not None:
    right_hi = min(right_hi, next_bend - gap)
shortest = _ARM_MIN_WIDTHS * width
if left_hi - left_lo < shortest or right_hi - right_lo < shortest:
    return float("nan")
def mean_heading(lo: float, hi: float) -> float:
    return float(np.mean(np.interp(np.linspace(lo, hi, 16), sm, heading)))
turn = abs(mean_heading(right_lo, right_hi) - mean_heading(left_lo, left_hi))
return max(np.pi - turn, 0.0)
```

```python
# source: lib/kink_detector.py::KinkDetector.judge_line
margin = END_MARGIN_WIDTHS * width
positions = sorted(q for _, q in kept)
...
for excess, p in kept:
    index = int(orig[int(np.argmin(np.abs(s - p)))])
    if index in taken:
        continue
    taken.add(index)
    if margin <= p <= length - margin:
        before = [q for q in positions if q < p]
        after = [q for q in positions if q > p]
        angle = _arm_interior_angle(
            sm, heading, p, width,
            max(before) if before else None,
            min(after) if after else None,
        )
        if not np.isfinite(angle):
            angle = np.pi - excess
        kinks.append((index, angle, excess))
    else:
        unjudged.append(index)
kinks.sort()
kink_indices = np.array([k for k, _, _ in kinks], dtype=np.intp)
kink_angles = np.clip(
    np.array([a for _, a, _ in kinks], dtype=np.float64),
    _MIN_INTERIOR_ANGLE, np.pi - _MIN_INTERIOR_ANGLE,
)
kink_excess = np.array([e for _, _, e in kinks], dtype=np.float64)
```

```python
# source: lib/measure.py::compute_fiber_stats
angles = tuple(float(np.degrees(a)) for a in f.kink_angles)
```

```python
# source: lib/measure.py::fiber_kink_angle
if not stat.kink_angles_deg:
    return float("nan")
return float(np.median(stat.kink_angles_deg))
```

**線自身のノイズに対する有意性。** 線ごとのノイズ床を実装している
（`NOISE_SIGMAS`、`KinkJudgement.noise_excess`）。線全体にわたる超過回転の
ロバストな尺度で、折れの超過回転はそのある倍数を超えなければならない、という
ものである。これは既定で**無効**にしている。誤検出と本物のキンクを分けなかった
ためである。目視基準に対して採点すると（`scripts/kink_reference_score.py`）、
倍数 3 では誤検出が 6 件減る一方で明瞭なキンクの検出が 3 件減り、倍数 4 では
10 件に対して 5 件減った。これらのスキャンの誤検出は、丸い曲がり・絡まり・
25〜40 度の折れであってノイズではなく、また強く折れ曲がった繊維では自身のキンクが
床を押し上げる。失われた明瞭なキンクはそこにあった。合成データの掃引では、最も
細かい画素サイズと最も強いノイズの条件（幅 11 px、画素ノイズ 0.30 nm）を除いて
何も変わらず、その条件でも 1 µm あたりの偽陽性を 3.9 から 3.1 に減らしただけで、
すでに失われていた再現率は戻らなかった。

**規則が適用できる範囲。** 同じ掃引が、規則がどの幅で働くかを示す。見かけ幅
3 px 以上では、合成の 120 度と 145 度のコーナーはすべて見つかり（140 度は
3 px で 6 件中 4 件、5.5 px 以上ではすべて）、画素ノイズ 0.15 nm までの直線・
円弧・蛇行に偽陽性は無く、165 度の曲がりにも無かった。幅がわずか 2 px の繊維では
幅そのものが測れず代替値が適用され、何も見つからなかった。約 3 px 未満では画像が
繊維の折れをもう分解しておらず、答えは規則を緩めることではなく、より細かい画素
サイズで走査することである。

### 4.4 端のそばの折れは判定せずに示す

線の端から $1.5\,W$ 以内に中心がある折れは**判定しない**。そのとき片方の腕は、
目視基準が折れを明瞭と呼ぶのに要した長さに満たない。またトラック端の多くは繊維の
終端ではなく交差での切断であり（同梱スキャンの実測では、トラック端の 46〜68 % が
分岐点から 3 px 以内にある）、そこでは線が分岐部の裾とともに曲がる。

こうした折れは黙って捨てない。`KinkDetector.kinks_on_line` はそれを別に返し、
バンドルは任意キー `up` に保存し、各繊維には `Fiber.unjudged_indices` として届き、
GUI04 は灰色の中空の円で描く。これにより「判定しなかった」と「測ってしきい値
未満だった」を見分けられる。数には一切入れない。キンク数・密度・角度・CSV は
判定したキンクだけを持つ。再結合したフィブリルが切断を橋渡しすれば、その折れは
もう端のそばにないので判定される。連結処理と
`fiber_connector.filter_fibers_by_height` は、組み立てる繊維を同じ規則で作り直す
ためである。

端の範囲を $1.0\,W$ にすると、同梱スキャンの誤検出は、明瞭なキンクを 1 件も
増やさずに 60 件から 75 件に増えた。$2.0\,W$ では 47 件に減ったが、端から
1.5〜2 $W$ の合成コーナーを判定しなくなった。同梱スキャンで判定しなかった 49 件の
折れのうち、明瞭な基準キンクの上にあるものは無かった。

### 4.5 しきい値は結果とともに移動する

キンクパラメータはバンドルの `params` メタデータへ書き込まれ、
`bundle_schema.kink_params_from_meta` が読み戻す。読み手が実際に*作用*する解析
フィールドは `kinkangle_deg` であり、そうでなければならない。バンドルが保持して
いないトラック——交差をまたいで連結した繊維、高さ帯で切り出した部分繊維——に
対してキンクを再計算するものは、保存済みキンク点を生んだのと同じ規則を適用
しなければならず、その規則が説明対象の配列と一緒に移動する場所はバンドル以外に
無い。`kink_decompose_px` も読み戻すが、使うのは形式 1.0 のバンドルだけである
（§4.6）。

これらを `_param.json` サイドカーから読まないのは意図的である。あのファイル
は解析の*入力*であり、事後に編集可能なので、そこを読むと編集ひとつで再解析
なしに連結繊維のキンクが変わってしまう。

バンドルは各キンクの角度 `ka` の隣に、それを判定した超過回転（`ke`、
`KinkJudgement.kink_excess`）も保存する。角度は折れの幾何であり、超過回転は
規則が検定した量である。両方を持つことで、規則を走らせ直さずにキンクをしきい値
に対して監査できる。

### 4.6 以前の規則で判定されたバンドル

形式 1.0 のバンドルは、スケルトントラック上で以前の規則により判定されている。
`KinkDetector._binary_decompose_simple` が **Douglas–Peucker** 法の考え方で
トラックを折れ線に縮約し、弦から `kink_decompose_px`（既定 3.0 px）以上離れた
トラック点に頂点を挿入した。`KinkDetector._detect_kink_from_decomposed_indices`
は、内角 $\theta$ が `kinkangle_deg` 以下で、直線からの不足が、頂点の許容量 $d$
が長さ $A$ の腕に与える誤差棒を上回る頂点を残した。

$$
\pi - \theta > \frac{2d}{\min(A_{\text{prev}},\, A_{\text{next}})}
$$

その規則は画素の許容量のほかに尺度を持たなかったため、滑らかな円弧を頂点に分割
してキンクとして報告し、またスケルトンを判定していたため、階段状の画素鎖や幅の
広い箇所での振れという、繊維自体には無い折れを報告した。1.0 のバンドルは再解析
されるまでスケルトントラックと保存済みキンクを保ち
（`bundle_schema.centerline_from_meta`）、その中で再結合したフィブリルはその規則で
判定する（`KinkDetector.kinks_and_decomposed_from_track`）。これにより、1 枚の画像
に 2 つの規則のキンクが混在することはない。

コードでは、折れ線は両端の 2 点から始まり、いずれかの弦から最も遠いトラック点を
繰り返し加えて、すべての点が `threshold_distance`（`kink_decompose_px`）以内に
収まるまで続ける。その後、各内部頂点の角度を検定する。

```python
# source: lib/kink_detector.py::KinkDetector._binary_decompose_simple
decomposed_indices = [0, n_pts - 1]
updated = True
while updated:
    updated = False
    for n, (i, j) in enumerate(zip(decomposed_indices[:-1], decomposed_indices[1:])):
        if j - i < 2:
            continue
        ax = cx[i]; ay = cy[i]
        bx = cx[j]; by = cy[j]
        abx = bx - ax
        aby = by - ay
        length_ab = (abx * abx + aby * aby) ** 0.5
        if length_ab == 0.0:
            continue
        xs = cx[i + 1:j]
        ys = cy[i + 1:j]
        dist = np.abs(abx * (ys - ay) - aby * (xs - ax)) / length_ab
        k = int(dist.argmax())
        farthest_distance = dist[k]
        if farthest_distance == 0:
            continue
        elif farthest_distance >= threshold_distance:
            added_indices = [k + i + 1]
            decomposed_indices = decomposed_indices[:n + 1] + added_indices + decomposed_indices[n + 1:]
            updated = True
            break
```

```python
# source: lib/kink_detector.py::KinkDetector._detect_kink_from_decomposed_indices
v1x = cx[prev_idx] - cx[mid_idx]
v1y = cy[prev_idx] - cy[mid_idx]
v2x = cx[next_idx] - cx[mid_idx]
v2y = cy[next_idx] - cy[mid_idx]
dot = v1x * v2x + v1y * v2y
norm1 = np.sqrt(v1x ** 2 + v1y ** 2)
norm2 = np.sqrt(v2x ** 2 + v2y ** 2)
angles = np.arccos(dot / (norm1 * norm2))
mask = angles <= threshold_angle
arm = np.minimum(norm1, norm2)
with np.errstate(divide="ignore", invalid="ignore"):
    angular_error = np.where(arm > 0.0,
                             2.0 * self.threshold_distance / arm,
                             np.inf)
mask &= (np.pi - angles) > angular_error
return mid_idx[mask], angles[mask]
```

---

## 5. これらの段が意図的に行わないこと

以上の処理が生むのは配列である。配列を数値に変える作業は別の場所にあり、
その境界を明確に保つことが、画像を再解析せずに計測をやり直せる理由である。

- **繊維ごとの計測**——輪郭長、高さ統計、直線性、曲率、キンク密度——は
  `lib/measure.py` にあり、GUI03、GUI04、`cli.py measure` が共有する。どの繊維も
  §4.2 の線に沿って読み、その線はバンドルを開くときに
  `fiber_tracking_image.FiberTrackingImage` が保存済みのスケルトンと高さから
  作り直す。その定義のうち 2 つは、線だけでなく上記の段から従う。高さ統計は
  §4.2 の頂点高さについて取り、繊維端ではなく切断である端の最後の $W$ を外す
  （`measure.height_sample_mask`）。§4.1 が消すのは分岐点周りの 3×3 だけだが、
  交差での相手繊維の裾はその先 1 幅ほど広がるため、それらの標本は一部が相手の
  繊維の高さである。中央値はほとんど気付かないが、最大値は交差を読んでしまう。
  連結器が補間する橋渡しも同じ理由で外す。またキンク密度
  （`measure.fiber_kink_density`）は**判定した**長さ、すなわち輪郭から両端の
  $1.5\,W$ を引いたもので割る。§4.4 はそれより端に近い折れを判定しないためで
  ある。輪郭全体で割ると低く読み、端の大半が切断で断片が短い密な試料ほど
  その偏りは大きかった。
- 交差で分割された**断片の再連結**は `lib/fiber_connector.py` にあり、探索を
  実行するのは GUI04 だけである。他の読み手は、その探索が記録した連結情報を
  適用する。
- **手動除外**は `lib/fiber_selection.py` にある。
- **画素サイズ**は計測時にのみ関与する。上記の各段はすべて画素基準であり、
  だからこそ走査サイズが記録されているかどうかに関わらず、段のパラメータは
  同じ意味を持つ。この選択の裏面として、同じパラメータファイルは走査サイズごと
  に異なる物理尺度で働く。12 px のスパー上限は 2 µm 走査では約 23 nm、10 µm
  走査では約 117 nm を刈る。そのため走査サイズが既知なら、バンドルは各画素設定
  が何 nm にあたったかを記録し（`bundle_schema.PIXEL_LENGTHS_KEY`、
  `pipeline.pixel_lengths_nm` による）、GUI01 はそれをログに出す。これが、その点で
  2 つのバンドルを比較可能にする。

## 6. 結果を再現する

このソフトウェアが報告する数値は、3 つの成果物によって一意に定まる。

| 成果物 | 記録する内容 |
|---|---|
| `<stem>_param.json` | 解析が使用した全 `ProcParams` フィールド。フィールド名は凍結されているため、古いファイルも読み込める。 |
| `<stem>.b2z` | 各段の出力配列、バンドル形式バージョン、走査サイズとその出所、解析した走査線範囲、および来歴としてのパラメータ。 |
| ソフトウェアのバージョン | バンドルに記録される。`CHANGELOG.md` は数値が変わる変更を明示的に記載する。 |

解析出力を変える変更は再現性の破壊として扱われ、API の変更を伴うかどうかに
関わらず、導入されたバージョンの `CHANGELOG.md` に明記される。
