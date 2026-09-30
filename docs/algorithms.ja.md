# 解析アルゴリズム

このページは、前処理の 4<!--n:count--> 段階が実際に何をしているのか、各手順がソースの
どこにあるのかを説明する。図のキャプションに書く数値の根拠を自分で説明する
必要がある人に向けて、ソフトウェアが利用者に代わって下した判断、その根拠、
そしてその判断を変えるパラメータを示す。

API リファレンスが個々の関数の仕様を記述するのに対し、このページは関数どうし
をつなぐ考え方を記述する。

このページは個別のデータでの結果を載せない。同梱スキャンと合成データで各段が
何をしたか、いくつかの既定値をどの結果を見て選んだかは、
[個別データでの評価](validation.ja.md) にまとめてある。

## コード参照の読み方

コードは**シンボル名**で参照し、行番号では参照しない。行番号は無関係な編集が
1<!--n:count--> 回入るだけでずれるためである。たとえば `Segmenter._binaryzation` は
`lib/segmenter.py` 内の同名メソッドを、`bg_calibrator.BG_METHOD_NAMES` は
モジュールレベルの定数を指す。このページに出てくるシンボルはすべて、
`tests/test_algorithm_docs.py` がテストのたびにソースと照合する。リネームや
削除があればテストが失敗するので、記述が誤ったまま気付かれずに残ることはない。

各手順は、**それを実行するコードとともに**示す。ただし §4.2 の中心線の各手順は、
同じコードを [GUI04 のファイバー計測](gui04_measurements.ja.md) §2 が引用して
いるため、ここでは入口の関数だけを引用する。各コードブロックの先頭には、
出典を示すヘッダがある。

```text
# source: lib/segmenter.py::Segmenter._binaryzation
```

ヘッダは、コードが属するファイルと、関数・メソッド（`Class.method`）・
モジュール定数を表す。同じファイルの複数のシンボルをカンマ区切りで並べる
こともある。`...` だけの行は省略箇所を表し、コメント・空行・メソッドの字下げは
省いている。各コード片は、ヘッダに書いたシンボルと 1<!--n:count--> 行ずつ照合される
（`scripts/doc_excerpts.py`。`tests/test_algorithm_docs.py` と pre-commit
フックが実行する）。英語版と日本語版は同じコードを引用しなければならない。
したがって、引用したコードが実際に動くコードと食い違ったまま残ることはない。

同じテストは逆方向も検査する。アルゴリズムモジュール（4<!--n:count--> つの段と、キンクを
判定する中心線を置く `lib/centerline.py`）をコメントと docstring を除いて
ハッシュ化しているので、コードの計算内容が変わると、このページを見直すまで
テストが通らない。文書が記述対象のコードから気付かれずに離れていくことはない。

## 全体を通じた表記規則

| 量 | 単位 | 備考 |
|---|---|---|
| 高さ | ナノメートル (nm) | ローダが nm へ変換する。以下の高さしきい値はすべて**背景補正後**の画像における絶対 nm 値であり、基板が 0<!--n:definition--> nm に位置する前提である。 |
| 面内距離 | 各段では画素 (px)、結果では物理長（nm または µm） | 各段は意図的に画素基準であり、画素サイズは計測時にのみ関与する。例外は既定で無効のリッジ回収（§2.6）で、その設定値は nm である。 |
| 角度 | キンク判定の内部ではラジアン、パラメータファイルでは度 | `pipeline.build_stages` が `KinkDetector` 構築時に `kinkangle_deg` をラジアンへ変換する。 |
| 配列添字 | `image[row, column]` すなわち `[y, x]` | いくつかのヘルパーは `np.where` の出力を返し、最初の配列が行添字になる。 |

**1<!--n:definition--> 画素の切り詰め。** 背景補正は隣接画素間の 1<!--n:definition--> 次差分の上に構築されている
ため、出力は入力より各軸 1<!--n:definition--> 画素小さい。`BGCalibrator._bg_calibrate` は
`original[1:, 1:] - bg_sm` を返す。以降のすべての段はこの切り詰め済み配列を
扱う。したがって解析結果の画素 $(r, c)$ にある特徴は、生スキャンの画素
$(r+1, c+1)$ に対応する。

**パラメータ。** 以下に出てくる利用者設定値はすべて `pipeline.ProcParams`
のフィールドであり、各バンドルの隣に `<input_stem>_param.json` として保存
される。同じ値はバンドル自身にも来歴として書き込まれる（§4.5）。利用者が
変えられる設定はこれで全部だが、解析を再現するにはソフトウェアのバージョンも
要る（§6）。フック切除の角度（§3.6）などの内部定数はフィールドではなく、
バージョンとともに決まるためである。「既定値」
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
   3. Skeletonizer   ->  skeleton_image     (1 px 幅のスケルトン) + ep / bp
   4. KinkDetector   ->  スケルトン成分ごとのキンク点と角度
                         （その中心線上で判定。§4.2）
                                     |
                             .b2z バンドル + _param.json
```

`pipeline.process_file` がまさにこの順序を実行し、GUI01 と `cli.py process`
の両方がこれを呼ぶため、2<!--n:count--> つの入口が乖離することはない。ステージオブジェクト
は `pipeline.build_stages` が一度だけ構築する。

各段は前段が書いた結果を読み、それが無ければ段の境界ではっきり失敗する。
たとえば `Segmenter.__call__` は、`calibrated_image` が `None` なら、OpenCV の
内部で原因の分かりにくいエラーになる前に、その場で例外を送出する。

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
傾きとスキャナの皿状歪みを伴うことがある。

ここから 2<!--n:count--> つの帰結が導かれ、それがこの段全体の設計を決めている。

1. 後段のしきい値はすべて**nm の絶対高さ**である。基板が全域で 0<!--n:definition--> nm へ
   揃えられて初めて意味を持つ。
2. この傾きや歪みを再現できない背景推定の誤差は、そのまま補正後の高さの誤差と
   なり、後段のしきい値判定に入る。

### 1.2 3 方式に共通する処理の流れ

3<!--n:count--> 方式はいずれもおおむね次の骨格に沿う。以下の流れは `trendfill` そのものである。

```text
繊維画素を同定して背景プールから除外
    -> 平滑なトレンド曲面をフィットして減算        (デトレンド)
    -> 除外された画素を充填
    -> Savitzky-Golay 平滑化
    -> トレンド曲面を足し戻す                      (リトレンド)
    -> 元画像から減算
```

他の 2<!--n:count--> 方式は、この骨格から次の点で外れる。

- `tophat`（§1.4）は繊維画素を同定しない。トレンドは全画素でフィットし、充填
  の代わりにデトレンドした画像へ opening をかけ、最後に中央値で再センタリング
  する。
- `spline1d`（§1.5）は `trendfill` と同じマスクを使い、充填をラインごとの
  1<!--n:definition--> 次元スプラインで行う。さらに順序が異なり、トレンドを**先に**足し戻して
  から Savitzky–Golay で平滑化する。

さらに 3<!--n:count--> 方式とも、最後に任意の 3<!--n:literal in the quoted code-->×3<!--n:literal in the quoted code--> 中央値フィルタを適用する。`apply_median`
（既定は無効）で有効化でき、インパルス状の残留ノイズを抑える代わりに、最も
鋭い高さ特徴を鈍らせる。

充填の前にトレンドを除くのは、どの充填法にも試料の傾きや歪みを再現させずに
済ませるためである。フィットは `BGCalibrator._fit_trend_surface` が行う。

`_fit_trend_surface` は平面ではなく**2<!--n:definition--> 次曲面**をフィットする。実際の走査は
傾いているだけでなく皿状に歪んでいることがあるためである（§1.1）。2<!--n:definition--> 次項を作る前に座標を
$[-1, 1]$ へ正規化し、設計行列の条件数を良好に保つ。背景画素の配置が退化して
いる場合（たとえば全点が 1<!--n:count--> 行に載る場合）、`numpy.linalg.lstsq` はランク落ち
でも黙って解を返してしまうため、ランクを明示的に検査し、2<!--n:definition--> 次 → 平面 → 背景の
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

名前は動作そのものを表す。トレンドを引き、穴を埋める。旧綴り `inpaint` を記録
したパラメータファイルは、`bg_calibrator.BG_METHOD_ALIASES` が現在名へ変換する
ので、そのまま動作する。

`_call_trendfill` は以下の 3<!--n:count--> 手順を順に実行する。

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

`BGCalibrator._detect_fiber_mask` が 4<!--n:count--> つのヘルパーを順に実行する。

```python
# source: lib/bg_calibrator.py::BGCalibrator._detect_fiber_mask
self.dif_x, self.dif_y = self._difXY(original)
self.histx, self.histy, self.outx, self.outy = self._bg_fit(self.dif_x, self.dif_y)
self.tri_difx, self.tri_dify = self._dif_sep(self.dif_x, self.dif_y, self.outx, self.outy)
self.tri_difx_fill, self.tri_dify_fill = self._extract_fiber(self.tri_difx, self.tri_dify)
```

`_difXY` は各軸方向の 1<!--n:definition--> 次差分 $\Delta_x$、$\Delta_y$ を取る。絶対値の大きい
差分はエッジを示し、この試料では繊維の側面を意味する。

```python
# source: lib/bg_calibrator.py::BGCalibrator._difXY
dif_x = image[:, 1:] - image[:, 0:-1]
dif_y = image[1:, :] - image[0:-1, :]
return dif_x, dif_y
```

`_bg_fit` は各差分画像を 150<!--c:lib/bg_calibrator.py::BGCalibrator._bg_fit(bin_n)--> ビンのヒストグラムにし、`lmfit` で**ガウス関数
＋線形ベースライン**をフィットする。ガウス成分が*背景*集団、すなわちゼロ近傍
に中心を持つ基板のノイズである。繊維の側面は裾に現れる。X と Y を独立に
フィットするのは、AFM の低速走査軸がノイズ特性を異にし、$\sigma$ が広がり
やすいためである。

ガウス成分の中心と幅の初期値は、差分の中央値と頑健な幅（四分位範囲を 1.349<!--n:literal in the quoted code--> で割った値）
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
**3<!--n:definition--> 値マップ**へ変換する。

$$
\text{tri} = \begin{cases}
+1 & \Delta > \mu + f\sigma \\
0 & \text{それ以外} \\
-1 & \Delta < \mu - f\sigma
\end{cases}
$$

ここで $f$ が `threshold_factor`（既定 2.0<!--c:lib/pipeline.py::ProcParams.threshold_factor-->）である。すなわち $\pm 1$ は
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

続いて `_extract_fiber` が各行（X 用）と各列（Y 用）を走査し、3<!--n:definition--> 値マップを
ランレングス符号化して、走査線を横切るリッジが生む 2<!--n:count--> つの符号パターンを
探す。ただしループは `range(shape[0] - 1)` なので、X のマップの最後の行と
Y のマップの最後の列は走査されず、そこには繊維の印が付かない。

- **パターン 1<!--n:label--> — `[+1, 0, -1]`**: 側面を上り、頂上で平坦になり、反対側の
  側面を下る。平坦区間が `fiber_detect_factor`（既定 10<!--c:lib/pipeline.py::ProcParams.fiber_detect_factor-->）より短いとき採用
  する。つまり頂上が繊維とみなせる程度に狭い場合である。
- **パターン 2<!--n:label--> — `[+1, -1]`**: 平坦な頂上が分解されない鋭いリッジ。スパンが
  `noise_detect_factor`（既定 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor-->）を超えるとき採用する。この条件が、スパンが
  既定では 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor--> 画素以下の短い段差をノイズとして排除する。

パターンの外側境界の間にある画素がすべて繊維としてマークされる。X と Y の
結果は次の手順で和集合として統合される。

コードでは、`l_arr` が各ランの値を、`arg_arr` がそのランの開始位置を持つ。
パターン 1<!--n:label--> は 0<!--n:label--> のランが `fiber_detect_factor` より短いとき、パターン 2<!--n:label--> は +1<!--n:label--> の
ランの開始から −1<!--n:label--> の次のランの開始までが `noise_detect_factor` を超えるときに
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

`_bg_generate` では、マスクを使う前に 2<!--n:count--> つの補正を行う。

**小成分の除去。** 2<!--n:count--> つのパターンは数画素の大きさのノイズ特徴にも反応し、
ノイズの多い画像や広視野画像では画面全体に密に散らばる。1<!--n:count--> 行の中で塗られる
長さは、パターン 1<!--n:label--> では最短 2<!--x:1 + 1 + 1 - 1--> 画素、パターン 2<!--n:label--> では `noise_detect_factor` 画素
以上である。したがって既定の `noise_detect_factor` = 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor--> では、10<!--c:lib/pipeline.py::ProcParams.min_mask_component_area--> 画素未満の
小成分を生むのはパターン 1<!--n:label--> だけであり、パターン 2<!--n:label--> が小成分を生むのは
`noise_detect_factor` を小さくした場合（ステージクラスのコンストラクタ既定は
2<!--c:lib/bg_calibrator.py::BGCalibrator.__init__(noise_detect_factor)-->）である。8<!--n:literal in the quoted code--> 連結成分のうち
`min_mask_component_area`（既定 10<!--c:lib/pipeline.py::ProcParams.min_mask_component_area-->）未満のものを除去する。これが無いと、
以下の膨張が 1<!--n:count--> つの偽検出を $(2d+1)^2$ の穴へ拡大し、再構成背景がゴマ塩状
となって、タイル状・細胞状のアーティファクトとして現れる。

**膨張。** マスクを `mask_dilation` px（既定 3<!--c:lib/pipeline.py::ProcParams.mask_dilation-->）膨張させる。`_extract_fiber`
が拾いきれない繊維の*肩*の画素には残留する繊維高さがあり、背景プールに残す
と推定値が底上げされ、繊維の両脇で過剰減算——暗いハロー——を生む。

`tri_difx_fill[1:, :]` と `tri_dify_fill[:, 1:]` は、和を取る前に X と Y の
マップを切り詰め後の画像の格子へ揃える。小成分の除去が行われるのは、膨張が
有効（`mask_dilation` > 0<!--n:literal in the quoted code-->）で、かつ `min_mask_component_area` が 1<!--n:literal in the quoted code--> より大きい
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

充填後の曲面を Savitzky–Golay フィルタ（`savgol_window` 既定 31<!--c:lib/pipeline.py::ProcParams.savgol_window-->、
`savgol_polyorder` 既定 1<!--c:lib/pipeline.py::ProcParams.savgol_polyorder-->）で平滑化し、トレンドを足し戻し、`_bg_calibrate`
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

### 1.4 `tophat` — 高速・マスク不要

`_call_tophat` は背景を、直径 `tophat_se_size`（既定 25<!--c:lib/pipeline.py::ProcParams.tophat_se_size--> px）の円盤状の
構造要素（縦横同寸の `cv2.MORPH_ELLIPSE`）による形態学的 **opening** として
推定する。opening は円盤より細い明るい構造を除去するので、残るものが背景である。残差 `original - opening` が典型的な
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

省略できない要点が 2<!--n:count--> つある。

**デトレンドした写しに opening をかける。** opening は画像内部では平面を
再現するが、構造要素の半径以内の境界域では再現しない。そこでは収縮が切り
詰められた近傍から最小値を取り、膨張が復元できないからである。先にデトレンド
するのは、この境界効果のもとになる傾きを除くためである。

**その後に中央値で再センタリングする。** opening は*下側包絡線*の推定量で
あり、ノイズのある基板では局所極小に張り付く。そのため減算後の基板レベルは
ノイズ包絡の深さ分だけ正側に浮く。画像中央値を引くことで 0<!--n:definition--> nm へ戻し、
`global_threshold`、`low_threshold`、`bp_height` が、ノイズの中央を通る補間系
の方式と同じ意味を持つようにする。繊維被覆率が約半分未満であれば中央値は
頑健である。

本方式は繊維マスクを作らないため、リッジ検出系の中間配列を計算しない。
同じオブジェクトで前回別の方式を実行していれば、その値が属性に残っている。
それを誤って参照しないよう、これらの属性には明示的に `None` を設定する。

### 1.5 `spline1d` — ラインノイズ主体の走査向け

`_call_spline1d` は `trendfill` の繊維マスクを流用したうえで、`spline1d_axis`
が指す軸に沿って、各ラインを次数 `spline1d_degree`（既定 2<!--c:lib/pipeline.py::ProcParams.spline1d_degree-->）の 1<!--n:definition--> 次元
B スプラインで独立に埋める。`'x'` では 1<!--n:count--> 本のラインが画像の 1<!--n:count--> **行**、`'y'`
では 1<!--n:count--> **列**である。各ラインの充填はそのライン自身の標本だけから作るので、
充填した背景はそのラインに固有の水準を保つ。行が高速走査軸である通常の配置
では、`'x'` のラインは走査ラインそのものであり、保たれる水準は走査ラインの
オフセット（フィードバックループのドリフトが生む横縞）である。どちらの軸でも、
後段の Savitzky–Golay 平滑化は X 方向（行に沿って）だけに働く。

既定の軸は `'x'` である。有効サンプルが `spline1d_degree` + 1<!--n:literal in the quoted code--> 個未満のライン、
または次数が 2<!--n:literal in the quoted code--> 未満の場合は、代わりに線形で埋める。

ライン端には意図的に**形を外挿しない**。各ラインの最初／最後の有効サンプルより
外側は片側にしか背景データが無いため、1<!--n:definition--> 次元手法がそこに置く形——スプライン
自身の外挿や線形の傾き——はそのライン単独で当てたものになる。その誤差は区間が
長いほど増え、隣接ラインと無相関なので、各ラインが自前の帯を描いてしまう。
`_spline1d_fill` は代わりに、各端の区間にわたって**そのライン自身の最近傍
`end_window` 個の背景サンプルの平均**を保持する。`end_window` には
`savgol_window`（既定 31<!--c:lib/pipeline.py::ProcParams.savgol_window-->）を渡す。既定の `'x'` では、デトレンド後の画像で
ライン固有に残る量は実質的に走査ラインのオフセットであり、ライン方向に一定
なので、水準を保持すれば傾きを外挿せずにこれを推定できる（`'y'` では、保持
するのはその列の水準である）。多数のサンプルを平均するのは、その水準に
画素ノイズを持ち込まないためである。有効サンプルが 2<!--n:literal in the quoted code--> 点未満のラインだけは
埋めずに残し、その画素を 2<!--n:definition--> 次元の最近傍背景画素から埋める。

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

| `bg_method` | 使う場面 | 行う処理 |
|---|---|---|
| `trendfill`（既定） | 一般用途。繊維を背景プールから除外するため、繊維自体を削り込まない。 | 勾配ヒストグラムのフィット（`lmfit`）による繊維マスクの検出、トレンドのフィット、充填、平滑化。 |
| `tophat` | 特殊な試料でリッジ検出が期待どおり働かない場合。 | 繊維マスクを検出せず、トレンドのフィット、opening、平滑化だけを行う。 |
| `spline1d` | ラインノイズ（フィードバック不良、走査線オフセット）が支配的な走査。 | `trendfill` のマスク検出と `_bg_generate` をすべて実行したうえで、ラインごとの 1<!--n:definition--> 次元スプラインを加える。 |

利用できなくなった方式（`spline2d`）を選んだ保存済みパラメータファイルは、
`bg_calibrator.BG_METHOD_REMOVED` が方式名を挙げて報告し、実行を止める。残って
いる方式へ読み替えることはしない。別の方式に置き換えると、保存済みの
`_param.json` が再現するはずの数値が変わってしまうためである。

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

大域しきい値 `global_threshold`（既定 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm）は基板からの絶対高さである。
背景補正が不可欠になるのはこの値のためである。局所しきい値は
`skimage.filters.threshold_local` を窓幅 `wsize_localbin` px（既定 17<!--c:lib/pipeline.py::ProcParams.wsize_localbin-->）で
適用したもので、残存する緩やかな変動に追随する。

両方を要求するのは意図的である。局所検定だけでは何もない領域（ノイズ同士
しか比較対象が無い）でノイズを持ち上げてしまうので、大域検定がそれを除く。
一方、論理積なので、局所検定は大域検定を通った画素を減らすことしかできない。
残るのは、基板からの高さが大域しきい値を超え、しかも周囲の加重平均より高い
画素である。
<!-- TODO(review): 以前ここにあった「大域検定だけでは局所的に沈んだ領域にある繊維を取りこぼす」は、論理積では局所検定がそうした繊維を拾えないため、局所検定を加える理由として成り立たない。局所検定を加えた意図を作者に確認すること。 -->

`skimage.filters.threshold_local` は既定の引数で呼ぶため、局所しきい値は窓内のガウス重み付き
平均（オフセット 0<!--n:library default (skimage.filters.threshold_local offset)-->）である。

```python
# source: lib/segmenter.py::Segmenter._binaryzation
binary_global = image > global_threshold
local_threshold = threshold_local(image, wsize_localbin)
binary_local = image > local_threshold
binary_final = binary_global & binary_local
return binary_final
```

### 2.2 面積フィルタ

`_remove_small_fragments` は 8<!--n:literal in the quoted code--> 連結成分のうち面積が `area_min`（既定
100<!--c:lib/pipeline.py::ProcParams.area_min--> px²）以下のものを除去し、続けて 3<!--n:literal in the quoted code-->×3<!--n:literal in the quoted code--> の中央値フィルタを適用する。これに
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

- 面積 1000<!--n:literal in the quoted code--> px² 以上の成分は検定せずに保持する。その大きさなら答えは自明で
  ある。
- バウンディングボックスが両方向とも `h_length`（既定 20<!--c:lib/pipeline.py::ProcParams.h_length--> px）未満の成分は
  除去する。必要な長さの線を含みえないためである。
- それ以外は成分のバウンディングボックスに Canny エッジ検出をかけ、Hough
  変換に通す。スコアは

  $$
  s_{\text{ratio}} = \frac{\sum \text{Hough ピークの投票数}}{\sum \text{エッジ画素数}}
  $$

  であり、「この物体の輪郭のうち直線で説明できる割合はどれだけか」を表す。
  $s_{\text{ratio}} <$ `h_sratio`（既定 0.5<!--c:lib/pipeline.py::ProcParams.h_sratio-->）*かつ*画素数が 1000<!--n:literal in the quoted code--> 未満の成分
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

もう 1<!--n:count--> 点。`h_length` はこの関数の中で 2<!--n:count--> つの役割を持つ。上の外接矩形の検定
では画素単位の長さだが、Hough ピークの `threshold` 引数にも渡しているため、
そこでは最小投票数（線長の代理指標）として働く。
また `target` が対象成分のみになったことで、その画素数は `area` と等しくなり、
上の `area >= 1000` ガードが既に上限を与えている。したがって
`np.sum(target) < 1000` の項は、何かを決めるものではなく規則を明示するもので
ある。

### 2.4 弱連結の整理（既定では無効）

`_remove_connecting_fragments` はマスクを収縮させ、面積 `area_min_connecting`
px²（既定 3<!--c:lib/pipeline.py::ProcParams.area_min_connecting-->）以下の成分を除去し、膨張で戻して closing する。狙いは 1<!--n:intent--> 画素幅の
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

### 2.5 高さフィルタ

`remove_low_component` は、較正済み画像上での**最大**高さが `low_threshold`
（既定 1.8<!--c:lib/pipeline.py::ProcParams.low_threshold--> nm）未満である成分を除去する。平均ではなく最大を使うことで、
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
狙う 2<!--n:count--> 巡目である。`ridge_recovery` が真で、かつ画素サイズが既知の場合に
のみ実行される。設定値が物理長であるためである。

1. マルチスケールの **Frangi** 血管強調フィルタを、`ridge_min_width_nm` から
   `ridge_max_width_nm` を画素へ換算した範囲の等比 5<!--n:literal in the quoted code--> スケールで実行する。
   物理単位で扱うため、1<!--n:count--> つの設定値がどの走査解像度でも同じ構造を意味する。
2. 応答を**ヒステリシス**で二値化する。高い側は大津法、低い側は三角法で
   決める。
3. 採用済みマスクは連結成分処理の**前**に差し引く。既存マスクに一切触れない
   候補成分だけを採る方式では、長い繊維が検出済みの網目にどこか一点でも接した
   瞬間に丸ごと捨てられ、しかも長い繊維ほど接しやすい。
4. 残った成分は、そのスケルトンの画素数に画素サイズを掛けた長さが
   `ridge_min_length_nm`（既定 100<!--c:lib/pipeline.py::ProcParams.ridge_min_length_nm--> nm）に達するものだけ採用する。

既定で無効なのは、保存済みパラメータファイルが書かれた当時の数値を再現でき
るようにするためである。有効時は Frangi フィルタが本段の処理時間を占める。

コードでは、最小のスケールは 0.6<!--n:literal in the quoted code--> px を下回らず、最大のスケールは最小の
1.5<!--n:literal in the quoted code--> 倍以上になる。三角法のレベルが大津法のレベルを下回らない場合、低い側の
レベルは高い側の 0.3<!--n:literal in the quoted code--> 倍に置き換える。

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

最後に形態学的 closing（既定の十字形の構造要素による `skimage.morphology.closing`）を
かける。リッジ回収をその*前*に実行するのは意図的で、既存成分の隣で終わる回収セグメントが独立した短繊維と
して残らず、closing で取り込まれるようにするためである。

---

## 3. 細線化

**コード:** `lib/skeletonizer.py`（形態処理は `lib/imp_tools.py`）。
**読む:** `binarized_image`、`calibrated_image`。
**書く:** `skeleton_image`、`label_image`、`nLabels`、`data`、`ep`、`bp`。

目標は繊維 1<!--n:count--> 本につき 1<!--n:definition--> 画素幅の線（スケルトン）を得ることである。難しいのは、細線化が
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

### 3.1 細線化の仕組み

**コード:** `skimage.morphology.thin`（`thin_ignoring_image_border` が呼ぶ。
§3.2）。§3.3 と §3.4 で手を加えたマスクは `skimage.morphology.skeletonize` で
細線化し直す。

細線化は、二値化マスクを**境界から 1<!--n:definition--> 画素の層ずつ剥がしていき**、それ以上
剥がせなくなったところで止めることで、幅 1<!--n:definition--> 画素の線を作る。細線化が見るのは
各画素が繊維か背景かだけで、高さは一切読まない。

`skimage.morphology.thin` は Guo と Hall の並列細線化（1989<!--n:citation-->、*Comm. ACM*
32<!--n:citation-->(3<!--n:citation-->), 359–373<!--n:citation-->）を実装している。繊維画素 $P$ を消すかどうかは、東から反時計
回りに番号を付けた 8<!--n:definition--> 近傍 $x_1, \dots, x_8$ で決める。$x_i$ は繊維なら 1<!--n:definition-->、
背景なら 0<!--n:definition--> である。

```text
x4  x3  x2        NW  N   NE
x5  P   x1        W   P   E
x6  x7  x8        SW  S   SE
```

次の 3<!--n:count--> 条件をすべて満たすとき $P$ を消す（添字は一周するので $x_9 = x_1$）。

**G1 — $P$ を消しても連結性が変わらない。**

$$
X_H(P) = \sum_{k=1}^{4} b_k = 1, \qquad
b_k = \begin{cases}
1 & x_{2k-1} = 0 \text{ かつ } (x_{2k} = 1 \text{ または } x_{2k+1} = 1) \\
0 & \text{それ以外}
\end{cases}
$$

$X_H$ は、近傍の中で繊維画素がいくつのかたまりに分かれているかを数える。
かたまりがちょうど 1<!--n:count--> つなら、$P$ が無くても近傍どうしはつながったままなので、
$P$ を消しても成分は分かれず、穴の数も変わらない。上下左右の 4<!--n:definition--> 近傍に背景が
1<!--n:count--> つも無い画素は $X_H = 0$ となって消されないので、消えるのは境界の画素だけで
ある。

**G2 — $P$ は線の端点でも、切り込みの底でもない。**

$$
2 \le \min(N_1, N_2) \le 3, \qquad
N_1 = \sum_{k=1}^{4} (x_{2k-1} \lor x_{2k}), \qquad
N_2 = \sum_{k=1}^{4} (x_{2k} \lor x_{2k+1})
$$

線の端点は隣接画素が 1<!--n:count--> つだけなので $\min(N_1, N_2) = 1$ となり、消されない。
すでに幅 1<!--n:definition--> 画素になった線がそれ以上短くならないのはこのためである。上限は、
8<!--n:definition--> 近傍のうち背景が上下左右の 1<!--n:count--> 画素だけである画素（たとえば幅 1<!--n:definition--> 画素の
切り込みの底の画素）を残す。

**G3 — $P$ が、剥がしている側にある。** 1<!--n:label--> つ目のサブ反復では
$(x_2 \lor x_3 \lor \lnot x_8) \land x_1 = 0$ を、2<!--n:label--> つ目では
$(x_6 \lor x_7 \lor \lnot x_4) \land x_5 = 0$ を要求する。塗りつぶした長方形で
試すと、1<!--n:label--> つ目は上端の行と右端の列を、2<!--n:label--> つ目は左端の列と下端の行を消す。

各サブ反復では、すべての画素をそのサブ反復が始まった時点の画像で判定する
ので、消去は並列に行われる。2<!--n:count--> つのサブ反復を交互に繰り返し、1<!--n:count--> 回の反復で何も
消えなくなったら終わる。判定は、近傍の並び 256<!--x:2 ** 8--> 通りそれぞれに可否を記した表を
引くだけである。配列の外側は背景として扱うので、走査範囲の外へ続く繊維は、
画像端で終わっているものとして剥がされる（§3.2）。

幅 5<!--n:example--> 画素の帯に、1<!--n:example--> 画素の穴と、上辺から 2<!--n:example--> 画素突き出た突起を付けたマスク（左。
`#` が繊維）に `skimage.morphology.thin` をかけると、右のスケルトンになる。

```text
mask                        thin
........................    ........................
.......#................    .......#................
.......#................    .......#................
..####################..    .......#................
..####################..    .......#......#.........
..############.#######..    ....##########.#####....
..####################..    ..............#.........
..####################..    ........................
```

この例に、細線化の 4<!--n:count--> つの性質が表れている。この段の以降の処理は、どれも
これらへの対処である。

- **線は中間を通る。** 両側から 1<!--n:definition--> 層ずつ剥がすので、線は両側のマスク境界の
  中間、つまり幅 5<!--n:example--> 画素の帯の中央の行に残る。厳密な中軸変換
  （`skimage.morphology.medial_axis`。ここでは使っていない）と同じではないが、
  このページで「スケルトンはマスクの medial axis を通る」と書くのはこの性質の
  ことである。
- **位相は厳密に保たれる。** マスクの各成分は 1<!--n:count--> つの成分のまま残り、各穴は
  それを囲む閉じた輪になる（穴の周りのひし形）。§3.4 がこの輪を潰す。
- **突起はすべて枝になる。** 突起も両側から剥がされて中央で止まるので、繊維
  本体と同じように線が残る。上辺の突起から枝が出ている。§3.3 と §3.5 がこれを
  刈る。
- **太い端は縮むが、線の端は縮まない。** 帯は、先端が幅 1<!--n:definition--> 画素になるまで
  両端で短くなり、そこから先は G2 によって残る。先端に低く広い裾が
  あると、線はその裾の中へ細線化される（§3.6）。

高さを使う処理はすべて細線化の後に加えている。§3.3 の枝刈り、§3.4 のループの
高さガード、§3.6 のフック切除、そして §4.2 の中心線である。

`skimage.morphology.skeletonize`（2<!--n:definition--> 次元画像では既定で Zhang と Suen の細線化。
1984<!--n:citation-->、*Comm. ACM* 27<!--n:citation-->(3<!--n:citation-->), 236–239<!--n:citation-->）は、別の 2<!--n:count--> サブ反復の細線化である。この段で使うのは、
§3.3 と §3.4 が手を加えたマスクを細線化し直すときだけで、そのマスクは手を
加えた箇所を除けばすでに幅 1<!--n:definition--> 画素である。上の例の `skimage.morphology.thin` の
出力にかけても何も変わらない。ただし太いマスクでは 2<!--n:count--> つの結果が異なることが
あり（上の例のマスクでは線の右端が異なる）、最初のスケルトンは必ず
`skimage.morphology.thin` で作る。

### 3.2 画像端で繊維を切らずに細線化する

`thin_ignoring_image_border` は画像端を `DEFAULT_BORDER_PAD` = 12<!--c:lib/skeletonizer.py::DEFAULT_BORDER_PAD--> px 外側へ
複製し、細線化してから切り戻す。

`skimage.morphology.thin` は配列外をすべて背景として扱うため、視野外へ抜ける
繊維は配列端で平らに切断された形状となり、その切断端の medial axis は切り口
の近い側の角へ向かって折れ、追跡線は末端で稜線から外れる。端を複製すると、
繊維は打ち切られずに外側へ延長されるので、この折れが生じない。

複製は、端を横切らず端に*沿って*延びる塊を太らせ、その軸を動かすことがある。
幅の広い塊では縁帯より内側（画像の中央寄り）にある軸も動き、幅の狭い塊では軸が
画像外へ押し出されることさえある。そこで、パディング版でスケルトンが空になる
連結成分は素の細線化結果を採用する。本補正で繊維が失われることはない。

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

### 3.3 高さゲート付きの枝刈り

枝を刈るかどうかを、分岐点の高さで決める段である。高さを使うクリーニングは
ほかに §3.4 のループの高さガードと §3.6 のフック切除があるが、分岐点を高さで
分類するのはこの段だけである。

`set_low_bp_coor` は、較正済み高さを `bp_height`（既定 10<!--c:lib/pipeline.py::ProcParams.bp_height--> nm）と比較して、
スケルトンの分岐点を**低い**ものと**高い**ものに分ける。以下で腕が刈られるのは、
探索が低い分岐点に達したか行き止まりになった場合だけで、高い分岐点に接した腕は
残る。
<!-- TODO(review): bp_height が何を分けるためのものか、作者の確認が要る。 -->

```python
# source: lib/skeletonizer.py::Skeletonizer.set_low_bp_coor
all_bps = imp_tools.branchedPoints(init_skeleton_image)
low_bp_coor = np.where(all_bps & (calibrated_image < bp_height))
high_bp_coor = np.where(all_bps & (calibrated_image >= bp_height))
```

`get_close_eps` は、低い分岐点から `branch_length` px（既定 12<!--c:lib/pipeline.py::ProcParams.branch_length-->）以内にある
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
次に低い分岐点の判定、最後に高い分岐点の判定を行い、いずれも現在の画素の 3<!--n:definition-->×3<!--n:definition-->
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

この探索には意図的な性質が 2<!--n:count--> つある。

- 探索は画像全体を明示的な境界判定で辿る。そのため、端点の近傍の外へ続く繊維が
  行き止まりと読まれることはない。
- 各探索は自前の訪問済み集合を持つ。そのため、先に処理した端点の探索が後続の
  探索からスケルトンを隠すことはなく、結果は端点の処理順に依存しない。

走査端から `branch_length` 以内の端点は対象外である。端の近くで終わる腕は
枝の先端ではなく、視野外へ抜ける繊維だからである。

枝刈り後のマスクは再細線化して 1<!--n:definition--> 画素幅へ戻す。

```python
# source: lib/skeletonizer.py::Skeletonizer.prune_branches
branches_image = self.calc_branches_image(calibrated_image, init_skeleton_image)
return init_skeleton_image - branches_image
```

### 3.4 ループアーティファクトを潰す

`collapse_skeleton_loops` は、スケルトンに**囲まれた**背景領域を探す。
8<!--n:definition--> 連結スケルトンの位相的補集合である 4<!--n:literal in the quoted code--> 連結でラベル付けするため、バウンディング
ボックスが画像端に接しない成分が真の穴である。面積が `max_loop_area`
（既定 100<!--c:lib/pipeline.py::ProcParams.max_loop_area--> px²）以下の穴を充填し、再細線化することで二重経路を 1<!--n:count--> 本の線へ
戻す。

二値マスク内部の穴はトポロジー保存細線化で二重経路として残り、その輪の上に
分岐点を作る。再細線化は既に細い線を変えないので、充填
箇所から離れたスケルトン画素は同じ座標に残る。そのため、キンクや端点のように
画素座標で引く特徴点は、そうした場所では変わらない。

これが 2<!--n:count--> 本の実在の繊維を融合させないよう、**高さガード**を設けている。
ループアーティファクトは繊維本体の内側か交差にあるため、内部は高いままである。
別々の 2<!--n:count--> 本が 2<!--n:count--> 点で接触して囲む細長い隙間なら、背景レベルの画素を含むはず
である。囲みを充填するのは、内部の中央値高さが周囲リッジの
中央値の `DEFAULT_LOOP_HEIGHT_RATIO` = 0.3<!--c:lib/skeletonizer.py::DEFAULT_LOOP_HEIGHT_RATIO--> 以上のときだけである。誤って
充填すると 2<!--n:count--> 本が融合し、その間の溝の中央に経路が捏造される。
<!-- TODO(review): 0.3 がループと隙間を分けられるかは確かめていない。 -->

リングは穴の 5<!--n:literal in the quoted code-->×5<!--n:literal in the quoted code--> 膨張の内側にあるスケルトン画素であり、2<!--n:count--> つの高さはいずれも
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

### 3.5 短いスパーを刈る

`prune_short_spurs` は、端点から出発して分岐点に到達する、長さ `spur_length`
（既定 12<!--c:lib/pipeline.py::ProcParams.spur_length--> px）以下の行き止まりの腕を除去する。

§3.3 と違い**純粋に幾何的**であり、それが要点である。繊維本体から生えた
スパーは繊維の高さにあるため高さしきい値では実在の交差と区別できないが、
長さの上限なら区別できる。実在の繊維の腕がそこまで短いことは稀だからである。
到達範囲に分岐点が無い孤立した短片は保持し、端点が画像端から
`border_margin` = 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px 以内にある腕は決して刈らない。§3.3 と同じく、端の近く
で終わる腕は枝の先端ではなく視野外へ続く繊維でありうる。加えて、走査端の直前
で接触する 2<!--n:count--> 本の繊維は真の合流点を作っており、その短い腕を刈ると 2<!--n:count--> 本が融合
してしまう。

合流点とは、スケルトン上の隣接画素を 3<!--n:literal in the quoted code--> つ以上持つ分岐点である
（`_junction_degree`）。探索は分かれ道で刈らずに止まり、スパーが 1<!--n:count--> 本も除去され
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

### 3.6 末端フックを切除する

`prune_terminal_hooks` は、上の 3<!--n:count--> パスがいずれも検出できない欠陥を扱う。
セグメンテーションが繊維先端の低く広がった「裾」をマスクに含めると、細線化は
その medial axis を裾へ辿って周縁を回り込み、**分岐点を持たないフック**を
残す。枝刈りは分岐点を必要とし、スパー除去は合流点を必要とし、ループ潰しは
閉じた穴を必要とする。フックはそのいずれも持たない。

フックは端点近傍の方向反転で認識する。端から `DEFAULT_HOOK_LENGTH` = 12<!--c:lib/skeletonizer.py::DEFAULT_HOOK_LENGTH--> px
以内で頂点内角が `DEFAULT_HOOK_APEX_ANGLE_DEG` = 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度未満になる場合である。
切除するのは、較正高さが隣接する本体の中央値高さの
`DEFAULT_HOOK_HEIGHT_RATIO` = 0.5<!--c:lib/skeletonizer.py::DEFAULT_HOOK_HEIGHT_RATIO--> 未満に落ちた画素だけである。したがって、
高さが本体のこの割合以上にとどまる折れた端は切られない。

頂点角 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度はキンク判定しきい値 150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg--> 度よりはるかに鋭いため、キンク検出に
干渉しない。切除量は見つかった最深の反転頂点までに制限され、まっすぐ薄れて
いく末端が短くされることはない。

マスクが裾を含んでいる以上、フックはそのマスクの medial axis として正しい。
そのため、細線化の文献にある、二値の形だけから枝の重要度を測る方法では
見分けられない。見分けるのに必要な情報は高さである。そこでこの段は、濃淡画像を
手がかりに繊維を辿る方法と同じ基準を使う。繊維の中心線は高さの稜線の上に
なければならない、という基準である。

コードでは、各端点からの経路（`_walk_from_endpoint`）を最大 30<!--x:12 + 6 + 12--> px 辿る。
経路の添字 $j \le 12$ における頂点角は、6<!--c:lib/skeletonizer.py::_HOOK_DIRECTION_WINDOW--> ステップ先の点（$j + 6$）へのベクトルと、
端点へ戻るベクトルのなす角である。角度が 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度未満となる最も深い $j$ が頂点で
ある。本体の高さは頂点より後の 12<!--c:lib/skeletonizer.py::_HOOK_BODY_WINDOW--> 画素の中央値で（4<!--n:literal in the quoted code--> 画素以上が必要）、先頭の
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

### 3.7 微小成分とリング成分の除去

`remove_small_and_ring` は `min_area`（既定 10<!--c:lib/pipeline.py::ProcParams.min_area--> px）未満の成分と、**端点を
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

### 3.8 端点と分岐点

`imp_tools.endPoints` と `imp_tools.branchedPoints` は、各スケルトン画素を
3<!--n:definition-->×3<!--n:definition--> 近傍パターン集合との hit-or-miss マッチング（`cv2.MORPH_HITMISS`）で
分類する。得られた
`ep` / `bp` マップはバンドルに保存され、下流の追跡と
`measure.isolated_fiber_flags` の孤立判定が参照する。

スケルトンには先に背景画素 1<!--n:literal in the quoted code--> つ分のパディングを付けるため、画像の縁にある
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
`KinkDetector.kinks_on_line`。判定は `lib/centerline.py` が置く中心線（§4.2）
の上で行う。
**読む:** `skeleton_image`、`calibrated_image`、`bp`。**書く:** ラベルごとの
キンク配列、端のそばで判定しなかった折れ（§4.4）、およびそれらを 1<!--n:count--> 列に
まとめた配列。

キンクとは繊維の**局所的な鋭い折れ**であり、なだらかな曲がりとは区別する。
検出するには、何を「鋭い」とみなすかを決める必要がある。見落とされやすいが、
どの尺度で見るかも決める必要がある。画素単位で見れば鋭い折れも、繊維の尺度で
見ればなだらかな曲がりでありうるからである。ここでは繊維の見かけ幅 $W$
（§4.2）を尺度とする。$W$ は、探針が画像に残す分解能でもある。

`KinkDetector.__call__` は、追跡した各成分に中心線を置いて判定する。キンクは
中心線（`placed.x`、`placed.y`）の上で判定し、同じ添字のスケルトン画素に
保存する。

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
        method=self.centerline_method,
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
`remove_size` = 1<!--c:lib/imp_tools.py::remove_bp(remove_size)-->）を消去し、交差でスケルトンを切断して、残る各成分が
分岐の無い 1<!--n:count--> 本の線になるようにする。`min_area` = 10<!--c:lib/imp_tools.py::remove_bp(min_area)--> px 未満の成分は捨てる。
続く `imp_tools.remove_Lcorner` が、偽の折れとして登録されかねない 2<!--n:definition--> 画素の
L 字コーナーアーティファクトを除去する。

各連結成分は `imp_tools.tracking` が端から端まで追跡し、片方の端点からもう
一方へ歩いて画素座標を**順序どおりに**返す。端点がちょうど 2<!--n:literal in the quoted code--> 個でない成分は
追跡できないため、画像全体を中断せず、ログに記録してスキップする。

`imp_tools.remove_Lcorner` のパターンでは、1<!--n:definition--> のセルはスケルトン、0<!--n:definition--> のセルは
背景でなければならない。したがって除去されるのは、2<!--n:count--> 本の腕が直交方向の隣接
画素である L 字の角の画素であり、L 字は斜めの段差になる。`imp_tools.tracking`
はラスタ順で先に来る端点から出発し、各ステップで 3<!--n:literal in the quoted code-->×3<!--n:literal in the quoted code--> 窓のラスタ順で最初に
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

`remove_bp` が分岐点の周りを消してから追跡するので、キンク検出と、同じ追跡
経路を共有する高さサンプリングには、分岐点近傍の画素が入らない。これは意図
どおりである。交差部の高さはどの 1<!--n:count--> 本の繊維にも属さない。

### 4.2 繊維の中心線を高さの上に置く

**コード:** `lib/centerline.py` — `centerline.place_centerline`。

追跡したスケルトンは、どの画素が 1<!--n:count--> 本の繊維をなし、どの順に並ぶかを決める。
しかし繊維が*どこを*通っているかの推定としては不正確である。スケルトンは
二値化マスクの medial axis なので、マスクの両側の境界のちょうど中間を通る。
隣の繊維、分岐部の裾、背景の凹凸のどれかがマスクを片側だけ広げると、軸も
それにつられて動き、さらに 8<!--n:definition--> 連結の画素鎖による階段状のギザつきが加わる。
その結果、マスクがたまたま広がっただけのまっすぐな繊維に折れが現れる。

そこでキンクはスケルトン画素ではなく、繊維の高さの上に置いた**中心線**で判定
する。どの画素が 1<!--n:count--> 本の繊維をなすかは引き続きスケルトンが決め、中心線は
その各点をどこに置くかだけを決める。

#### 中心線の置き方

既定の方式では、各スケルトン点を次の 5<!--n:count--> 手順で繊維の高さの上へ移す。

1. `centerline.measure_apparent_width` が繊維の見かけ幅 $W$ を測る。トラックに
   沿った各高さ断面の半値全幅を求め、トラック全体での中央値を取ったものである。
   以降の手順の長さはすべて $W$ の倍数で決めるため、それらの手順は走査サイズに
   よらず同じ意味を持つ。
2. トラックを $W/4$ で平滑化し、これを**枠**とする。枠の各点が、その点の横方向
   の位置を測る原点となり、枠の向きが測る方向（繊維の法線方向）を与える。
   平滑化した位置をそのまま中心線にはしない。そうすると本物のコーナーまで
   丸まってしまうためである。中心線の位置は、次の手順で高さから測った横方向の
   オフセットで決まる。
3. `centerline.refine_centerline` が、その法線に沿って枠の点から坂を上り、
   最寄りの高さの極大を見つける。届く範囲で最も高い点を選ぶわけではないので、
   より高い隣の繊維に中心線を奪われることはない。そのうえで点を、**断面が基底と
   最大値の中間の高さ（半値）まで下がる 2<!--n:count--> つの位置の中点**に置く。
4. この 1<!--n:count--> 本の繊維の位置を決められない断面は「信頼できない」と印を付け、その
   オフセットは測らずに、周囲の信頼できる点から補間する。該当するのは、分岐点
   から $W$ 以内の断面、幅が $1.5\,W$ を超える断面（2<!--n:count--> 本が並んでいる）、見つけた
   極大がトラックの載っている断面のものではない断面、信号が弱すぎる断面である。
   各点のオフセットは、隣り合う点どうしの差（1<!--n:definition--> 階差分）に罰則をかける平滑化
   （Whittaker 平滑化）でトラックに沿って滑らかにつなぐ。罰則の強さは、
   平滑化の尺度が $W/4$ になるように決める。
5. 中心線の各点を、枠の点から法線方向にそのオフセットだけ動かした位置に置き、
   画像の最外の画素中心の範囲内に収める。走査範囲の外へ続く繊維
   では、手順 2〜4<!--n:label--> が最後の点を縁の外（高さを測っていない位置）へ運ぶことがある
   ためである。

計算の各手順は、コードとともに [GUI04 のファイバー計測](gui04_measurements.ja.md)
§2 で説明している。キンク検出も同じ関数を呼ぶ。

```python
# source: lib/centerline.py::place_centerline
width, measured = measure_apparent_width(height, x, y, return_measured=True)
lx, ly, reliable, crest = _refine(height, x, y, width, branch_points, method)
return CenterlineResult(lx, ly, float(width), bool(measured), reliable, crest)
```

結果の中心線は、スケルトン点 1<!--n:count--> つにつきちょうど 1<!--n:count--> 点を持つ。このため、中心線
上で判定したキンクをバンドルにはスケルトン画素として保存できる。また、描画と
計測はすべて中心線を使いながら、除外と連結は引き続きスケルトン画素で対象を
指定できる。

前処理パイプライン（GUI01 と `cli.py process`）はキンクを判定するときにこの関数で
中心線を作り、
`fiber_tracking_image.FiberTrackingImage` はバンドルを開くときに同じ関数で
作り直す。そのため、画面に表示されるキンクと、それが載る中心線は同じ 1<!--n:count--> つの
計算から来る。バンドルをどの中心線で組み立て直すかは、バンドルの形式で決まる
（`bundle_schema.centerline_from_meta`）。

| バンドル形式 | キンクを判定した対象 | 組み立て直す対象 |
|---|---|---|
| 1.2<!--n:bundle format version--> | `bundle_schema.CENTERLINE_KEY` に記録された中心線 | その中心線 |
| 1.1<!--n:bundle format version--> | 半値中点の中心線 | 半値中点の中心線 |
| 1.0<!--n:bundle format version--> | スケルトントラック | 再解析されるまでスケルトントラック |

#### 中心線と一緒に返すもの

`centerline.place_centerline` は、中心線と一緒に、その上で計算する数値が依存
する 3<!--n:count--> つの情報を `centerline.CenterlineResult` として返す。

- **$W$ と、それが実測値かどうか。** キンク規則の長さはすべて $W$ の倍数で
  あり、$W$ には繊維の幅だけでなく探針による広がりも含まれる。つまり $W$ は、
  その繊維のキンクを判定したときの物理的な尺度である。使える半値区間を持つ
  断面が少なすぎるときは `centerline.FALLBACK_WIDTH_PX`（8<!--c:lib/centerline.py::FALLBACK_WIDTH_PX--> px）を代わりに
  使う。これは繊維の幅の倍数ではなく単なる画素数なので、代用したことを隠さず
  報告する。各繊維は自身の $W$（`Fiber.width_px`、`Fiber.width_measured`）を
  ファイバー一覧と CSV へ渡し、バンドルには画像全体での $W$ の中央値と、代替値
  を使った成分の数を記録する（`bundle_schema.APPARENT_WIDTH_KEY`）。
- **位置を決められた点はどれか。** 手順 4<!--n:label--> で補間した点は直線区間の上にある
  ので、そこではキンクも曲率も検出できない。点ごとのフラグ
  （`Fiber.line_reliable`）は、中心線のうち実際に繊維の上で位置を決められた
  割合として、一覧と CSV に表示される。
- **頂点高さ。** 各点での繊維の高さは、中心線の位置で画像を補間した値ではなく、
  **断面の最大値**（`CenterlineResult.crest`）である。中心線は半値中点にある
  ため、非対称な断面では頂部の真上ではなく脇に来る。また双線形補間では、画素
  中心の間にある頂点の高さに届かない。
  <!-- TODO(review): 頂点高さも断面を双線形補間した標本の最大値なので（centerline._refine）、画素中心の間にある頂点に届かない点は頂点高さも同じであり、この文は頂点高さを選ぶ理由として区別になっていない。意図を作者に確認すること。 -->
  断面を決められなかった点では、補間した
  点から $W/4$ 以内の最大値を使う。`Fiber.height`、高さプロファイル、すべての
  高さ統計はこの頂点高さを使う。

#### 別の中心線を選ぶ

1/4 幅の半値中点は既定であって、唯一の選択肢ではない。既定は合成データと同梱
スキャンでの比較を見て選んだ経験的な選択である（[個別データでの評価](validation.ja.md)
§4.2、§4.3）。`centerline_method`
（GUI01 の Kinkdetector グループ、`cli.py process --centerline`）で、
`centerline.CENTERLINE_METHODS` にある 8<!--c:lib/centerline.py::len(CENTERLINE_METHODS)--> 種類の中心線から 1<!--n:count--> つを選べる。
利用者が自分の画像でこの選択を確かめられるようにするためである。どの中心線も、
どの画素が 1<!--n:count--> 本の繊維をなすかというスケルトンの判断をそのまま使い、スケルトン
点 1<!--n:count--> つにつき 1<!--n:count--> 点を返す。断面の読み方（極大への登攀と、半値のレベルでの
信頼性の判定）は共通で、主に違うのは各点を置く位置である。ただし 2<!--n:count--> つの例外が
ある。`"half_max_05w"` は枠とオフセットの平滑化が $W/2$ である。`"quarter_max"`
と `"centroid"` は、読むレベルが窓の中で閉じない断面を信頼できない点として
補間するので、信頼できる点と、それに伴って頂点高さ（信頼できない点では近傍の
最大値を使う）が既定と異なりうる。それぞれのコードは
[GUI04 のファイバー計測](gui04_measurements.ja.md) §2.8 に引用している。

次の表は、各中心線が点を置く位置である。

| `centerline_method` | 各点を置く位置 |
|---|---|
| `"half_max_025w"`（既定） | 半値中点。枠とオフセットを W/4 で平滑化 |
| `"half_max_05w"` | 同じく 0.5<!--c:lib/centerline.py::_WIDE_SMOOTH_WIDTHS--> W で平滑化 |
| `"skeleton_pixels"` | スケルトン画素そのもの |
| `"smoothed_skeleton_05w"`、`"smoothed_skeleton_1w"` | スケルトンを長さ方向に 0.5<!--n:definition--> W / 1<!--n:definition--> W で平滑化したもの |
| `"quarter_max"` | 1/4 高さの交点の中点 |
| `"centroid"` | 基底より上の高さで重み付けした重心 |
| `"crest"` | 断面の最大値（放物線で標本間に補間） |

なお、断面が異方的なフィブリルは、ねじれに伴って最も高い縁を左右交互に向ける。
探針が太い場合、この偏りは画像そのものに含まれており、高さから読み取るどの
中心線でも取り除けない。

キンク規則とその長さ（W の倍数）はどの中心線でも同じである。そのため、既定より
横方向のノイズが大きい中心線は、それだけで多くの折れを報告する。長さ・高さ・
キンクはすべて中心線によって変わるので、異なる中心線で得た結果どうしは比較
できない。

### 4.3 各折れを超過回転で判定する

**コード:** `KinkDetector.judge_line`（`KinkDetector.kinks_on_line` はその
結果をタプルで返す形）。

#### 超過回転規則

この規則は中心線の向き $\theta(s)$ を使う。弧長 $s$ に沿って 0.5<!--c:lib/kink_detector.py::_HEADING_STEP_PX--> px ごとに
再サンプリングし、$\sigma = W/4$ のガウスで平滑化したものである
（`kink_detector._heading_profile`）。位置 $p$ では、窓の内側で中心線が回る
角度を、窓のすぐ外側で繊維がもともと回っていた割合と比べる。

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

$T$ は窓の内側での回転角、$r_{\text{L}}$ と $r_{\text{R}}$ は左右の脇での
回転率である。$E$ を**超過回転**と呼ぶ。窓の中の回転のうち、脇で繊維がすでに
回っていた割合では説明できない分である。折れは

$$
E \ge 180^\circ - \theta_{\text{max}}
$$

のときキンクと判定する。$\theta_{\text{max}}$ は `kinkangle_deg`（既定
150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg--> 度）なので、既定では 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v--> 度以上の超過回転が必要である。しきい値を内角で
表すのは、形式 1.0<!--n:bundle format version--> のバンドルに使う折れ線規則（§4.6）も同じ `kinkangle_deg` を
内角のしきい値として読むためである。
`pipeline.build_stages` が検出器に渡す前にラジアンへ変換する。キンクとして
*保存する*角度は、これとは別に腕の向きから測る（後述の「報告する角度」を参照）。

**なぜ回転ではなく超過回転か。** 窓の中の回転だけを見ると、キンクだけでなく
なだらかな曲がりも拾ってしまう。たとえば半径 $3\,W$ の円弧は、$1.5\,W$ の間に
すでに 29<!--x:degrees(2 * 0.75 / 3)--> 度回る。円弧は窓の中でも両脇でも同じ割合で回るので超過回転はほぼ 0<!--n:analytic (an arc turns at one rate)-->
になり、まっすぐな腕に挟まれたコーナーは回転がそのまま残る。両脇の回転率の
*小さい方*を使うのは、曲線が終わる所にあるコーナーでは、片方の脇が曲がって
いてもう片方がまっすぐであり、それでもコーナーには違いないからである。どちらか
の脇が逆向きに回る場合（段差をなす 2<!--n:label--> つ目の折れ）は、何も差し引かない。

コードでは、`_heading_profile` が向きの再サンプリング・差分・平滑化を行い、
`excess_profile` が任意の位置で $T$ と $E$ を計算する。端の近くでは脇の区間が
中心線の範囲で切り詰められるが、割る数は $f$ のままである。位置 $p$ を採用
するのは、次の条件をすべて満たす場合だけである。

- 両端から $c$ 以上離れている。
- $|T(p)|$ がしきい値に達している。
- $E(p)$ がしきい値とノイズ床の両方に達している（`NOISE_SIGMAS` が 0<!--c:lib/kink_detector.py::NOISE_SIGMAS--> の間、
  ノイズ床は 0<!--c:lib/kink_detector.py::NOISE_SIGMAS-->）。

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

#### 候補の探し方

$E$ は候補の位置でだけ計算する。候補には 2<!--n:count--> 種類ある。

- **曲率の極大。** 曲率 $|d\theta/ds|$ の極大のうち、下限に達するもの。下限は、
  しきい値ちょうどの折れが窓全体で持つ平均曲率の半分、すなわち
  $0.5 \times (\pi - \theta_{\text{max}}) / (2c)$ である
  （`_CURVATURE_FLOOR_FRAC` = 0.5<!--c:lib/kink_detector.py::_CURVATURE_FLOOR_FRAC-->）。
- **$|T|$ そのものの極大。** $0.75\,W$ 以内に、上の曲率の極大から採用した
  候補が無い場所に限って加える。
  ノイズで曲率のピークが 2<!--n:count--> つに割れたコーナーや、回転がそのまま曲線へ続く
  コーナーは、中心に曲率の極大を 1<!--n:count--> つも持たないためである。両端から $c$ 以上
  離れたサンプル（`grid`）の上で探す。

$0.75\,W$ より近い候補どうしは 1<!--n:count--> つの折れとみなす。候補を超過回転の大きい順に
処理するので、そうした組では超過回転の最も大きいものが残る。

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

#### 報告する角度

キンクとして*保存する*角度（`ka`）は、180<!--n:definition--> 度から超過回転を引いた値では
なく、折れの両脇にある 2<!--n:count--> 本の**腕**のなす内角とする
（`KinkDetector.judge_line`）。各腕の向きは、頂点から半幅離れた位置（探針が頂点を
丸める範囲の外側）から 1<!--c:lib/kink_detector.py::_ARM_LENGTH_WIDTHS--> 幅の区間で平均した向きである。区間は次の折れの手前で
打ち切り、段差の 2<!--n:label--> つ目のコーナーが 1<!--n:label--> つ目の腕に入らないようにする。

超過回転も角度の隣に `ke` として保存する（§4.5）。判定に使った量と折れの
幾何の両方が、バンドルと一緒に残る。

**腕のなす角の計算方法。** 長さ $L$ の中心線上の弧長位置 $p$ にある折れに
ついて、$g = 0.5\,W$（`_ARM_GAP_WIDTHS`）、$a = 1.0\,W$
（`_ARM_LENGTH_WIDTHS`）とすると、2<!--n:count--> 本の腕は次の弧長区間である。

$$
A_{\text{L}} = \bigl[\max(s_0,\ p - g - a,\ p_{\text{prev}} + g),\ p - g\bigr],
\qquad
A_{\text{R}} = \bigl[p + g,\ \min(s_1,\ p + g + a,\ p_{\text{next}} - g)\bigr]
$$

ここで、

- $s_0$ と $s_1$ は、最初と最後の向きのサンプルの位置である（始端から
  0.25<!--x:0.5 / 2--> px、終端から 0.25〜0.75<!--x:[0.5 / 2, 0.5 * 1.5]--> px 内側）。
- $p_{\text{prev}}$ と $p_{\text{next}}$ は、同じ中心線上に残した最寄りの
  別の折れである（判定したかどうかは問わない）。無ければその項を省く。

各腕の向き $\bar\theta$ は、区間内の等間隔な 16<!--n:literal in the quoted code--> 点で平滑化後の向きを取り、
平均したものである。内角は

$$
\phi = \max\bigl(0,\ \pi - |\bar\theta_{\text{R}} - \bar\theta_{\text{L}}|\bigr)
$$

である。どちらかの区間が $0.25\,W$（`_ARM_MIN_WIDTHS`）より短い場合、つまり
2<!--n:count--> つの折れが近すぎて間に腕が取れない場合は、代わりに $\phi = \pi - E$ を保存
する。角度は最後に $[10^{-6},\ \pi - 10^{-6}]$ rad に収め、ラジアンのまま `ka` に
書き込む。折れの位置は弧長で $p$ に最も近い中心線の点とし、`kp` にはその添字の
スケルトン画素を書く。2<!--n:count--> つの折れが同じ点に落ちた場合は、超過回転の大きい方を
残す。キンクかどうかを決めるのは角度では
なく $E$ なので、保存された角度が `kinkangle_deg` 以下になるとは限らない。

`measure.compute_fiber_stats` は角度を度に変換し（`FiberStats.kink_angles_deg`）、
ファイバー CSV にはこの値が入る。`measure.fiber_kink_angle` はその中央値を取り、
GUI03 がヒストグラムにする繊維ごとの値とする。

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

#### 尺度とノイズ床

**尺度。** 規則の長さはすべて $W$ の倍数であり、$W$ は画像の分解能でもある。
探針はどの繊維も約 $W$ の幅に広げるので、繊維自体がどれほど鋭く曲がっていても、
コーナーは中心線上で約 $W$ の長さを占める。それよりずっと近い 2<!--n:count--> つの折れは
見分けられない。規則の長さはすべて $W$ の倍数なので、$W$ が十分に分解されて
いる限り、同じ繊維を別の画素サイズで走査しても同じ尺度で判定する。ただし、
それぞれの長さが $W$ の何倍かは理論から一意に決まるものではなく、同梱スキャンの
目視基準で確かめた経験的な値である（[個別データでの評価](validation.ja.md) §4.4）。画素数で
決まるのは、$W$ を測る手順の中の長さ（幅を測るときに断面を読む範囲はトラックから
±12<!--c:lib/centerline.py::_WIDTH_SEARCH_PX--> px、$W$ を測れなかったときの代替値 `centerline.FALLBACK_WIDTH_PX` の
8<!--c:lib/centerline.py::FALLBACK_WIDTH_PX--> px など）と、標本化の間隔（断面は 0.25<!--c:lib/centerline.py::_WIDTH_STEP_PX--> px、向きは 0.5<!--c:lib/kink_detector.py::_HEADING_STEP_PX--> px）である。
`kink_decompose_px` はもう使わない（§4.6）。

**中心線ごとのノイズ床（既定は無効）。** 中心線ごとのノイズ床を実装している
（`NOISE_SIGMAS`、`KinkJudgement.noise_excess`）。中心線全体での超過回転の
ロバストなばらつきを求め、折れの超過回転がその何倍かを超えることを要求する
ものである。既定では**無効**である（`NOISE_SIGMAS` = 0<!--c:lib/kink_detector.py::NOISE_SIGMAS-->）。無効にした経緯は
[個別データでの評価](validation.ja.md) §4.7 にある。

### 4.4 端のそばの折れは判定せずに示す

中心線の端から $1.5\,W$ 以内に中心がある折れは**判定しない**。トラックの端には、
繊維の本当の終端のほかに、§4.1 の `imp_tools.remove_bp` が交差で切った切断が
あり、そこでは中心線が分岐部の裾につられて曲がりうるためである。範囲の
$1.5\,W$ は経験的に選んだ値である（[個別データでの評価](validation.ja.md) §4.9）。

こうした折れも捨てずに残す。`KinkDetector.kinks_on_line` はこれを別に返し、
バンドルは任意キー `up` に保存し、各繊維には `Fiber.unjudged_indices` として
渡り、GUI04 は灰色の中空の円で描く。これにより「判定しなかった」と「測った
うえでしきい値未満だった」を区別できる。ただし数には一切入れない。キンク数・
密度・角度・CSV は、判定したキンクだけを扱う。連結処理と
`fiber_connector.filter_fibers_by_height` は、組み立て直した繊維に同じ規則を
適用し直す。そのため連結したフィブリルが切断をつなげば、その折れはもう端の
そばにないので判定される。逆に高さの絞り込みは繊維を切るので、新しくできた
端のそばの折れは判定されなくなる。

### 4.5 しきい値は結果と一緒に持ち運ばれる

キンクのパラメータはバンドルの `params` メタデータに書き込まれ、
`bundle_schema.kink_params_from_meta` が読み戻す。読み手が実際に使うのは
`kinkangle_deg` であり、これは省くことができない。バンドルに含まれないトラック
（交差をまたいで連結した繊維や、高さ帯で切り出した部分繊維）でキンクを計算し
直すときは、保存済みのキンク点を生んだのと同じ規則を適用する必要がある。その
規則を、それが説明する配列と一緒に持ち運べる場所はバンドルしかない。
`kink_decompose_px` も読み戻すが、使うのは形式 1.0<!--n:bundle format version--> のバンドルだけである
（§4.6）。

これらを `_param.json` サイドカーから読まないのは意図的である。このファイルは
解析の*入力*であり、解析後も編集できる。そこから読むと、再解析しないまま、
ファイルを編集しただけで連結繊維のキンクが変わってしまう。

バンドルは各キンクの角度 `ka` の隣に、判定に使った超過回転（`ke`、
`KinkJudgement.kink_excess`）も保存する。角度は折れの幾何を表し、超過回転は
規則が検定した量を表す。両方があれば、規則を実行し直さなくても、各キンクが
しきい値をどれだけ超えていたかを確認できる。

### 4.6 形式 1.0 のバンドルの折れ線規則

形式 1.0<!--n:bundle format version--> のバンドルのキンクは、スケルトントラック上で折れ線規則により判定されて
いる。`KinkDetector._binary_decompose_simple` が **Douglas–Peucker** 法の考え方で
トラックを折れ線に縮約し、弦から `kink_decompose_px`（既定 3.0<!--c:lib/pipeline.py::ProcParams.kink_decompose_px--> px）以上離れた
トラック点に頂点を挿入する。`KinkDetector._detect_kink_from_decomposed_indices`
は、内角 $\theta$ が `kinkangle_deg` 以下で、直線からの不足が、頂点の許容量 $d$
が長さ $A$ の腕に与える誤差棒を上回る頂点を残す。

$$
\pi - \theta > \frac{2d}{\min(A_{\text{prev}},\, A_{\text{next}})}
$$

その規則は画素の許容量のほかに尺度を持たないため、滑らかな円弧も頂点に分割して
キンクとして報告しうる。またスケルトンを判定するため、階段状の画素鎖や幅の広い
箇所での振れという、繊維自体には無い折れも報告しうる。1.0<!--n:bundle format version--> のバンドルは再解析
されるまでスケルトントラックと保存済みキンクを保ち
（`bundle_schema.centerline_from_meta`）、その中で再結合したフィブリルはその規則で
判定する（`KinkDetector.kinks_and_decomposed_from_track`）。これにより、1<!--n:count--> 枚の画像
に 2<!--n:count--> つの規則のキンクが混在することはない。

コードでは、折れ線は両端の 2<!--n:literal in the quoted code--> 点から始まり、いずれかの弦から最も遠いトラック点を
繰り返し加えて、すべての点が弦から `threshold_distance`（`kink_decompose_px`）
未満に収まるまで続ける。その後、各内部頂点の角度を検定する。

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
  §4.2 の中心線に沿って読み、その中心線はバンドルを開くときに
  `fiber_tracking_image.FiberTrackingImage` が保存済みのスケルトンと高さから
  作り直す。次の 2<!--n:count--> つの定義は、中心線だけでなく上記の段の振る舞いからも決まる。高さ統計は
  §4.2 の頂点高さについて取り、繊維端ではなく切断である端の最後の $W$ を外す
  （`measure.height_sample_mask`）。§4.1 が消すのは分岐点周りの 3<!--c:lib/imp_tools.py::remove_bp(remove_size)|2 * v + 1-->×3<!--c:lib/imp_tools.py::remove_bp(remove_size)|2 * v + 1--> だけだが、
  交差での相手繊維の裾はその先 1 幅ほど広がるため、それらの標本は一部が相手の
  繊維の高さである。中央値はその影響をほとんど受けないが、最大値は交差の高さを
  拾ってしまう。<!-- TODO(review): 「1 幅ほど」は scripts/measure_docs.py のどの実験も測っていない。CUT_END_EXCLUSION_WIDTHS の根拠として書かれたものである。 -->
  連結器が橋渡しで補間した高さも、画像を測った値ではないので外す。またキンク密度
  （`measure.fiber_kink_density`）は**判定した**長さ、すなわち輪郭から両端の
  $1.5\,W$ を引いたもので割る。§4.4 はそれより端に近い折れを判定しないためで
  ある。輪郭全体で割ると、判定していない両端の分だけ低く読み、繊維が短いほど
  その偏りは大きい。
- 交差で分割された**断片の再連結**は `lib/fiber_connector.py` にあり、探索を
  実行するのは GUI04 だけである。他の読み手は、その探索が記録した連結情報を
  適用する。
- **手動除外**は `lib/fiber_selection.py` にある。
- **画素サイズ**は計測時にのみ関与する。上記の各段は、既定で無効のリッジ回収
  （§2.6。設定値が nm で、画素サイズが無ければ実行しない）を除いて画素基準で
  あり、だからこそ走査サイズが記録されているかどうかに関わらず、段の
  パラメータは同じ意味を持つ。この選択の裏面として、同じパラメータファイルは走査サイズごと
  に異なる物理尺度で働く。12<!--c:lib/pipeline.py::ProcParams.spur_length--> px のスパー上限は、1024<!--n:example--> 画素の走査なら、2<!--n:example--> µm
  走査では約 23<!--x:12 * 2000 / 1024--> nm、10<!--n:example--> µm 走査では約 117<!--x:12 * 10000 / 1024--> nm にあたる。そのため走査
  サイズが既知なら、バンドルは各画素設定が何 nm にあたったかを記録し
  （`bundle_schema.PIXEL_LENGTHS_KEY`、`pipeline.pixel_lengths_nm` による）、
  GUI01 はそれをログに出す。この記録があれば、2<!--n:count--> つのバンドルの段の設定が物理的に
  同じ長さだったかを比べられる。

## 6. 結果を再現する

このソフトウェアが報告する数値は、次の 3<!--n:count--> つの記録によって一意に定まる。

| 記録 | 記録する内容 |
|---|---|
| `<stem>_param.json` | 解析が使用した全 `ProcParams` フィールド。フィールド名は凍結されているため、古いファイルも読み込める。 |
| `<stem>.b2z` | 各段の出力配列、バンドル形式バージョン、キンクを判定した中心線（形式 1.2<!--n:bundle format version--> から）、走査サイズとその出所、解析した走査線範囲、および来歴としてのパラメータ。 |
| ソフトウェアのバージョン | バンドルに記録される。`CHANGELOG.md` は数値が変わる変更を明示的に記載する。 |

解析出力を変える変更は再現性の破壊として扱われ、API の変更を伴うかどうかに
関わらず、導入されたバージョンの `CHANGELOG.md` に明記される。
