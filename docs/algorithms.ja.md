# 解析アルゴリズム

このページでは、前処理の 4<!--n:count--> つの段階がそれぞれ実際に何をしているのか、そして
各手順がソースコードのどこにあるのかを説明する。論文の図に載せる数値について
「なぜこの値になるのか」を自分で説明しなければならない人のために書いている。
ソフトウェアが利用者の代わりに何を決めているのか、なぜそう決めたのか、それを
変えるにはどのパラメータを変えればよいのかを示す。

API リファレンスは関数を個別に説明する。このページは、関数どうしがどう
つながって全体として何をしているのかを説明する。

このページには、特定のデータでの結果は載せない。同梱のスキャンや合成データで
各段が実際にどう動いたか、いくつかの既定値をどの結果を見て決めたかは、
[個別データでの評価](validation.ja.md) にまとめてある。

## コード参照の読み方

コードは**シンボル名**（関数名やクラス名）で指し、行番号では指さない。行番号は、
関係のない編集が 1<!--n:count--> 回入っただけでずれてしまうからである。たとえば
`Segmenter._binaryzation` は `lib/segmenter.py` の中にある同じ名前のメソッドを、
`bg_calibrator.BG_METHOD_NAMES` はモジュールに直接書かれた定数を指す。このページに
出てくるシンボルは、テストを実行するたびに `tests/test_algorithm_docs.py` が
ソースコードと突き合わせる。名前が変わったり消えたりするとテストが失敗するので、
間違った記述が誰にも気付かれずに残ることはない。

各手順は、**その手順を実行するコードと一緒に**示す。ただし §4.2 の中心線の
各手順は、[GUI04 のファイバー計測](gui04_measurements.ja.md) §2 が同じコードを
引用しているので、ここでは入口の関数だけを引用する。コードブロックの先頭には、
そのコードがどこから来たかを示す見出し行（ヘッダ）がある。

```text
# source: lib/segmenter.py::Segmenter._binaryzation
```

ヘッダには、コードのあるファイルと、関数・メソッド（`Class.method` の形）・
モジュール定数の名前が書いてある。同じファイルのシンボルをカンマで区切って
複数並べることもある。`...` だけの行は途中を省いた印である。コメント・空行・
メソッドの字下げも省いている。各コード片は、ヘッダに書いたシンボルの実際の
コードと 1<!--n:count--> 行ずつ突き合わされる（`scripts/doc_excerpts.py` が行い、
`tests/test_algorithm_docs.py` と pre-commit フックがそれを実行する）。英語版と
日本語版は同じコードを引用しなければならない。こうして、このページに載せた
コードが実際に動くコードと食い違ったまま残ることはない。

同じテストは、反対の向きのずれも検査する。アルゴリズムのモジュール（4<!--n:count--> つの段と、
キンクを判定するための中心線を置く `lib/centerline.py`）を、コメントと
docstring を除いたうえでハッシュ化して記録している。そのため、コードの計算内容が
変わると、このページを見直すまでテストが通らない。コードだけが変わって文書が
取り残されることはない。

## 全体を通じた表記規則

| 量 | 単位 | 備考 |
|---|---|---|
| 高さ | ナノメートル (nm) | 読み込み時に nm へ変換する。以下に出てくる高さのしきい値はすべて、**背景補正をした後**の画像での nm の値そのものであり、基板の高さが 0<!--n:definition--> nm になっていることを前提にしている。 |
| 面内の距離 | 各段の中では画素 (px)、結果では実際の長さ（nm または µm） | 各段はわざと画素を単位にしている。画素の大きさ（1<!--n:definition--> 画素が何 nm か）を使うのは計測のときだけである。例外は既定では使わないリッジ回収（§2.6）で、その設定値は nm で指定する。 |
| 角度 | キンク判定の中ではラジアン、パラメータファイルでは度 | `pipeline.build_stages` が `KinkDetector` を作るときに、`kinkangle_deg` をラジアンに直す。 |
| 配列の添字 | `image[row, column]`、つまり `[y, x]` | いくつかのヘルパー関数は `np.where` の結果をそのまま返す。その場合、最初の配列が行の添字である。 |

**端の 1<!--n:definition--> 画素が削れる。** 背景補正は、隣り合う画素どうしの差（1<!--n:definition--> 次差分）を
もとに組み立てている。そのため出力は入力より縦横それぞれ 1<!--n:definition--> 画素小さい。
`BGCalibrator._bg_calibrate` が返すのは `original[1:, 1:] - bg_sm` である。後の段は
すべて、この削れた配列を使う。つまり解析結果の画素 $(r, c)$ は、元の
スキャンの画素 $(r+1, c+1)$ にあたる。

**パラメータ。** 以下に出てくる利用者が設定できる値は、すべて
`pipeline.ProcParams` のフィールドである。その値は、各バンドル（解析結果を
まとめた `.b2z` ファイル）の隣に `<input_stem>_param.json` として保存される。
同じ値は、どの設定で解析したかの記録（来歴）として、バンドルの中にも書き込まれる
（§4.5）。利用者が変えられる設定はこれですべてだが、解析を再現する
にはソフトウェアのバージョンも必要である（§6）。フック切除の角度（§3.6）の
ような内部の定数はフィールドではなく、バージョンによって決まるからである。
このページで「既定値」と書いた値は `ProcParams` の既定値であり、GUI と CLI は
この値から始まる。各段のクラスのコンストラクタにも既定値があり、一部は
`ProcParams` の既定値と違う。ただしそちらが使われるのは、スクリプトから
クラスを直接作ったときだけである。

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

この順番どおりに実行するのが `pipeline.process_file` である。GUI01 も
`cli.py process` もこの関数を呼ぶので、2<!--n:count--> つの入口で結果が食い違うことはない。
各段のオブジェクトは `pipeline.build_stages` が一度だけ作る。

各段は、前の段が書いた結果を読む。それが無ければ、その段の入口ではっきりと
エラーにする。たとえば `Segmenter.__call__` は、`calibrated_image` が `None` の
とき、OpenCV の奥で原因の分かりにくいエラーが起きる前に、その場で例外を出す。

---

## 1. 背景補正

**コード:** `lib/bg_calibrator.py` — `BGCalibrator.__call__` が
`_call_trendfill` / `_call_tophat` / `_call_spline1d` へ振り分ける。
**読む:** `original_image`。**書く:** `calibrated_image`。

`BGCalibrator.__call__` 自身は、選ばれた方式の処理へ振り分けるだけである。

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

生の AFM スキャンは、平らな台の上に試料を置いて測った高さの地図、というわけ
ではない。試料が傾いていたり、スキャナのせいで画像全体が皿のようにたわんで
いたりすることがある。

このことから次の 2<!--n:count--> つが言え、この段の作りはすべてここから決まっている。

1. 後の段のしきい値は、すべて **nm で表した高さそのもの**である。基板がどこでも
   0<!--n:definition--> nm にそろっていないと、しきい値は意味を持たない。
2. 背景の推定がこの傾きやたわみを再現できないと、そのずれがそのまま補正後の
   高さのずれになり、後の段のしきい値判定に紛れ込む。

### 1.2 方式ごとの処理の流れ

3<!--n:count--> つの方式は、背景の見積もり方がそれぞれ違う。まず各方式の流れを図で示す。
右端の括弧は、その手順を行う関数である。各手順の詳しい説明は §1.3〜§1.5 にある。

ここでいう**トレンド**とは、画像全体のゆるやかな傾きやたわみを表す、なめらかな
曲面のことである。**Savitzky–Golay フィルタ**は、少しずつずらした小さな窓の中で
多項式を当てはめて、データをなめらかにするフィルタである。

**`trendfill`（既定。§1.3）** — 繊維の画素を背景の候補から外し、その穴を
いちばん近い背景の画素の値で埋めて、背景を作る。

```text
元の画像 original
 -> 隣り合う画素の高さの差を取る                            (_difXY)
 -> 差の分布に山を当てはめ、ノイズにしては大きすぎる差に印   (_bg_fit, _dif_sep)
 -> 印の並び方から、繊維の画素を見つける                    (_extract_fiber)
 -> 小さなかたまりを消し、マスクを外側へ膨らませる           (_bg_generate)
 -> 端を削った画像の、背景の画素だけにトレンド曲面を当てはめる
 -> 画像からトレンドを引く
 -> 繊維の画素を、いちばん近い背景の画素の値で埋める
 -> X 方向に Savitzky-Golay フィルタでなめらかにする
 -> トレンドを足し戻す  => 背景 bg_sm
 -> original[1:, 1:] から bg_sm を引く                       (_bg_calibrate)
 -> (apply_median が有効なら 3x3 の中央値フィルタ)
```

**`tophat`（§1.4）** — 繊維の画素を調べない。穴埋めの代わりに opening で繊維を
削り取って、背景を作る。

```text
元の画像 original
 -> 繊維も含めた全部の画素にトレンド曲面を当てはめる
 -> 画像からトレンドを引く
 -> 円盤で opening をかけ、円盤より細い繊維を削る
 -> X 方向に Savitzky-Golay フィルタでなめらかにする
 -> トレンドを足し戻す  => 背景 bg_sm
 -> original[1:, 1:] から bg_sm[1:, 1:] を引く
 -> 画像全体の中央値を引き、基板の高さを 0 nm に戻す
 -> (apply_median が有効なら 3x3 の中央値フィルタ)
```

**`spline1d`（§1.5）** — `trendfill` と同じ繊維のマスクを使い、その穴を走査ライン
ごとの 1<!--n:definition--> 次元スプラインで埋めて、背景を作る。なめらかにするのは、トレンドを
足し戻した**後**である。

```text
元の画像 original
 -> trendfill と同じ手順で繊維のマスクを作る       (_detect_fiber_mask, _bg_generate)
 -> 端を削った画像の、背景の画素だけにトレンド曲面を当てはめる
 -> 画像からトレンドを引く
 -> ライン (既定は行) ごとに、繊維の画素をスプラインで埋める   (_spline1d_fill)
      ラインの両端の外側は、近くの背景の値の平均で一定に埋める
 -> それでも埋まらない画素は、いちばん近い背景の画素の値で埋める
 -> トレンドを足し戻す
 -> X 方向に Savitzky-Golay フィルタでなめらかにする  => 背景 bg_sm
 -> original[1:, 1:] から bg_sm を引く
 -> (apply_median が有効なら 3x3 の中央値フィルタ)
```

3<!--n:count--> つの方式に共通するのは、次の点だけである。

- トレンドの当てはめには、どれも `BGCalibrator._fit_trend_surface` を使う（下で
  説明する）。背景の見積もりは、トレンドを引いた画像の上で行う。
- なめらかにするのは、どれも X 方向（行に沿った方向）だけである。
- 背景を引くのは、端を削った `original[1:, 1:]` からである（冒頭の「全体を通じた
  表記規則」を参照）。
- 最後に 3<!--n:literal in the quoted code-->×3<!--n:literal in the quoted code--> の中央値フィルタをかけることができる。`apply_median`（既定は
  無効）で有効にする。有効にすると、点状に残ったノイズは減るが、そのぶん
  いちばん鋭い高さの特徴が少し鈍る。

`trendfill` と `spline1d` が穴を埋める前にトレンドを引いておくのは、どちらの
穴埋めの方法にも試料の傾きやたわみを再現させなくて済むようにするためである。
`tophat` がトレンドを先に引く理由は別で、opening が画像の端で傾きを再現できない
ためである（§1.4）。

`_fit_trend_surface` が当てはめるのは、平面ではなく**2<!--n:definition--> 次曲面**である。実際の
スキャンは傾いているだけでなく、皿のようにたわんでいることがあるからである
（§1.1）。2<!--n:definition--> 次の項を作る前に座標を $[-1, 1]$ の範囲に直し、計算が数値的に
不安定にならないようにしている。背景の画素の並び方が偏っていると（たとえば
全部の点が 1<!--n:count--> 行に並んでいると）、曲面は一通りに決まらない。それでも
`numpy.linalg.lstsq` は黙って答えを返してしまう。そこで、曲面が一通りに決まるか
（行列のランク）をはっきり調べ、決まらなければ 2<!--n:definition--> 次曲面 → 平面 → 背景の平均の
高さ、の順に簡単なものへ切り替える。

座標を $x_n, y_n \in [-1, 1]$ に直すと、当てはめる曲面は

$$
T(x, y) = a\,x_n^2 + b\,y_n^2 + c\,x_n y_n + d\,x_n + e\,y_n + g
$$

であり、背景の画素（`valid_mask`）だけを使って最小二乗法で係数を求める。

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

名前のとおり、トレンド (trend) を引いてから穴を埋める (fill) 方式である。古い
名前 `inpaint` が書かれたパラメータファイルも、`bg_calibrator.BG_METHOD_ALIASES`
が今の名前に読み替えるので、そのまま使える。

`_call_trendfill` は、次の 3<!--n:count--> つの手順を順に実行する。

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

#### 手順 1 — 高さの差の分布から繊維の画素を見つける

`BGCalibrator._detect_fiber_mask` が、4<!--n:count--> つの補助関数を順に呼ぶ。

```python
# source: lib/bg_calibrator.py::BGCalibrator._detect_fiber_mask
self.dif_x, self.dif_y = self._difXY(original)
self.histx, self.histy, self.outx, self.outy = self._bg_fit(self.dif_x, self.dif_y)
self.tri_difx, self.tri_dify = self._dif_sep(self.dif_x, self.dif_y, self.outx, self.outy)
self.tri_difx_fill, self.tri_dify_fill = self._extract_fiber(self.tri_difx, self.tri_dify)
```

`_difXY` は、横方向と縦方向それぞれについて、隣り合う画素の高さの差
（1<!--n:definition--> 次差分）$\Delta_x$、$\Delta_y$ を取る。差が大きいところは段差（エッジ）であり、
この試料では繊維の側面にあたる。

```python
# source: lib/bg_calibrator.py::BGCalibrator._difXY
dif_x = image[:, 1:] - image[:, 0:-1]
dif_y = image[1:, :] - image[0:-1, :]
return dif_x, dif_y
```

`_bg_fit` は、差分画像ごとに差の値の分布を 150<!--c:lib/bg_calibrator.py::BGCalibrator._bg_fit(bin_n)--> 区間のヒストグラムにし、
`lmfit` で**ガウス関数＋直線のベースライン**を当てはめる。ガウス関数の山が
*背景*、つまりゼロ付近に集まる基板のノイズを表す。繊維の側面の差は、山から外れた
裾のほうに出てくる。X と Y を別々に当てはめるのは、AFM では遅いほうの走査方向
（低速走査軸）のノイズの性質が違い、$\sigma$（山の幅）が広がりやすいからである。

ガウス関数の中心と幅の初期値には、差の中央値と、外れ値に強い幅の目安
（四分位範囲を 1.349<!--n:literal in the quoted code--> で割った値）を使う。Y の当てはめは、同じコードを `dif_y`
に対して実行する。

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

`_dif_sep` は、当てはめで得た山の中心 $\mu$ と幅 $\sigma$ を使って、各差分画像を
**3<!--n:definition--> 値の地図**に変える。

$$
\text{tri} = \begin{cases}
+1 & \Delta > \mu + f\sigma \\
0 & \text{それ以外} \\
-1 & \Delta < \mu - f\sigma
\end{cases}
$$

ここで $f$ は `threshold_factor`（既定 2.0<!--c:lib/pipeline.py::ProcParams.threshold_factor-->）である。つまり $\pm 1$ は「この段差は
基板のノイズにしては大きすぎる」という意味である。その境目は決まった nm の値
ではなく、画像ごとのノイズの幅から決まる。

Y の地図も、Y の当てはめ結果から同じやり方で作る。

```python
# source: lib/bg_calibrator.py::BGCalibrator._dif_sep
outx_min = outx.best_values['pv1_center'] - self.threshold_factor * outx.best_values['pv1_sigma']
outx_max = outx.best_values['pv1_center'] + self.threshold_factor * outx.best_values['pv1_sigma']
...
tri_difx = np.where(dif_x < outx_min, -1, 0) + np.where(dif_x > outx_max, 1, 0)
```

次に `_extract_fiber` が、3<!--n:definition--> 値の地図を行ごと（X 用）と列ごと（Y 用）に
端から順に読んでいく。同じ値が続く区間（ラン）ごとにまとめ、繊維を横切ったときに
現れる 2<!--n:count--> 種類の並び方を探す。ただしループは `range(shape[0] - 1)` なので、
X の地図の最後の行と Y の地図の最後の列は読まれず、そこには繊維の印が付かない。

- **パターン 1<!--n:label--> — `[+1, 0, -1]`**: 繊維の片側の斜面を上り、てっぺんで平らになり、
  反対側の斜面を下る並び。平らな区間が `fiber_detect_factor`（既定 10<!--c:lib/pipeline.py::ProcParams.fiber_detect_factor-->）より
  短いときに繊維とみなす。つまり、てっぺんが繊維と言えるくらい狭い場合である。
- **パターン 2<!--n:label--> — `[+1, -1]`**: てっぺんの平らな部分が見えないほど尖った山。
  上りと下りを合わせた長さが `noise_detect_factor`（既定 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor-->）を超えるときに
  繊維とみなす。この条件によって、その長さが既定で 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor--> 画素以下の短い段差は
  ノイズとして捨てられる。

見つかった並びの両端の間にある画素に、すべて繊維の印を付ける。X と Y の結果は、
次の手順で合わせる（どちらかで印が付けば繊維とする）。

コードでは、`l_arr` が各ランの値を、`arg_arr` が各ランの始まる位置を持つ。
パターン 1<!--n:label--> は、0<!--n:label--> のランが `fiber_detect_factor` より短いときに採る。
パターン 2<!--n:label--> は、+1<!--n:label--> のランの始まりから、−1<!--n:label--> のランの次のランの始まりまでが
`noise_detect_factor` を超えるときに採る。Y の走査は、行と列を入れ替えただけの
同じコードである。

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

#### 手順 2 — マスクを掃除して膨らませる

`_bg_generate` は、マスクを使う前に 2<!--n:count--> つの手直しをする。

**小さなかたまりを消す。** 2<!--n:count--> つのパターンは、数画素ほどの大きさのノイズにも
反応する。ノイズの多い画像や広い範囲を撮った画像では、そうした小さな印が画面
全体にびっしり散らばる。1<!--n:count--> 行の中で印が付く長さは、パターン 1<!--n:label--> では最短で
2<!--x:1 + 1 + 1 - 1--> 画素、パターン 2<!--n:label--> では `noise_detect_factor` 画素以上である。したがって既定の
`noise_detect_factor` = 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor--> では、10<!--c:lib/pipeline.py::ProcParams.min_mask_component_area--> 画素より小さなかたまりを作るのはパターン 1<!--n:label-->
だけである。パターン 2<!--n:label--> が小さなかたまりを作るのは、`noise_detect_factor` を
小さくしたとき（`BGCalibrator` のコンストラクタの既定値は 2<!--c:lib/bg_calibrator.py::BGCalibrator.__init__(noise_detect_factor)-->）である。
斜め隣も含めてつながった（8<!--n:literal in the quoted code--> 連結の）かたまりのうち、面積が
`min_mask_component_area`（既定 10<!--c:lib/pipeline.py::ProcParams.min_mask_component_area-->）より小さいものを消す。これをしないと、
次の膨張で 1<!--n:count--> つの誤検出が $(2d+1)^2$ の大きさの穴に広がる。すると作り直した背景
がゴマ塩のようにまだらになり、タイル状・細胞状の模様となって画像に現れる。

**膨らませる。** マスクを `mask_dilation` px（既定 3<!--c:lib/pipeline.py::ProcParams.mask_dilation-->）だけ外側へ広げる。
繊維の*肩*（斜面のすそ）の画素は `_extract_fiber` では拾いきれず、まだ繊維の
高さが少し残っている。これを背景の候補に残すと背景の推定が持ち上がり、
繊維の両脇を引きすぎて、暗い縁取り（ハロー）ができる。

コードの `tri_difx_fill[1:, :]` と `tri_dify_fill[:, 1:]` は、X と Y の地図を合わせる
前に、どちらも「端の画素を削った後の画像」と同じマス目にそろえるためのもので
ある。小さなかたまりを消すのは、膨張が有効（`mask_dilation` > 0<!--n:literal in the quoted code-->）で、しかも
`min_mask_component_area` が 1<!--n:literal in the quoted code--> より大きいときだけである。

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

#### 手順 3 — 穴を埋め、なめらかにして、引く

マスクで隠した画素は、**いちばん近い背景の画素**の値で埋める。いちばん近い
画素を探すのには `scipy.ndimage.distance_transform_edt` を使う。背景の画素にとって
いちばん近い背景の画素は自分自身なので、背景の画素の値はそのまま残る。わざわざ
元に戻す処理はいらない。

埋め終わった面を Savitzky–Golay フィルタ（`savgol_window` 既定 31<!--c:lib/pipeline.py::ProcParams.savgol_window-->、
`savgol_polyorder` 既定 1<!--c:lib/pipeline.py::ProcParams.savgol_polyorder-->）でなめらかにし、トレンドを足し戻す。これが
背景になり、`_bg_calibrate` が元の画像から背景を引く。

`signal.savgol_filter` は配列の最後の軸に沿ってかかる。そのため、なめらかにする
のは各行に沿った方向（X 方向）だけである。

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

`_call_tophat` は、直径 `tophat_se_size`（既定 25<!--c:lib/pipeline.py::ProcParams.tophat_se_size--> px）の円盤（縦横が同じ大きさの
`cv2.MORPH_ELLIPSE`）を使った **opening** で背景を見積もる。opening は、円盤を
高さの地図の下側から押し当てて、円盤が入り込めない細い出っ張りを削る処理である。
円盤より細い繊維は削られて消えるので、残ったものが背景になる。元の画像から
opening の結果を引いた残り `original - opening` は、よく知られた white top-hat
変換にあたる。

この方式では、トレンドの曲面を繊維も含めた全部の画素に当てはめる。トレンドを
引いた画像に opening をかけ、X 方向になめらかにしてから、トレンドを戻す。

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

欠かせないポイントが 2<!--n:count--> つある。

**トレンドを引いた写しに opening をかける。** opening は、画像の内側では平面を
そのまま再現する。しかし画像の端から円盤の半径までの帯では再現できない。
そこでは円盤が画像からはみ出し、opening の前半（収縮）が画像の中に残った部分
だけから最小値を取るので、後半（膨張）で元に戻せないからである。先にトレンドを
引くのは、この端の問題を引き起こす傾きを取り除いておくためである。

**最後に中央値を引いて高さをそろえ直す。** opening は、凹凸の*下側の縁*をなぞる
ような見積もりになる。ノイズのある基板では、ノイズの谷の底に張り付いてしまう。
そのため背景を引いた後の基板の高さは、ノイズの谷の深さの分だけプラス側に
浮く。画像全体の中央値を引いてこれを 0<!--n:definition--> nm に戻し、`global_threshold`、
`low_threshold`、`bp_height` が、ノイズの真ん中を通るように背景を作る他の方式と
同じ意味になるようにする。繊維が画像のおよそ半分より少ない面積しか覆って
いなければ、中央値は繊維に引っぱられず基板の高さを表す。

この方式は繊維のマスクを作らないので、マスク作りの途中の配列も計算しない。
ただし、同じオブジェクトで前に別の方式を実行していると、そのときの値が属性に
残っている。それを間違って使わないように、これらの属性にははっきり `None` を
入れておく。

### 1.5 `spline1d` — ラインノイズ主体の走査向け

`_call_spline1d` は、`trendfill` と同じ繊維のマスクを使う。そのうえで、
`spline1d_axis` が指す向きのライン 1<!--n:count--> 本ごとに、次数 `spline1d_degree`（既定 2<!--c:lib/pipeline.py::ProcParams.spline1d_degree-->）の
1<!--n:definition--> 次元 B スプラインで穴を埋める。ラインどうしは互いに影響しない。`'x'` では
ライン 1<!--n:count--> 本が画像の 1<!--n:count--> **行**、`'y'` では 1<!--n:count--> **列**である。各ラインの穴は、そのライン
自身の値だけから埋めるので、埋めた背景はそのライン独自の高さの水準を保つ。
行が速いほうの走査方向（高速走査軸）である普通の撮り方では、`'x'` のラインは
走査ラインそのものである。このとき保たれる水準は走査ラインごとの高さのずれ
（フィードバックループのドリフトが作る横縞）である。どちらの向きを選んでも、
後の Savitzky–Golay による平滑化は X 方向（行に沿った方向）にしかかからない。

既定の向きは `'x'` である。ラインの中の使える値（有効サンプル）が
`spline1d_degree` + 1<!--n:literal in the quoted code--> 個より少ないとき、または次数が 2<!--n:literal in the quoted code--> より小さいときは、
スプラインの代わりに直線で埋める。

ラインの両端では、わざと**形を外へ延ばさない（外挿しない）**。各ラインの最初と
最後の有効サンプルより外側には、片側にしか背景のデータが無い。そこに 1<!--n:definition--> 次元の
方法で形を置くと（スプラインをそのまま延ばす、直線の傾きを延ばすなど）、その
ラインだけに合わせた形になる。その誤差は延ばす区間が長いほど大きくなり、
しかも隣のラインとは無関係に出るので、ラインごとに勝手な帯模様ができてしまう。
そこで `_spline1d_fill` は、両端の区間を**そのライン自身のいちばん近い
`end_window` 個の背景の値の平均**で一定に埋める。`end_window` には
`savgol_window`（既定 31<!--c:lib/pipeline.py::ProcParams.savgol_window-->）を渡す。既定の `'x'` では、トレンドを引いた後の画像で
ラインごとに残る量は、ほぼ走査ラインの高さのずれだけである。これはラインに
沿って一定なので、平均の高さで一定に埋めれば、傾きを延ばさずにこのずれを
見積もれる（`'y'` のときは、その列の高さの水準を保つことになる）。たくさんの値を
平均するのは、その高さに画素ごとのノイズを持ち込まないためである。有効サンプルが
2<!--n:literal in the quoted code--> 点より少ないラインだけは埋めずに残し、その画素は 2<!--n:definition--> 次元でいちばん近い
背景の画素の値で埋める。

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
| `trendfill`（既定） | ふつうはこれを使う。繊維を背景の候補から外すので、繊維そのものを削ってしまわない。 | 差の分布への当てはめ（`lmfit`）で繊維のマスクを作り、トレンドの当てはめ、穴埋め、平滑化を行う。 |
| `tophat` | 特殊な試料で、繊維のマスク作りが思いどおりに働かないとき。 | 繊維のマスクは作らず、トレンドの当てはめ、opening、平滑化だけを行う。 |
| `spline1d` | ラインノイズ（フィードバックの不調、走査ラインごとの高さのずれ）が目立つスキャン。 | `trendfill` のマスク作りと `_bg_generate` をすべて実行したうえで、ラインごとの 1<!--n:definition--> 次元スプラインによる穴埋めを加える。 |

もう使えない方式（`spline2d`）を選んだパラメータファイルを読み込むと、
`bg_calibrator.BG_METHOD_REMOVED` がその方式の名前を挙げて知らせ、実行を止める。
残っている別の方式に勝手に読み替えることはしない。別の方式に置き換えると、
保存してある `_param.json` で再現できるはずの数値が変わってしまうからである。

---

## 2. 二値化

**コード:** `lib/segmenter.py` — `Segmenter.__call__`。
**読む:** `calibrated_image`。**書く:** `binarized_image`。

この段は、フィルタを順につないだものである。パラメータを調整するときに途中の
結果をそれぞれ確かめられるよう、フィルタごとに別のメソッドになっている。

```text
_binaryzation             -> binary_image
_remove_small_fragments   -> no_small_binary_image
_remove_nonlinear_objects -> no_linear_binary_image
_remove_connecting_fragments（任意） -> no_connecting_binary_image
remove_low_component      -> no_low_binary_image
_recover_missed_ridges（任意）      -> ridge_recovered_image
closing                   -> binarized_image
```

`Segmenter.__call__` は、これらを次の順につないでいる。

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

`_binaryzation` は、**2<!--n:count--> つのしきい値の両方**を超えた画素だけを繊維とする。

$$
\text{mask} = (h > t_{\text{global}}) \;\wedge\; (h > t_{\text{local}}(x,y))
$$

全体のしきい値 `global_threshold`（既定 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm）は、基板から測った高さそのもので
ある。背景補正が欠かせないのは、この値のためである。局所のしきい値は、
`skimage.filters.threshold_local` を窓の幅 `wsize_localbin` px（既定 17<!--c:lib/pipeline.py::ProcParams.wsize_localbin-->）で使ったもので、
画像に残ったゆるやかな高さの変化に合わせて場所ごとに変わる。

両方を満たすことを求めるのは、わざとである。局所のしきい値だけでは、何もない
場所（周りにノイズしかない場所）でノイズを繊維として拾ってしまう。全体の
しきい値がそれを取り除く。一方、「両方」を求めるので、局所のしきい値は、全体の
しきい値を通った画素を減らすことしかできない。残るのは、基板からの高さが全体の
しきい値を超え、しかも周りの重み付き平均より高い画素である。
<!-- TODO(review): 以前ここにあった「大域検定だけでは局所的に沈んだ領域にある繊維を取りこぼす」は、論理積では局所検定がそうした繊維を拾えないため、局所検定を加える理由として成り立たない。局所検定を加えた意図を作者に確認すること。 -->

`skimage.filters.threshold_local` は既定の引数のまま呼んでいるので、局所のしきい値は、
窓の中の値をガウス関数で重み付けした平均（オフセット 0<!--n:library default (skimage.filters.threshold_local offset)-->）である。

```python
# source: lib/segmenter.py::Segmenter._binaryzation
binary_global = image > global_threshold
local_threshold = threshold_local(image, wsize_localbin)
binary_local = image > local_threshold
binary_final = binary_global & binary_local
return binary_final
```

### 2.2 面積フィルタ

`_remove_small_fragments` は、斜め隣も含めてつながった（8<!--n:literal in the quoted code--> 連結の）かたまりの
うち、面積が `area_min`（既定 100<!--c:lib/pipeline.py::ProcParams.area_min--> px²）以下のものを消す。続けて 3<!--n:literal in the quoted code-->×3<!--n:literal in the quoted code--> の
中央値フィルタをかける。これで、ぽつんと孤立した画素が消え、かたまりの縁の
ギザギザがならされる。

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

`_remove_nonlinear_objects` は、かたまりが*線*のような形かどうかを調べる。
繊維は線のような形をしているが、汚れの粒や探針によるアーティファクトはそうでは
ない。

- 面積が 1000<!--n:literal in the quoted code--> px² 以上のかたまりは、調べずに残す。そこまで大きければ、
  答えは調べるまでもないからである。
- かたまりを囲む長方形（バウンディングボックス）が縦も横も `h_length`
  （既定 20<!--c:lib/pipeline.py::ProcParams.h_length--> px）より短いかたまりは消す。必要な長さの線が入りようがないから
  である。
- それ以外のかたまりは、囲む長方形の中で Canny 法で輪郭（エッジ）を取り出し、
  Hough 変換で直線を探す。直線らしさの点数は

  $$
  s_{\text{ratio}} = \frac{\sum \text{Hough ピークの投票数}}{\sum \text{エッジ画素数}}
  $$

  であり、「このかたまりの輪郭のうち、どれだけの割合が直線で説明できるか」を
  表す。$s_{\text{ratio}} <$ `h_sratio`（既定 0.5<!--c:lib/pipeline.py::ProcParams.h_sratio-->）*で、しかも*画素数が 1000<!--n:literal in the quoted code--> より少ない
  かたまりを消す。

輪郭は、囲む長方形の中のマスク全体からではなく、調べているかたまり自身の画素
（`label_image[bbox] == i`）だけから取り出す。囲む長方形は縦横の向きにそろって
いるので、斜めに走る繊維だと長方形は大きくすかすかになり、近くの別のものが
入り込みやすい。マスク全体を切り出すと、それらの輪郭まで $s_{\text{ratio}}$ の
分子と分母の両方に入り、そのかたまりが残るかどうかが「たまたま近くに何が
あったか」で決まってしまう。

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

補足が 2<!--n:count--> つある。1<!--n:label--> つ目に、`h_length` はこの関数の中で 2<!--n:count--> つの役目を持つ。
囲む長方形の判定では画素で測った長さだが、Hough のピークを探す関数の
`threshold` 引数にも渡しているので、そこでは直線とみなすのに必要な最小の投票数
（線の長さの目安）として働く。
2<!--n:label--> つ目に、`target` は調べているかたまりの画素だけなので、その画素数は `area` と
同じである。上の `area >= 1000` の判定で、すでに 1000<!--n:literal in the quoted code--> 画素以上のかたまりは
飛ばされている。したがって `np.sum(target) < 1000` という条件は結果を変えず、
規則を読んで分かるように書いてあるだけである。

### 2.4 弱連結の整理（既定では無効）

`_remove_connecting_fragments` は、マスクを一回り縮め（収縮）、面積が
`area_min_connecting` px²（既定 3<!--c:lib/pipeline.py::ProcParams.area_min_connecting-->）以下のかたまりを消し、膨張で元の太さに
戻してから closing をかける。ねらいは、幅 1<!--n:intent--> 画素の細い橋でつながった破片を
切り離すことである。これが実行されるのは `apply_no_connecting` が真のときだけで、
既定では**無効**である。

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

`remove_low_component` は、背景補正後の画像で見たときに、**いちばん高い点**の
高さが `low_threshold`（既定 1.8<!--c:lib/pipeline.py::ProcParams.low_threshold--> nm）に届かないかたまりを消す。平均ではなく
最大を使うので、細くても本物の繊維は残り、広く薄くにじんだだけのものは
捨てられる。

かたまりごとの最大値は `scipy.ndimage.maximum` で求める。

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

`_recover_missed_ridges` は、ここまでのしきい値処理が*丸ごと*見落とした繊維を
拾うための、2<!--n:count--> 回目の探索である。`ridge_recovery` が真で、しかも画素の大きさが
分かっているときだけ実行する。設定値が実際の長さ（nm）で書かれているからで
ある。

1. **Frangi** フィルタ（血管のような細長い構造を強調するフィルタ）を、複数の
   スケール（見る構造の太さの目安）でかける。スケールは、`ridge_min_width_nm` から
   `ridge_max_width_nm` までを画素に換算した範囲を、等比で 5<!--n:literal in the quoted code--> 段階に分けたもので
   ある。実際の長さで指定するので、1<!--n:count--> つの設定値が、どの解像度のスキャンでも
   同じ大きさの構造を指す。
2. フィルタの出力を**ヒステリシス**（高いしきい値を超えた部分と、そこから
   低いしきい値の上でつながった部分を残す方法）で二値化する。高いしきい値は
   大津法、低いしきい値は三角法で決める。
3. すでに繊維とされたマスクは、つながったかたまりに分ける**前に**差し引く。
   すでにあるマスクにまったく触れていないかたまりだけを拾うやり方だと、長い
   繊維は見つかっている網目に一点でも触れた途端に丸ごと捨てられる。しかも長い
   繊維ほど触れやすい。
4. 残ったかたまりのうち、細線化した画素の数に画素の大きさを掛けた長さが
   `ridge_min_length_nm`（既定 100<!--c:lib/pipeline.py::ProcParams.ridge_min_length_nm--> nm）以上のものだけを採る。

既定で無効にしているのは、保存してあるパラメータファイルで、それが書かれた
当時の数値を再現できるようにするためである。有効にすると、この段の処理時間の
大半を Frangi フィルタが占める。

コードでは、いちばん小さいスケールは 0.6<!--n:literal in the quoted code--> px より小さくならず、いちばん大きい
スケールはいちばん小さいスケールの 1.5<!--n:literal in the quoted code--> 倍以上になる。三角法で決めた値が大津法で決めた値
より小さくならないときは、低いしきい値を高いしきい値の 0.3<!--n:literal in the quoted code--> 倍に置き換える。

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

最後に closing（小さな隙間やくぼみを埋める形態学的な処理）をかける。使うのは
`skimage.morphology.closing` で、なぞる形（構造要素）は既定の十字形である。リッジ回収をその*前*に
行うのはわざとである。回収した線が、すでにあるかたまりのすぐ隣で終わっている
場合に、それが独立した短い繊維として残らず、closing で本体とつながるように
するためである。

---

## 3. 細線化

**コード:** `lib/skeletonizer.py`（形態処理は `lib/imp_tools.py`）。
**読む:** `binarized_image`、`calibrated_image`。
**書く:** `skeleton_image`、`label_image`、`nLabels`、`data`、`ep`、`bp`。

この段の目標は、繊維 1<!--n:count--> 本につき幅 1<!--n:definition--> 画素の線（スケルトン）を得ることである。
難しいのは、細線化は*マスク*の形に忠実に従うのに、そのマスクには欠陥がある
ことである。中の穴、幅のばらつき、繊維の先端の低い裾などである。こうした欠陥は
どれも、スケルトンの上では枝分かれや輪になって現れる。後の段の追跡は分岐点の
たびに繊維を切るので、欠陥から生まれた分岐点は、単にノイズを増やすだけでは
すまない。**本物の繊維をいくつもの断片に切ってしまう**。この段の処理の大半は、
そうした切断を引き起こす欠陥を取り除くためのものである。

`Skeletonizer.__call__` は次の処理を順に実行する。

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
§3.2）。§3.3 と §3.4 で手を加えたマスクは、`skimage.morphology.skeletonize` で
もう一度細線化する。

細線化は、二値化したマスクを**外側から 1<!--n:definition--> 画素分の皮を順にはがしていき**、
それ以上はがせなくなったところで止める。こうして幅 1<!--n:definition--> 画素の線ができる。
細線化が見るのは、各画素が繊維か背景かだけである。高さはまったく見ない。

`skimage.morphology.thin` は、Guo と Hall の並列細線化（1989<!--n:citation-->、*Comm. ACM*
32<!--n:citation-->(3<!--n:citation-->), 359–373<!--n:citation-->）を実装したものである。繊維の画素 $P$ を消すかどうかは、
周りの 8<!--n:definition--> 個の画素 $x_1, \dots, x_8$ で決める。番号は右（東）から反時計回りに
付ける。$x_i$ は、その画素が繊維なら 1<!--n:definition-->、背景なら 0<!--n:definition--> である。

```text
x4  x3  x2        NW  N   NE
x5  P   x1        W   P   E
x6  x7  x8        SW  S   SE
```

次の 3<!--n:count--> つの条件をすべて満たすとき、$P$ を消す（番号は一周するので $x_9 = x_1$）。

**G1 — $P$ を消しても、つながり方が変わらない。**

$$
X_H(P) = \sum_{k=1}^{4} b_k = 1, \qquad
b_k = \begin{cases}
1 & x_{2k-1} = 0 \text{ かつ } (x_{2k} = 1 \text{ または } x_{2k+1} = 1) \\
0 & \text{それ以外}
\end{cases}
$$

$X_H$ は、周りの画素の中で、繊維の画素がいくつのかたまりに分かれているかを
数える。かたまりがちょうど 1<!--n:count--> つなら、$P$ が無くても周りの画素どうしはつながった
ままである。だから $P$ を消しても、かたまりが割れることはなく、穴の数も
変わらない。上下左右の 4<!--n:definition--> 画素に背景が 1<!--n:count--> つも無い画素は $X_H = 0$ となり、
消されない。つまり消えるのは、外側に面した画素だけである。

**G2 — $P$ は線の端でも、切り込みの底でもない。**

$$
2 \le \min(N_1, N_2) \le 3, \qquad
N_1 = \sum_{k=1}^{4} (x_{2k-1} \lor x_{2k}), \qquad
N_2 = \sum_{k=1}^{4} (x_{2k} \lor x_{2k+1})
$$

線の端の画素は隣の画素が 1<!--n:count--> つしかないので $\min(N_1, N_2) = 1$ となり、消されない。
いったん幅 1<!--n:definition--> 画素になった線がそれ以上短くならないのは、このためである。
上限のほうは、周りの 8<!--n:definition--> 画素のうち背景が上下左右のどれか 1<!--n:count--> 画素だけ、という画素
（たとえば幅 1<!--n:definition--> 画素の切り込みの底にある画素）を消さずに残す。

**G3 — $P$ が、今はがしている側にある。** 1<!--n:count--> 回の反復は 2<!--n:count--> 回の小さなステップ
（サブ反復）からなる。1<!--n:label--> つ目のサブ反復では
$(x_2 \lor x_3 \lor \lnot x_8) \land x_1 = 0$ を、2<!--n:label--> つ目では
$(x_6 \lor x_7 \lor \lnot x_4) \land x_5 = 0$ を求める。塗りつぶした長方形で
試すと、1<!--n:label--> つ目は上の端の行と右の端の列を、2<!--n:label--> つ目は左の端の列と下の端の行を
消す。

各サブ反復では、すべての画素を、そのサブ反復を始めた時点の画像で判定する。
つまり、消す画素を先に全部決めてから一度に消す（並列に消す）。2<!--n:count--> つのサブ反復を
交互に繰り返し、1<!--n:count--> 回の反復で何も消えなくなったら終わる。判定は、周りの画素の
並び方 256<!--x:2 ** 8--> 通りのそれぞれについて「消す／消さない」を書いた表を引くだけで
ある。配列の外側は背景として扱う。そのため、スキャンの範囲の外へ続いている
繊維も、画像の端で終わっているものとしてはがされる（§3.2）。

幅 5<!--n:example--> 画素の帯に、1<!--n:example--> 画素の穴と、上の辺から 2<!--n:example--> 画素突き出た出っ張りを付けたマスク
（左。`#` が繊維）に `skimage.morphology.thin` をかけると、右のスケルトンになる。

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

この例には、細線化の 4<!--n:count--> つの性質が表れている。この段のこの後の処理は、どれも
この性質への手当てである。

- **線は真ん中を通る。** 両側から 1<!--n:definition--> 枚ずつ皮をはがすので、線は両側のマスクの
  縁のちょうど中間、つまり幅 5<!--n:example--> 画素の帯の真ん中の行に残る。厳密な中軸変換
  （`skimage.morphology.medial_axis`。ここでは使っていない）と同じものではないが、
  このページで「スケルトンはマスクの medial axis（中心軸）を通る」と書くときは、
  この性質のことを言っている。
- **つながり方（位相）はそのまま保たれる。** マスクの 1<!--n:count--> つのかたまりは 1<!--n:count--> つの
  かたまりのまま残る。穴は、それを囲む閉じた輪になる（穴の周りのひし形）。§3.4 が
  この輪をつぶす。
- **出っ張りはすべて枝になる。** 出っ張りも両側からはがされて真ん中で止まるので、
  繊維の本体と同じように線が残る。上の辺の出っ張りから枝が出ているのがそれで
  ある。§3.3 と §3.5 がこれを刈り取る。
- **太い端は縮むが、線の端は縮まない。** 帯は、先端が幅 1<!--n:definition--> 画素になるまで両端から
  短くなり、そこから先は G2 のおかげで残る。先端に低く広い裾があると、線は
  その裾の中へ向かって細線化される（§3.6）。

高さを使う処理は、すべて細線化の後に加えている。§3.3 の枝刈り、§3.4 のループの
高さチェック、§3.6 のフック切除、そして §4.2 の中心線である。

`skimage.morphology.skeletonize`（2<!--n:definition--> 次元の画像では、既定で Zhang と Suen の細線化。
1984<!--n:citation-->、*Comm. ACM* 27<!--n:citation-->(3<!--n:citation-->), 236–239<!--n:citation-->）は、やはり 2<!--n:count--> つのサブ反復からなる、別の
細線化である。この段でこれを使うのは、§3.3 と §3.4 が手を加えたマスクを
もう一度細線化するときだけである。そのマスクは、手を加えた場所以外はすでに
幅 1<!--n:definition--> 画素になっている。上の例の `skimage.morphology.thin` の結果にかけても、
何も変わらない。ただし太いマスクでは 2<!--n:count--> つの結果が違うことがある（上の例のマスク
では線の右端が違う）。そのため、最初のスケルトンは必ず
`skimage.morphology.thin` で作る。

### 3.2 画像端で繊維を切らずに細線化する

`thin_ignoring_image_border` は、画像の端の画素を `DEFAULT_BORDER_PAD` = 12<!--c:lib/skeletonizer.py::DEFAULT_BORDER_PAD--> px 分
外側へ書き写して画像を広げ、細線化してから、広げた分を切り落とす。

`skimage.morphology.thin` は配列の外側をすべて背景として扱う。そのため、画像の
外へ抜けていく繊維は、画像の端でスパッと切られた形になる。すると、その切り口の
中心軸は、切り口の近いほうの角へ向かって曲がり、線は繊維の端で尾根から外れて
しまう。端の画素を外側へ書き写せば、繊維は端で切られずに外側へ延びるので、
この曲がりは起きない。

ただし書き写すと、端を横切らずに端に*沿って*延びているかたまりが太くなり、
その中心軸が動くことがある。幅の広いかたまりでは、書き写した帯より内側（画像の
中央寄り）にある軸まで動く。幅の狭いかたまりでは、軸が画像の外に押し出されて
しまうことさえある。そこで、広げた版で細線化するとスケルトンが消えてしまう
かたまりについては、広げずに細線化した結果を使う。この手直しで繊維が
失われることはない。

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

ここでは、枝を刈るかどうかを分岐点の高さで決める。高さを使う掃除はほかにも
§3.4 のループの高さチェックと §3.6 のフック切除があるが、分岐点を高さで分ける
のはここだけである。

`set_low_bp_coor` は、背景補正後の高さを `bp_height`（既定 10<!--c:lib/pipeline.py::ProcParams.bp_height--> nm）と比べて、
スケルトンの分岐点を**低い**ものと**高い**ものに分ける。後で説明する探索で腕が
刈られるのは、低い分岐点にたどり着いたか、行き止まりになったときだけである。
高い分岐点に接した腕は残る。
<!-- TODO(review): bp_height が何を分けるためのものか、作者の確認が要る。 -->

```python
# source: lib/skeletonizer.py::Skeletonizer.set_low_bp_coor
all_bps = imp_tools.branchedPoints(init_skeleton_image)
low_bp_coor = np.where(all_bps & (calibrated_image < bp_height))
high_bp_coor = np.where(all_bps & (calibrated_image >= bp_height))
```

`get_close_eps` は、低い分岐点から `branch_length` px（既定 12<!--c:lib/pipeline.py::ProcParams.branch_length-->）以内にある
端点を探す。短い偽物の枝でありうるのは、そうした端点から伸びる枝だけだから
である。

「以内」の範囲は、低い分岐点それぞれの周りに、大きさ $2k$ の
`scipy.ndimage.maximum_filter` をかけて作る（$k$ = `branch_length`）。

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

`track_branches` は、それぞれの端点からスケルトンを最大 `branch_length` 歩だけたどる。
低い分岐点にたどり着いたとき、または分岐点に着く前に行き止まりになったとき
（ぽつんと離れた短い切れ端）は、その腕を**刈る**。高い分岐点に接したときと、
歩数の上限まで歩ききったときは、短くて低い枝だと確かめられないので**残す**。

コードでは `x` が行、`y` が列である。各歩では、まず行き止まりかどうか、次に
低い分岐点に接しているか、最後に高い分岐点に接しているかを調べる。どれも、
今いる画素の周りの 3<!--n:definition-->×3<!--n:definition--> 画素で調べる。腕を刈るときは、それまでにたどった画素を
枝として記録する。

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

この探索は、わざと次の 2<!--n:count--> つの性質を持たせてある。

- 探索は、画像全体の上を、画像の範囲をはっきり確かめながら歩く。そのため、端点の
  周りの小さな範囲の外へ続いている繊維を、行き止まりと読み違えることはない。
- 探索ごとに、「もう通った画素」の記録を別々に持つ。そのため、先に調べた端点の
  探索が、後の探索からスケルトンを隠してしまうことはない。結果は、どの端点から
  調べたかの順番によらない。

画像の端から `branch_length` 以内にある端点は調べない。端の近くで終わる腕は、枝の
先ではなく、画像の外へ抜けていく繊維だからである。

枝を刈った後のマスクは、もう一度細線化して幅 1<!--n:definition--> 画素に戻す。

```python
# source: lib/skeletonizer.py::Skeletonizer.prune_branches
branches_image = self.calc_branches_image(calibrated_image, init_skeleton_image)
return init_skeleton_image - branches_image
```

### 3.4 ループアーティファクトを潰す

`collapse_skeleton_loops` は、スケルトンに**ぐるりと囲まれた**背景の領域を探す。
スケルトンは斜めも含めて（8<!--n:definition--> 連結で）つながっているので、背景のほうは上下左右
だけで（4<!--n:literal in the quoted code--> 連結で）つながったかたまりに分ける。こうすると、囲む長方形が画像の端に
触れていないかたまりが、本当の穴である。面積が `max_loop_area`
（既定 100<!--c:lib/pipeline.py::ProcParams.max_loop_area--> px²）以下の穴を塗りつぶしてから細線化し直し、二重になった経路を
1<!--n:count--> 本の線に戻す。

二値マスクの中の穴は、つながり方を保つ細線化では、穴を囲む二重の経路として
残り、その輪の上に分岐点を作る。細線化し直しても、すでに細い線は変わらない。
そのため、塗りつぶした場所から離れたスケルトンの画素は、同じ位置に残る。キンクや
端点のように画素の位置で決まる点も、そうした場所では変わらない。

この処理で本物の繊維 2<!--n:count--> 本がくっついてしまわないように、**高さのチェック**を
入れている。ループのアーティファクトは繊維の本体の中か交差にあるので、囲まれた
内側も高いままである。一方、別々の繊維 2<!--n:count--> 本が 2<!--n:count--> か所で触れて囲んだ細長い隙間なら、
背景の高さの画素を含んでいるはずである。そこで、内側の高さの中央値が、周りの
尾根（スケルトン）の高さの中央値の `DEFAULT_LOOP_HEIGHT_RATIO` = 0.3<!--c:lib/skeletonizer.py::DEFAULT_LOOP_HEIGHT_RATIO--> 倍以上の
ときだけ塗りつぶす。間違って塗りつぶすと 2<!--n:count--> 本がくっつき、その間の溝の真ん中に、
実在しない経路ができてしまう。
<!-- TODO(review): 0.3 がループと隙間を分けられるかは確かめていない。 -->

コードでは、周りの尾根（`ring`）を、穴を 5<!--n:literal in the quoted code-->×5<!--n:literal in the quoted code--> で膨らませた範囲に入るスケルトンの
画素とする。比べる 2<!--n:count--> つの高さは、どちらも中央値である。

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

`prune_short_spurs` は、片方が行き止まりの端点で、もう片方が分岐点につながって
いる、長さ `spur_length`（既定 12<!--c:lib/pipeline.py::ProcParams.spur_length--> px）以下の短いとげ（スパー）を取り除く。

§3.3 と違って高さを使わず、**形（長さ）だけで判断する**。ここが肝心な点である。
繊維の本体から生えたとげは繊維と同じ高さにあるので、高さのしきい値では本物の
交差と見分けられない。しかし長さの上限なら見分けられる。本物の繊維の腕が
そこまで短いことはめったにないからである。届く範囲に分岐点が無い、ぽつんと
離れた短い切れ端は残す。端点が画像の端から `border_margin` = 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px 以内にある腕は、
決して刈らない。§3.3 と同じく、端の近くで終わる腕は、枝の先ではなく画像の外へ
続く繊維かもしれないからである。さらに、画像の端のすぐ手前で触れ合う 2<!--n:count--> 本の
繊維は本物の合流点を作っており、その短い腕を刈ると 2<!--n:count--> 本がくっついてしまう。

ここでいう合流点とは、スケルトン上で隣の画素を 3<!--n:literal in the quoted code--> つ以上持つ分岐点である
（`_junction_degree`）。たどっている途中で道が分かれていたら、刈らずに止まる。
とげが 1<!--n:count--> 本も取り除かれなくなるまで、画像全体についてこれを繰り返す。

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

`prune_terminal_hooks` は、ここまでの 3<!--n:count--> つの処理のどれでも見つけられない欠陥を
扱う。二値化で、繊維の先端にある低く広がった「裾」までマスクに入ってしまうと、
細線化はその中心軸を裾のほうへたどり、裾の縁に沿って回り込む。その結果、
**分岐点の無い釣り針のような曲がり（フック）**が線の端に残る。枝刈りには分岐点が、
とげの除去には合流点が、ループつぶしには閉じた穴が必要だが、フックはそのどれも
持たない。

フックは、端点の近くで線の向きが折り返していることで見つける。端から
`DEFAULT_HOOK_LENGTH` = 12<!--c:lib/skeletonizer.py::DEFAULT_HOOK_LENGTH--> px 以内で、折れ曲がりの頂点の内角が
`DEFAULT_HOOK_APEX_ANGLE_DEG` = 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度より小さくなる場合である。切り取るのは、背景補正後の
高さが、隣に続く繊維本体の高さの中央値の `DEFAULT_HOOK_HEIGHT_RATIO` = 0.5<!--c:lib/skeletonizer.py::DEFAULT_HOOK_HEIGHT_RATIO--> 倍より
低くなっている画素だけである。したがって、折れ曲がっていても高さが本体のこの
割合以上ある端は切られない。

頂点の角度の 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度は、キンク判定のしきい値 150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg--> 度よりずっと鋭いので、キンク
検出の邪魔をしない。切り取る量は、見つかったいちばん奥の折り返し点までに
限られるので、まっすぐなまま薄れていく端が短くされることはない。

マスクが裾を含んでいる以上、フックはそのマスクの中心軸としては正しい。その
ため、細線化の研究でよく使われる、白黒の形だけから枝の大事さを測る方法では
見分けられない。見分けるには高さの情報が要る。そこでこの処理は、濃淡のある
画像を手がかりに繊維をたどる方法と同じ考え方を使う。「繊維の中心線は高さの
尾根の上になければならない」という考え方である。

コードでは、各端点から線を最大 30<!--x:12 + 6 + 12--> px たどる（`_walk_from_endpoint`）。たどった
経路の $j$ 番目の点（$j \le 12$）での頂点の角度は、6<!--c:lib/skeletonizer.py::_HOOK_DIRECTION_WINDOW--> 歩先の点（$j + 6$）へ向かう
ベクトルと、端点へ戻るベクトルとのなす角である。この角度が 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度より小さく
なる $j$ のうち、いちばん奥のものを頂点とする。本体の高さは、頂点より先の
12<!--c:lib/skeletonizer.py::_HOOK_BODY_WINDOW--> 画素の高さの中央値である（4<!--n:literal in the quoted code--> 画素以上必要）。端点から順に、高さがその半分
より低いあいだだけ画素を取り除く。ただし頂点とそれより先は取り除かない。

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

`remove_small_and_ring` は、`min_area`（既定 10<!--c:lib/pipeline.py::ProcParams.min_area--> px）より小さいかたまりと、
**端点を 1<!--n:count--> つも持たない**かたまりを取り除く。端点の無いかたまりは閉じた輪であり、
端から端へたどる繊維の追跡ではたどれない。

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

`imp_tools.endPoints` と `imp_tools.branchedPoints` は、スケルトンの各画素の周りの
3<!--n:definition-->×3<!--n:definition--> 画素を、端点や分岐点の並び方のひな形と照らし合わせて（hit-or-miss、
`cv2.MORPH_HITMISS`）分類する。できた `ep`（端点）と `bp`（分岐点）の地図は
バンドルに保存され、後の追跡や、`measure.isolated_fiber_flags` の孤立判定が使う。

照らし合わせる前に、スケルトンの外側を背景の画素 1<!--n:literal in the quoted code--> つ分で囲む。そのため、
画像の縁にある画素は、スキャンがそこで終わっているものとして分類される。

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
`KinkDetector.kinks_on_line`。判定は、`lib/centerline.py` が置く中心線（§4.2）の
上で行う。
**読む:** `skeleton_image`、`calibrated_image`、`bp`。**書く:** かたまり（ラベル）
ごとのキンクの配列、端のそばで判定しなかった折れ（§4.4）、およびそれらを
1<!--n:count--> 列にまとめた配列。

キンクとは、繊維が**一か所で鋭く折れているところ**であり、なだらかな曲がりとは
区別する。見つけるには、何を「鋭い」とみなすかを決めなければならない。見落と
しやすいが、どれくらいの大きさの目で見るか（尺度）も決めなければならない。
画素の細かさで見れば鋭い折れでも、繊維の太さくらいの目で見ればなだらかな曲がり
かもしれないからである。ここでは、繊維の見かけの幅 $W$（§4.2）を尺度にする。
$W$ は、探針で撮った画像でどこまで細かいものを見分けられるか（分解能）の目安
でもある。

`KinkDetector.__call__` は、追跡したかたまりごとに中心線を置いて判定する。キンクは
中心線（`placed.x`、`placed.y`）の上で判定し、同じ番号のスケルトンの画素の位置に
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

`imp_tools.remove_bp` は、各分岐点を中心とする一辺 $(2r+1)$ の正方形（$r$ =
`remove_size` = 1<!--c:lib/imp_tools.py::remove_bp(remove_size)-->）の画素を消す。こうして交差のところでスケルトンを切り、残った
かたまりがどれも枝分かれの無い 1<!--n:count--> 本の線になるようにする。`min_area` = 10<!--c:lib/imp_tools.py::remove_bp(min_area)--> px より
小さいかたまりは捨てる。続いて `imp_tools.remove_Lcorner` が、偽物の折れとして
数えられかねない、2<!--n:definition--> 画素の L 字の角を取り除く。

つながったかたまりごとに、`imp_tools.tracking` が一方の端点からもう一方の端点まで
歩き、画素の位置を**並び順どおりに**返す。端点がちょうど 2<!--n:literal in the quoted code--> 個ではないかたまりは
たどれないので、画像全体の処理は止めずに、ログに書いてそのかたまりだけ飛ばす。

`imp_tools.remove_Lcorner` のひな形では、1<!--n:definition--> のマスはスケルトン、0<!--n:definition--> のマスは背景
でなければならない。したがって取り除かれるのは、2<!--n:count--> 本の腕が上下左右の隣にある
L 字の角の画素である。取り除くと、L 字は斜めの段差になる。`imp_tools.tracking` は、
画像を左上から行ごとに読んだとき（ラスタ順）に先に来る端点から出発する。各歩では、
周りの 3<!--n:literal in the quoted code-->×3<!--n:literal in the quoted code--> の窓をラスタ順に見て最初に見つかった残りの画素へ進み、今いた
画素は消す。

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

`remove_bp` が分岐点の周りを消してから追跡するので、キンク検出にも、同じ追跡の
経路を使う高さの読み取りにも、分岐点のすぐ近くの画素は入らない。これはねらい
どおりである。交差しているところの高さは、どれか 1<!--n:count--> 本の繊維だけのものではない
からである。

### 4.2 繊維の中心線を高さの上に置く

**コード:** `lib/centerline.py` — `centerline.place_centerline`。

追跡したスケルトンは、どの画素が 1<!--n:count--> 本の繊維に属し、どんな順に並ぶかを決める。
しかし、繊維が*どこを*通っているかを表すものとしては正確ではない。スケルトンは
二値化したマスクの中心軸なので、マスクの両側の縁のちょうど中間を通る。隣の繊維、
分岐のところの裾、背景のでこぼこのどれかがマスクを片側だけ広げると、軸もそれに
つられて動く。さらに、斜め隣も含めてつながった画素の列（8<!--n:definition--> 連結の画素の鎖）なので、
階段のようなギザギザも加わる。その結果、マスクがたまたま広がっただけの
まっすぐな繊維に、折れが現れてしまう。

そこでキンクは、スケルトンの画素ではなく、繊維の高さの上に置いた**中心線**で
判定する。どの画素が 1<!--n:count--> 本の繊維に属すかは引き続きスケルトンが決め、中心線は、
その各点をどこに置くかだけを決める。

#### 中心線の置き方

既定の方式では、スケルトンの各点を、次の 5<!--n:count--> つの手順で繊維の高さの上へ動かす。

1. `centerline.measure_apparent_width` が、繊維の見かけの幅 $W$ を測る。トラックに
   沿って、繊維を横切る向きに高さの断面をとり、それぞれの半値全幅（ふもとから測って、
   山の高さの半分以上ある部分の幅）を求め、トラック全体での中央値をとったものである。
   この後の手順の長さはすべて $W$ の何倍かで決めるので、スキャンの大きさが
   違っても同じ意味になる。
2. トラックを $W/4$ の幅でなめらかにし、これを**枠**とする。枠の各点は、その点の
   横方向の位置を測るときの原点になる。枠の向きからは、測る方向（繊維に直角な
   方向、法線方向）が決まる。なめらかにした位置をそのまま中心線にはしない。
   そうすると本物の角まで丸まってしまうからである。中心線の位置は、次の手順で
   高さから測った横方向のずれ（オフセット）で決まる。
3. `centerline.refine_centerline` が、その法線に沿って枠の点から坂を上り、いちばん
   近い高さの山のてっぺん（極大）を見つける。届く範囲でいちばん高い点を選ぶわけ
   ではないので、もっと高い隣の繊維に中心線を横取りされることはない。そのうえで
   点を、**断面の高さが、ふもと（基底）と山のてっぺんのちょうど中間の高さ（半値）まで
   下がる 2<!--n:count--> つの位置の真ん中**に置く。
4. この 1<!--n:count--> 本の繊維の位置を決められない断面には「信頼できない」と印を付け、その
   オフセットは測らずに、周りの信頼できる点から補間する。たとえば、分岐点から
   $W$ 以内の断面、幅が $1.5\,W$ を超える断面（繊維が 2<!--n:count--> 本並んでいる）、見つけた
   山がトラックの載っている断面のものではない断面、探す範囲の中で半値まで
   下がる位置が見つからない断面、信号が弱すぎる断面がこれにあたる。各点の
   オフセットは、隣り合う点どうしの差（1<!--n:definition--> 階差分）が大きいほど罰を与える
   平滑化（Whittaker 平滑化）で、トラックに沿ってなめらかにつなぐ。罰の強さは、
   なめらかにする幅が $W/4$ になるように決める。
5. 中心線の各点を、枠の点から法線方向にそのオフセットだけ動かした位置に置く。
   ただし、画像のいちばん外側の画素の中心より外には出さない。スキャンの範囲の
   外へ続く繊維では、手順 2〜4<!--n:label--> が最後の点を画像の縁の外（高さを測っていない
   位置）へ運んでしまうことがあるからである。

計算の各手順は、コードと一緒に [GUI04 のファイバー計測](gui04_measurements.ja.md)
§2 で説明している。キンク検出も同じ関数を呼ぶ。

```python
# source: lib/centerline.py::place_centerline
width, measured = measure_apparent_width(height, x, y, return_measured=True)
lx, ly, reliable, crest = _refine(height, x, y, width, branch_points, method)
return CenterlineResult(lx, ly, float(width), bool(measured), reliable, crest)
```

できあがった中心線は、スケルトンの点 1<!--n:count--> つにつき、ちょうど 1<!--n:count--> つの点を持つ。
そのため、中心線の上で判定したキンクを、バンドルにはスケルトンの画素として保存
できる。また、描画と計測はすべて中心線を使いつつ、除外や連結の対象は
これまでどおりスケルトンの画素で指定できる。

前処理（GUI01 と `cli.py process`）は、キンクを判定するときにこの関数で中心線を
作る。`fiber_tracking_image.FiberTrackingImage` は、バンドルを開くときに同じ関数で
中心線を作り直す。だから、画面に出るキンクと、それが載っている中心線は、同じ
1<!--n:count--> つの計算から来ている。バンドルをどの中心線で組み立て直すかは、バンドルの
形式で決まる（`bundle_schema.centerline_from_meta`）。

| バンドルの形式 | キンクを判定した線 | 組み立て直すときに使う線 |
|---|---|---|
| 1.2<!--n:bundle format version--> | `bundle_schema.CENTERLINE_KEY` に記録された中心線 | その中心線 |
| 1.1<!--n:bundle format version--> | 半値中点の中心線 | 半値中点の中心線 |
| 1.0<!--n:bundle format version--> | スケルトントラック | 再解析されるまでスケルトントラック |

#### 中心線と一緒に返すもの

`centerline.place_centerline` は、中心線と一緒に、その上で計算する数値を左右する
3<!--n:count--> つの情報を、`centerline.CenterlineResult` として返す。

- **$W$ と、それが実際に測った値かどうか。** キンク判定の規則の長さは、すべて
  $W$ の何倍かで決まる。$W$ には繊維そのものの幅だけでなく、探針による広がりも
  含まれる。つまり $W$ は、その繊維のキンクを判定したときの、実際の物差しの
  大きさである。使える半値の区間を持つ断面が少なすぎるときは、代わりに
  `centerline.FALLBACK_WIDTH_PX`（8<!--c:lib/centerline.py::FALLBACK_WIDTH_PX--> px）を使う。これは繊維の幅をもとにした値では
  なく、ただの画素数なので、代わりの値を使ったことを隠さずに知らせる。各繊維は
  自分の $W$（`Fiber.width_px`、`Fiber.width_measured`）をファイバー一覧と CSV に
  渡す。バンドルには、画像全体での $W$ の中央値と、代わりの値を使ったかたまりの数を
  記録する（`bundle_schema.APPARENT_WIDTH_KEY`）。
- **どの点の位置を実際に決められたか。** 手順 4<!--n:label--> で補間した点は、まっすぐな
  区間の上に並ぶので、そこではキンクも曲率も見つけられない。点ごとの印
  （`Fiber.line_reliable`）は、中心線のうち実際に繊維の上で位置を決められた点の
  割合として、一覧と CSV に出る。
- **頂点高さ。** 各点での繊維の高さには、中心線の位置で画像から補間した値では
  なく、**断面のいちばん高い値**（`CenterlineResult.crest`）を使う。中心線は半値の
  真ん中にあるので、左右が非対称な断面では、てっぺんの真上ではなく横にずれる。
  また双線形補間では、画素の中心と中心の間にあるてっぺんの高さに届かない。
  <!-- TODO(review): 頂点高さも断面を双線形補間した標本の最大値なので（centerline._refine）、画素中心の間にある頂点に届かない点は頂点高さも同じであり、この文は頂点高さを選ぶ理由として区別になっていない。意図を作者に確認すること。 -->
  断面を決められなかった点では、補間した
  点から $W/4$ 以内でいちばん高い値を使う。`Fiber.height`、高さプロファイル、
  すべての高さの統計は、この頂点高さを使う。

#### 別の中心線を選ぶ

1/4 幅でなめらかにした半値の中点は既定の方式であって、ほかに選べないわけでは
ない。既定の方式は、合成データと同梱スキャンでの比較を見て、経験的に選んだもの
である（[個別データでの評価](validation.ja.md) §4.2、§4.3）。`centerline_method`
（GUI01 の Kinkdetector グループ、`cli.py process --centerline`）で、
`centerline.CENTERLINE_METHODS` にある 8<!--c:lib/centerline.py::len(CENTERLINE_METHODS)--> 種類の中心線から 1<!--n:count--> つを選べる。
利用者が自分の画像でこの選び方を確かめられるようにするためである。どの中心線も、
どの画素が 1<!--n:count--> 本の繊維に属すかについてはスケルトンの判断をそのまま使い、
スケルトンの点 1<!--n:count--> つにつき 1<!--n:count--> つの点を返す。断面の読み方（山のてっぺんへ上ること
と、半値の高さで信頼できるかを判定すること）は共通で、主に違うのは各点を置く
位置である。ただし例外が 2<!--n:count--> つある。`"half_max_05w"` は、枠とオフセットを
なめらかにする幅が $W/2$ である。`"quarter_max"` と `"centroid"` は、自分が読む高さまで
断面が下がる位置が、探す範囲の中で左右のどちらかでも見つからない断面を、信頼
できない点として補間する。そのため、信頼できる点と、それにつれて頂点高さ
（信頼できない点では近くのいちばん高い値を使う）が、既定の方式と違うことがある。
それぞれのコードは
[GUI04 のファイバー計測](gui04_measurements.ja.md) §2.8 に引用している。

次の表は、それぞれの中心線が点をどこに置くかをまとめたものである。

| `centerline_method` | 各点を置く位置 |
|---|---|
| `"half_max_025w"`（既定） | 半値の中点。枠とオフセットを W/4 の幅でなめらかにする |
| `"half_max_05w"` | 同じく半値の中点。なめらかにする幅は 0.5<!--c:lib/centerline.py::_WIDE_SMOOTH_WIDTHS--> W |
| `"skeleton_pixels"` | スケルトンの画素そのもの |
| `"smoothed_skeleton_05w"`、`"smoothed_skeleton_1w"` | スケルトンを長さ方向に 0.5<!--n:definition--> W / 1<!--n:definition--> W の幅でなめらかにしたもの |
| `"quarter_max"` | 高さが 1/4 になる 2<!--n:count--> 点の中点 |
| `"centroid"` | ふもと（基底）より上の高さで重みを付けた重心 |
| `"crest"` | 断面のいちばん高い位置（放物線を当てて、標本と標本の間まで求める） |

なお、断面の形が向きによって違う（異方的な）フィブリルは、ねじれるにつれて、
いちばん高い縁を左右交互に向ける。探針が太いと、この片寄りは画像そのものに
含まれてしまい、高さから読み取るどの中心線でも取り除けない。

キンク判定の規則とその長さ（W の何倍か）は、どの中心線でも同じである。その
ため、既定の方式より横方向のノイズが大きい中心線は、それだけで折れを多く
報告する。長さ・高さ・キンクはすべて中心線の選び方で変わるので、違う中心線で
得た結果どうしを比べることはできない。

### 4.3 各折れを超過回転で判定する

**コード:** `KinkDetector.judge_line`（`KinkDetector.kinks_on_line` はその
結果をタプルで返す形）。

#### 超過回転規則

この規則は、中心線の向き $\theta(s)$ を使う。中心線に沿った長さ（弧長）$s$ で
0.5<!--c:lib/kink_detector.py::_HEADING_STEP_PX--> px ごとに点を取り直し、各点での向きを、幅 $\sigma = W/4$ のガウス関数で
なめらかにしたものである（`kink_detector._heading_profile`）。位置 $p$ では、$p$ を
中心とする窓の中で中心線がどれだけ向きを変えるかを、窓のすぐ外側で繊維が
もともとどれくらいの割合で向きを変えていたかと比べる。

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

$T$ は、窓の中で向きが変わった角度（回転角）である。$r_{\text{L}}$ と $r_{\text{R}}$ は、
窓の左右の脇で、長さあたりどれだけ向きが変わっているか（回転率）である。$E$ を
**超過回転**と呼ぶ。窓の中での回転のうち、「脇と同じ割合で回り続けただけ」では
説明できない分である。折れは

$$
E \ge 180^\circ - \theta_{\text{max}}
$$

のときキンクと判定する。$\theta_{\text{max}}$ は `kinkangle_deg`（既定
150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg--> 度）なので、既定では超過回転が 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v--> 度以上必要である。しきい値を内角
（折れの内側の角度）で表すのは、形式 1.0<!--n:bundle format version--> のバンドルに使う折れ線規則（§4.6）も、
同じ `kinkangle_deg` を内角のしきい値として読むからである。
`pipeline.build_stages` が、検出器に渡す前にラジアンに直す。キンクとして*保存
する*角度は、これとは別に、折れの両側の腕の向きから測る（後の「報告する角度」を
参照）。

**なぜ回転そのものではなく超過回転を使うのか。** 窓の中の回転だけを見ると、
キンクだけでなく、なだらかな曲がりまで拾ってしまう。たとえば半径 $3\,W$ の円弧は、
$1.5\,W$ 進むあいだに 29<!--x:degrees(2 * 0.75 / 3)--> 度も向きを変える。しかし円弧は、窓の中でも両脇でも
同じ割合で曲がるので、超過回転はほぼ 0<!--n:analytic (an arc turns at one rate)--> になる。一方、まっすぐな腕にはさまれた
角では、窓の中の回転がそのまま残る。両脇の回転率のうち*小さいほう*を使うのは、
曲線が終わるところにある角では、片方の脇は曲がっていてもう片方はまっすぐだが、
それでも角であることに変わりはないからである。どちらかの脇が逆向きに曲がって
いる場合（階段のような段差をつくる 2<!--n:label--> つ目の折れ）は、何も差し引かない。

コードでは、`_heading_profile` が点の取り直し・向きの計算・なめらかにする処理を
行い、`excess_profile` が好きな位置で $T$ と $E$ を計算する。端の近くでは脇の
区間が中心線の端で切れて短くなるが、割る長さは $f$ のままである。位置 $p$ を
採るのは、次の条件をすべて満たすときだけである。

- 両端から $c$ 以上離れている。
- $|T(p)|$ がしきい値以上である。
- $E(p)$ が、しきい値とノイズ床（後の「尺度とノイズ床」で説明する）の両方以上
  である。`NOISE_SIGMAS` が 0<!--c:lib/kink_detector.py::NOISE_SIGMAS--> のあいだは、ノイズ床は 0<!--c:lib/kink_detector.py::NOISE_SIGMAS--> である。

しきい値は、ラジアンで表した $\pi - \theta_{\text{max}}$（`turn_threshold`）である。

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

$E$ は、候補の位置でだけ計算する。候補は 2<!--n:count--> 種類ある。

- **曲率がまわりより大きくなる点（曲率の極大）。** 曲率 $|d\theta/ds|$ の極大の
  うち、下限以上のもの。下限は、しきい値ちょうどの折れが窓全体で持つ平均の
  曲率の半分、つまり $0.5 \times (\pi - \theta_{\text{max}}) / (2c)$ である
  （`_CURVATURE_FLOOR_FRAC` = 0.5<!--c:lib/kink_detector.py::_CURVATURE_FLOOR_FRAC-->）。
- **$|T|$ そのものの極大。** ただし、$0.75\,W$ 以内に、上の曲率の極大から採った
  候補が無い場所だけに加える。ノイズで曲率の山が 2<!--n:count--> つに割れてしまった角や、
  回転がそのまま曲線へ続いていく角では、真ん中に曲率の極大が 1<!--n:count--> つも無いから
  である。両端から $c$ 以上離れた点（`grid`）の上で探す。

$0.75\,W$ より近い候補どうしは、1<!--n:count--> つの折れとみなす。候補を超過回転の大きい
順に処理するので、そうした組の中では超過回転がいちばん大きいものが残る。

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

キンクとして*保存する*角度（`ka`）は、180<!--n:definition--> 度から超過回転を引いた値ではない。
折れの両側にある 2<!--n:count--> 本の**腕**がなす内角である（`KinkDetector.judge_line`）。各腕の
向きは、頂点から半幅離れたところ（探針が頂点を丸めてしまう範囲の外側）から
1<!--c:lib/kink_detector.py::_ARM_LENGTH_WIDTHS--> 幅の長さの区間で平均した向きである。区間は次の折れの手前で打ち切る。
こうして、段差をつくる 2<!--n:label--> つ目の角が、1<!--n:label--> つ目の折れの腕に入り込まないように
する。

超過回転も、角度の隣に `ke` として保存する（§4.5）。判定に使った量と折れの形の
両方が、バンドルと一緒に残る。

**腕のなす角の計算のしかた。** 長さ $L$ の中心線の上で、弧長の位置 $p$ にある
折れを考える。$g = 0.5\,W$（`_ARM_GAP_WIDTHS`）、$a = 1.0\,W$
（`_ARM_LENGTH_WIDTHS`）とすると、2<!--n:count--> 本の腕は次の弧長の区間である。

$$
A_{\text{L}} = \bigl[\max(s_0,\ p - g - a,\ p_{\text{prev}} + g),\ p - g\bigr],
\qquad
A_{\text{R}} = \bigl[p + g,\ \min(s_1,\ p + g + a,\ p_{\text{next}} - g)\bigr]
$$

ここで、

- $s_0$ と $s_1$ は、向きを求めた最初の点と最後の点の位置である（始まりの端から
  0.25<!--x:0.5 / 2--> px、終わりの端から 0.25〜0.75<!--x:[0.5 / 2, 0.5 * 1.5]--> px 内側）。
- $p_{\text{prev}}$ と $p_{\text{next}}$ は、同じ中心線の上に残した折れのうち、
  前後でいちばん近いものである（判定したかどうかは問わない）。無ければ、その項は
  使わない。

各腕の向き $\bar\theta$ は、区間の中に等間隔に取った 16<!--n:literal in the quoted code--> 点で、なめらかにした後の
向きを読み、平均したものである。内角は

$$
\phi = \max\bigl(0,\ \pi - |\bar\theta_{\text{R}} - \bar\theta_{\text{L}}|\bigr)
$$

である。どちらかの区間が $0.25\,W$（`_ARM_MIN_WIDTHS`）より短いとき、つまり
2<!--n:count--> つの折れが近すぎて間に腕が取れないときは、代わりに $\phi = \pi - E$ を保存
する。角度は最後に $[10^{-6},\ \pi - 10^{-6}]$ rad の範囲に収め、ラジアンのまま `ka` に
書き込む。折れの位置は、弧長で $p$ にいちばん近い中心線の点とし、`kp` には同じ
番号のスケルトンの画素を書く。2<!--n:count--> つの折れが同じ点に重なったときは、超過回転の
大きいほうを残す。キンクかどうかを決めるのは角度ではなく $E$ なので、保存された
角度が `kinkangle_deg` 以下になるとは限らない。

`measure.compute_fiber_stats` は角度を度に直し（`FiberStats.kink_angles_deg`）、
ファイバーの CSV にはこの値が入る。`measure.fiber_kink_angle` はその中央値を取り、
GUI03 がヒストグラムにする、繊維ごとの値にする。

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

**尺度。** 規則の長さはすべて $W$ の何倍かで決まる。$W$ は、画像で見分けられる
細かさの限界（分解能）でもある。探針はどの繊維もおよそ $W$ の幅に広げて写すので、
繊維そのものがどれほど鋭く折れていても、角は中心線の上でおよそ $W$ の長さに
広がる。それよりずっと近い 2<!--n:count--> つの折れは、見分けられない。したがって、$W$ が
十分な画素数で写っている限り、同じ繊維を別の画素の大きさで撮っても、同じ
物差しで判定することになる。ただし、それぞれの長さを $W$ の何倍に
するかは理論から一つに決まるものではない。同梱スキャンを目で見て作った基準で
確かめた、経験的な値である（[個別データでの評価](validation.ja.md) §4.4）。画素の数で決まっているのは、
$W$ を測る手順の中の長さ（幅を測るときに断面を読む範囲はトラックから
±12<!--c:lib/centerline.py::_WIDTH_SEARCH_PX--> px、$W$ を測れなかったときの代わりの値 `centerline.FALLBACK_WIDTH_PX` の
8<!--c:lib/centerline.py::FALLBACK_WIDTH_PX--> px など）と、点を取る間隔（断面は 0.25<!--c:lib/centerline.py::_WIDTH_STEP_PX--> px、向きは 0.5<!--c:lib/kink_detector.py::_HEADING_STEP_PX--> px）である。
`kink_decompose_px` は、この規則では使わない。使うのは形式 1.0<!--n:bundle format version--> のバンドルの
折れ線規則だけである（§4.6）。

**中心線ごとのノイズ床（既定では無効）。** 中心線ごとのノイズ床という仕組みも
用意してある（`NOISE_SIGMAS`、`KinkJudgement.noise_excess`）。中心線全体で超過回転が
どれくらいばらつくかを、外れ値に強い方法で求め、折れの超過回転がそのばらつきの
何倍かを超えることを求めるものである。既定では**無効**である（`NOISE_SIGMAS` = 0<!--c:lib/kink_detector.py::NOISE_SIGMAS-->）。
無効にした理由は [個別データでの評価](validation.ja.md) §4.7 にある。

### 4.4 端のそばの折れは判定せずに示す

中心線の端から $1.5\,W$ 以内に中心がある折れは、**判定しない**。トラックの端には、
繊維の本当の端のほかに、§4.1 の `imp_tools.remove_bp` が交差のところで切った
切り口もある。切り口では、中心線が分岐のところの裾につられて曲がることがある
からである。この $1.5\,W$ という範囲は、経験的に選んだ値である
（[個別データでの評価](validation.ja.md) §4.9）。

こうした折れも、捨てずに残しておく。`KinkDetector.kinks_on_line` はこれを別にして
返し、バンドルは省略できるキー `up` に保存し、各繊維には
`Fiber.unjudged_indices` として渡る。GUI04 はこれを灰色の中が空いた丸で描く。
こうして、「判定しなかった」ものと「測ったうえでしきい値に届かなかった」ものを
区別できる。ただし、数には一切入れない。キンクの数・密度・角度・CSV は、判定した
キンクだけを扱う。繊維の連結と `fiber_connector.filter_fibers_by_height` は、組み
立て直した繊維に同じ規則をもう一度かける。そのため、連結したフィブリルが
切り口をつなげば、その折れはもう端のそばではなくなり、判定される。反対に、
高さによる絞り込みは繊維を切るので、新しくできた端のそばの折れは判定されなく
なる。

### 4.5 しきい値は結果と一緒に持ち運ばれる

キンクのパラメータはバンドルの `params` メタデータに書き込まれ、
`bundle_schema.kink_params_from_meta` がそれを読み戻す。バンドルを読む側は、
このうち `kinkangle_deg` を必ず使う。バンドルに入っていないトラック（交差を
またいで連結した繊維や、高さの帯で切り出した繊維の一部）でキンクを計算し直す
ときは、保存してあるキンクの点を生んだのと同じ規則を使わなければならないから
である。その規則を、キンクの配列と一緒に持ち運べる場所は、バンドルしかない。
`kink_decompose_px` も読み戻すが、使うのは形式 1.0<!--n:bundle format version--> のバンドルのときだけである
（§4.6）。

これらを `_param.json`（バンドルの隣に置くファイル）から読まないのは、わざとで
ある。このファイルは解析の*入力*であり、解析の後でも書き換えられる。そこから
読むと、解析をやり直していないのに、ファイルを書き換えただけで連結した繊維の
キンクが変わってしまう。

バンドルは、各キンクの角度 `ka` の隣に、判定に使った超過回転（`ke`、
`KinkJudgement.kink_excess`）も保存する。角度は折れの形を表し、超過回転は規則が
実際に試した量を表す。両方あれば、規則を実行し直さなくても、各キンクがしきい値
をどれだけ超えていたかを確かめられる。

### 4.6 形式 1.0 のバンドルの折れ線規則

形式 1.0<!--n:bundle format version--> のバンドルのキンクは、スケルトントラックの上で、折れ線規則によって
判定されている。`KinkDetector._binary_decompose_simple` が、**Douglas–Peucker** 法の
考え方でトラックを折れ線に単純化する。弦（折れ線の辺）から
`kink_decompose_px`（既定 3.0<!--c:lib/pipeline.py::ProcParams.kink_decompose_px--> px）以上離れたトラックの点があれば、そこに頂点を
加える。`KinkDetector._detect_kink_from_decomposed_indices` は、頂点のうち、内角
$\theta$ が `kinkangle_deg` 以下で、しかも直線から曲がっている分が「頂点の位置の
許容誤差 $d$ が、長さ $A$ の腕の向きに与える誤差」より大きいものを残す。

$$
\pi - \theta > \frac{2d}{\min(A_{\text{prev}},\, A_{\text{next}})}
$$

この規則は、画素の許容誤差のほかに物差しを持たない。そのため、なめらかな円弧も
頂点で区切って、キンクとして報告することがある。また、スケルトンの上で判定する
ので、画素の鎖の階段状のギザギザや、幅の広いところでの線のふらつきといった、
繊維そのものには無い折れも報告することがある。形式 1.0<!--n:bundle format version--> のバンドルは、解析し
直すまでスケルトントラックと保存済みのキンクをそのまま使い
（`bundle_schema.centerline_from_meta`）、その中でつなぎ直したフィブリルもこの規則で
判定する（`KinkDetector.kinks_and_decomposed_from_track`）。こうして、1<!--n:count--> 枚の画像の
中に 2<!--n:count--> つの規則のキンクが混ざることはない。

コードでは、折れ線は両端の 2<!--n:literal in the quoted code--> 点から始まる。弦ごとに、その弦からいちばん遠い
トラックの点を調べ、`threshold_distance`（`kink_decompose_px`）以上離れていれば
頂点に加える。これを、どの点も自分の弦から `threshold_distance` 未満に収まる
まで繰り返す。その後、内側の各頂点の角度を調べる。

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

## 5. これらの段がわざと行わないこと

ここまでの処理が作るのは配列である。配列から数値を計算する作業は別の場所で行う。
この役割分担をはっきりさせてあるので、画像を解析し直さなくても計測だけを
やり直せる。

- **繊維ごとの計測**（輪郭の長さ、高さの統計、まっすぐさ、曲率、キンクの密度）は
  `lib/measure.py` にあり、GUI03、GUI04、`cli.py measure` が同じものを使う。どの
  繊維も §4.2 の中心線に沿って測る（形式 1.0<!--n:bundle format version--> のバンドルでは、§4.2 の表の
  とおりスケルトントラックに沿って測る）。中心線は、バンドルを開くときに
  `fiber_tracking_image.FiberTrackingImage` が、保存してあるスケルトンと高さから
  作り直す。次の 2<!--n:count--> つの決まりは、中心線だけでなく、ここまでの段の動きにも
  よって決まっている。高さの統計は §4.2 の頂点高さについて取り、繊維の本当の端
  ではなく切り口である端では、最後の $W$ の分を除く（`measure.height_sample_mask`）。
  §4.1 が消すのは分岐点の周りの 3<!--c:lib/imp_tools.py::remove_bp(remove_size)|2 * v + 1-->×3<!--c:lib/imp_tools.py::remove_bp(remove_size)|2 * v + 1--> 画素だけだが、
  交差での相手繊維の裾はその先 1 幅ほど広がるため、それらの標本は一部が相手の
  繊維の高さである。中央値はその影響をほとんど受けないが、最大値は交差の高さを
  拾ってしまう。<!-- TODO(review): 「1 幅ほど」は scripts/measure_docs.py のどの実験も測っていない。CUT_END_EXCLUSION_WIDTHS の根拠として書かれたものである。 -->
  繊維をつなぐ処理（連結器）が橋渡しのために補間した高さも、画像から測った値では
  ないので除く。また、キンクの密度（`measure.fiber_kink_density`）は、**判定した**
  長さ、つまり輪郭の長さから両端の $1.5\,W$ ずつを引いた長さで割る。§4.4 のとおり、
  それより端に近い折れは判定しないからである。輪郭全体の長さで割ると、判定して
  いない両端の分だけ値が小さく出て、繊維が短いほどそのずれは大きくなる。
- 交差で切れた**断片をつなぎ直す処理**は `lib/fiber_connector.py` にある。つなぐ
  相手を探すのは GUI04 だけで、ほかのところは、その探索で記録した連結の情報を
  そのまま使う。
- **手で除外する処理**は `lib/fiber_selection.py` にある。
- **画素の大きさ**を使うのは計測のときだけである。ここまでの各段は、既定では
  使わないリッジ回収（§2.6。設定値が nm なので、画素の大きさが分からなければ
  実行しない）を除いて、画素を単位にしている。だからこそ、スキャンの大きさが
  記録されていてもいなくても、各段のパラメータは同じ意味を持つ。その裏返しとして、
  同じパラメータファイルでも、スキャンの大きさによって実際の長さは変わる。たとえば
  とげの長さの上限 12<!--c:lib/pipeline.py::ProcParams.spur_length--> px は、1024<!--n:example--> 画素のスキャンなら、幅 2<!--n:example--> µm のスキャンでは
  約 23<!--x:12 * 2000 / 1024--> nm、幅 10<!--n:example--> µm のスキャンでは約 117<!--x:12 * 10000 / 1024--> nm にあたる。そこで、スキャンの
  大きさが分かっているときは、画素で決めた各設定が何 nm にあたったかをバンドルに
  記録し（`bundle_schema.PIXEL_LENGTHS_KEY`、`pipeline.pixel_lengths_nm` による）、
  GUI01 はそれをログに出す。この記録があれば、2<!--n:count--> つのバンドルの各段の設定が、
  実際の長さとして同じだったかどうかを比べられる。

## 6. 結果を再現する

このソフトウェアが出す数値は、次の 3<!--n:count--> つの記録があれば一通りに決まる。

| 記録 | 記録する内容 |
|---|---|
| `<stem>_param.json` | 解析に使ったすべての `ProcParams` フィールド。フィールド名は変えないことにしているので、古いファイルも読み込める。 |
| `<stem>.b2z` | 各段の出力の配列、バンドルの形式のバージョン、キンクを判定した中心線（形式 1.2<!--n:bundle format version--> から）、スキャンの大きさとその出どころ、解析した走査ラインの範囲、および来歴としてのパラメータ。 |
| ソフトウェアのバージョン | バンドルに記録される。数値が変わる変更は `CHANGELOG.md` にはっきり書かれる。 |

解析の出力を変える変更は、再現性を壊す変更として扱う。API が変わるかどうかに
関係なく、その変更が入ったバージョンの `CHANGELOG.md` にはっきり書く。
