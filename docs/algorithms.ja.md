# 解析アルゴリズム

このページでは、前処理の 4<!--n:count--> つの段階がそれぞれ実際に何をしているのか、そして
各手順がソースコードのどこにあるのかを説明する。論文の図に載せる数値について
「なぜこの値になるのか」を自分で説明しなければならない人のために書いている。
ソフトウェアが利用者の代わりに何を決めているのか、なぜそう決めたのか、それを
変えるにはどのパラメータを変えればよいのかを示す。

このページでいう**前処理**とは、AFM の高さ画像から繊維を取り出し、キンク（繊維の
鋭い折れ）を判定するまでの処理である。繊維の長さや高さを数える**計測**は、前処理の
結果を使って別に行う（§5）。

関数ごとの技術資料（API リファレンス）は関数を個別に説明する。このページは、
関数どうしがどうつながって全体として何をしているのかを説明する。

このページには、特定のデータでの結果は載せない。同梱のスキャンや合成データで
各段階が実際にどう動いたか、いくつかの既定値をどの結果を見て決めたかは、
[個別データでの評価](validation.ja.md) にまとめてある。

## コード参照の読み方

この節は、このページをソースコードと照らし合わせて読む人のためのものである。
コードを読まない人は、次の「全体を通じた表記規則」まで飛ばしてよい。

コードは**シンボル名**（関数名やクラス名）で指し、行番号では指さない。行番号は、
関係のない編集が 1<!--n:count--> 回入っただけでずれてしまうからである。たとえば
`Segmenter._binaryzation` は `lib/segmenter.py` の中にある同じ名前のメソッド（クラスに
属する関数）を、`bg_calibrator.BG_METHOD_NAMES` はファイルに直接書かれた定数を指す。このページに
出てくるシンボルは、テストを実行するたびに `tests/test_algorithm_docs.py` が
ソースコードと突き合わせる。名前が変わったり消えたりするとテストが失敗するので、
間違った記述が誰にも気付かれずに残ることはない。

それぞれの処理は、**その計算を行うコードと一緒に**示す。ただし §4.2 の中心線（繊維の
高さの尾根に沿って引く線）の作成処理は、[GUI04 のファイバー計測](gui04_measurements.ja.md)
（GUI04 は、繊維を 1<!--n:count--> 本ずつ計測して確かめる画面）の §2 が同じコードを引用して
いるので、ここでは処理全体をまとめて呼び出す関数だけを引用する。コードブロックの先頭には、
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

同じテストは、逆に、コードだけが変わって文書が古いまま残るずれも検査する。
アルゴリズムのファイル（4<!--n:count--> つの段階と、中心線を置く `lib/centerline.py`）について、
コメントと説明文（docstring）を除いたコードから、内容が変われば必ず変わる短い
識別値（ハッシュ）を作って記録している。コードの計算内容が変わると、このページを
見直すまでテストが通らない。

## 全体を通じた表記規則

| 量 | 単位 | 備考 |
|---|---|---|
| 高さ | ナノメートル (nm) | 読み込み時に nm へ変換する。以下に出てくる高さのしきい値はすべて、**背景補正をした後**の画像での nm の値そのものであり、基板の高さが 0<!--n:definition--> nm になっていることを前提にしている。 |
| 面内の距離 | 各段階の中では画素 (px)、結果では実際の長さ（nm または µm） | 各段階はわざと画素を単位にしている。画素の大きさ（1<!--n:definition--> 画素が何 nm か）を使うのは計測のときだけである。例外は、見落とした繊維を拾い直す処理（リッジ回収、§2.6。既定では使わない）で、その設定値は nm で指定する。同じ画素の設定でも、実際の長さはスキャンの大きさで変わる（§5 の換算例）。 |
| 角度 | パラメータファイルでは度、計算の内部ではラジアン | パラメータファイルの角度（`kinkangle_deg`）は度で書き、`pipeline.build_stages` が計算の前にラジアンに直す。 |
| 配列の添字（コードを読む人向け） | `image[row, column]`、つまり `[y, x]` | いくつかの補助関数は `np.where` の結果をそのまま返す。その場合、最初の配列が行の添字である。 |

**解析結果の画素の位置は、元のスキャンから 1<!--n:definition--> 画素ずれる。** 背景補正（§1）には
3<!--n:count--> つの方式（`trendfill`・`tophat`・`spline1d`）があり、どれも元のスキャンの最初の行と
最初の列を切り落とした画像（コードでは `original[1:, 1:]`）から背景を引く。`trendfill` と
`spline1d` は隣り合う画素の高さの差をもとに背景を作るので、縦横とも 1<!--n:definition--> 画素小さく
なる。`tophat` も、後の段階が同じ大きさの画像を受け取れるように、同じ形に切りそろえる。後の段階はすべてこの画像を使うので、解析結果の画素 $(r, c)$ は、
元のスキャンの画素 $(r+1, c+1)$ にあたる。

**パラメータ**

以下に出てくる利用者が設定できる値は、すべて `pipeline.ProcParams` の項目である。
その値は、各バンドル（解析結果をまとめた `.b2z` ファイル）の隣に
`<input_stem>_param.json` として保存される（`<input_stem>` は入力ファイルの名前から
拡張子を除いたもの）。同じ値は、どの設定で解析したかの記録として、バンドルの中にも
書き込まれる（§4.5）。利用者が変えられる設定はこれですべてだが、解析を再現するには
ソフトウェアのバージョンも必要である（§6）。線の端の釣り針形の曲がりを切り取る
処理（フック切除、§3.6）の角度のような内部の定数は、`ProcParams` の項目ではなく、
バージョンによって決まるからである。

このページで「既定値」と書いた値は `ProcParams` の既定値であり、GUI（画面からの
操作）と CLI（コマンドからの操作）はこの値から始まる。プログラムから各段階の
クラスを直接使う場合だけ、一部の既定値が違う。通常の利用には関係しない。

## 処理の全体の流れ

前処理は、次の 4<!--n:count--> つの段階からなる。

1. **背景補正**（§1）: 試料の傾きやスキャナのたわみを引き、基板の高さを 0<!--n:definition--> nm に
   そろえる。
2. **二値化**（§2）: 各画素を繊維かそれ以外かに分け、繊維の画素に印を付けた
   白黒の画像を作る。この画像を**マスク**と呼ぶ。
3. **細線化**（§3）: マスクの繊維を、幅 1<!--n:definition--> 画素の線にする。この線を**スケルトン**と
   呼ぶ。
4. **キンク検出**（§4）: 繊維が一か所で鋭く折れているところ（**キンク**）を見つける。

```text
生の AFM テキスト / CSV  ->  afm_io.load_afm_text()      \
Gwyddion .gwy            ->  gwy_io.load_gwy_image()     /  -> 高さ配列 (nm)
                                                             |
                             ProcessedImage.original_image  <-+
                                     |
   1. BGCalibrator   ->  calibrated_image   (nm、基板が 0)
   2. Segmenter      ->  binarized_image    (白黒の繊維マスク)
   3. Skeletonizer   ->  skeleton_image     (1 px 幅のスケルトン) + ep / bp
   4. KinkDetector   ->  スケルトンのかたまりごとのキンクの位置と角度
                         （中心線の上で判定。§4.2）
                                     |
                             .b2z バンドル + _param.json
```

図の `ep` は端点（線の端）、`bp` は分岐点（線が枝分かれする点）の地図である（§3.8）。

この順番どおりに実行するのが `pipeline.process_file` である。GUI01（前処理を行う
画面）でも `cli.py process`（コマンドラインから前処理を行う命令）でも、同じ処理が
同じ順に実行されるので、2<!--n:count--> つの入口で結果が食い違うことはない。

各段階は、前の段階が書いた結果を読む。それが無ければ、原因が分かりやすいように、
その段階の入口ではっきりとエラーにする（たとえば `Segmenter.__call__`）。

---

## 1. 背景補正

**コード:** `lib/bg_calibrator.py` — `BGCalibrator.__call__` が
`_call_trendfill` / `_call_tophat` / `_call_spline1d` へ振り分ける。
**入力:** `original_image`。**出力:** `calibrated_image`。

背景の見積もり方は 3<!--n:count--> 通り（`trendfill`・`tophat`・`spline1d`）あり、パラメータ `bg_method`
で選ぶ（既定は `trendfill`）。`BGCalibrator.__call__` 自身は、選ばれた方式の処理へ
振り分けるだけである。

```python
# source: lib/bg_calibrator.py::BGCalibrator.__call__
if self.bg_method == 'tophat':
    self._call_tophat(image)
elif self.bg_method == 'spline1d':
    self._call_spline1d(image)
else:
    self._call_trendfill(image)
```

### 1.1 なぜ背景補正が必要なのか

生の AFM スキャンには、試料の傾きや、スキャナのせいで画像全体が皿のように
たわんだ形が重なっていることがある。

一方、背景補正の後に行う二値化や細線化は、高さのしきい値を**基板から何 nm 高いか**
で決めている（二値化の `global_threshold` と `low_threshold`、細線化の `bp_height`
など）。たとえば二値化（§2.1）は、高さが `global_threshold` を超える画素を繊維の
候補にする。こうしたしきい値が画像のどこでも同じ意味を持つのは、基板の高さが
どこでも 0<!--n:definition--> nm のときだけである。傾いたままの画像では、同じしきい値が、基板の
高い場所では低すぎ、低い場所では高すぎることになる。

そこで背景補正は、画像から傾きやたわみ（背景）を見積もって引き、基板をどこでも
0<!--n:definition--> nm にそろえる。この段階の作りは、すべてこの目的から決まっている。見積もりが
傾きやたわみを再現しきれないと、残ったずれがそのまま補正後の高さのずれになり、
二値化や細線化のしきい値の判定に紛れ込む。

### 1.2 3 方式が共通して使う処理

背景の見積もり方は方式ごとに違うので、§1.3〜§1.5 で方式ごとに説明する。ここでは、
どの方式も使う処理だけを説明する。

**Savitzky–Golay フィルタによる平滑化**

Savitzky–Golay フィルタは、少しずつずらした小さな窓の中で多項式を当てはめて、
データをなめらかにするフィルタである。どの方式も、見積もった背景をこのフィルタで
なめらかにする。窓の幅は `savgol_window`（既定 31<!--c:lib/pipeline.py::ProcParams.savgol_window--> 画素）、窓の中で当てはめる
多項式の次数は `savgol_polyorder`（既定 1<!--c:lib/pipeline.py::ProcParams.savgol_polyorder-->、つまり直線）である。かけるのは X 方向
（行に沿った方向）だけである。`signal.savgol_filter` を、画像の最後の軸（行に沿った
方向）にかかる既定の向きのまま呼んでいるためである。

**最後の中央値フィルタ（任意）**

どの方式でも、背景を引いた後の画像に
3<!--n:literal in the quoted code-->×3<!--n:literal in the quoted code--> の中央値フィルタをかけることができる。`apply_median`（既定は無効）で有効に
する。有効にすると、点状に残ったノイズは減るが、そのぶんいちばん鋭い高さの
特徴が少し鈍る。

**トレンドの当てはめ**

トレンドとは、画像全体のゆるやかな傾きやたわみを表す、なめらかな曲面のことである。
どの方式も、背景を見積もる前に画像からトレンドをいったん引き、見積もった後で足し
戻す。足し戻した背景（トレンドを含む）を最後に元の画像から引くので、傾きやたわみも
結局は取り除かれる。いったん引くのは、背景の見積もり（穴埋めやオープニング）が傾きに
じゃまされないようにするためである（理由の詳細は §1.3〜§1.5）。当てはめは
`BGCalibrator._fit_trend_surface` が行う。

`_fit_trend_surface` が当てはめるのは、平面ではなく**2<!--n:definition--> 次曲面**である。実際の
スキャンは傾いているだけでなく、皿のようにたわんでいることがあるからである
（§1.1）。2<!--n:definition--> 次の項を作る前に座標を $[-1, 1]$ の範囲に直し、計算が数値的に
不安定にならないようにしている。背景の画素の並び方が偏っていると（たとえば
全部の点が 1<!--n:count--> 行に並んでいると）、曲面は一通りに決まらない。それでも、使っている
計算（`numpy.linalg.lstsq`）は何も言わずに答えを返してしまう。そこで、曲面が一通りに
決まるかをはっきり調べ、決まらなければ 2<!--n:definition--> 次曲面 → 平面 → 背景の平均の
高さ、の順に簡単なものへ切り替える。

座標を $x_n, y_n \in [-1, 1]$ に直すと、当てはめる曲面は

$$
T(x, y) = a\,x_n^2 + b\,y_n^2 + c\,x_n y_n + d\,x_n + e\,y_n + g
$$

であり、背景とした画素（コードでは `valid_mask`。どの画素を背景とするかは方式ごとに
違う。§1.3〜§1.5）だけを使って、最小二乗法で係数を求める。

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

この方式は、まず繊維の画素を見つけて印を付け、それを背景の候補から外す。この印の
画像も「繊維のマスク」と呼ぶが、§2 の二値化で作るマスクとは別のもので、背景を
見積もるためだけに使う。

`_call_trendfill` は、次のように処理を呼び出す。

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

各行と、この後の手順 1<!--n:label-->〜3<!--n:label--> などとの対応は次のとおりである。

| コードの行 | 説明している箇所 |
|---|---|
| `_detect_fiber_mask(...)` | 手順 1<!--n:label-->（繊維の画素を見つける） |
| `_bg_generate(...)` | 手順 2<!--n:label-->（マスクの掃除と膨張）と、手順 3<!--n:label--> のうち背景を作るところ（トレンドを引く・穴埋め・平滑化・トレンドを戻す） |
| `...`（省略した行） | 他の方式の途中結果を消しておく（理由は §1.4 の最後） |
| `_bg_calibrate(...)` | 手順 3<!--n:label--> の最後（元の画像から背景を引く） |
| `if self.apply_median:` 以下 | §1.2 の「最後の中央値フィルタ（任意）」 |

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

`_bg_fit` は、差分画像ごとに、高さの差の値がどのくらいの頻度で現れるかを 150<!--c:lib/bg_calibrator.py::BGCalibrator._bg_fit(bin_n)--> 区間の
ヒストグラムにする。画像の大部分は平らな基板なので、隣り合う画素の差はほとんどが
ノイズ程度の小さな値になり、ゼロ付近に高い山を作る。一方、繊維の斜面をまたぐ
ところでは差が大きくなるので、山から離れた両側の裾に少しだけ現れる。この山に、
当てはめ用のライブラリ `lmfit` で**ガウス関数＋直線**（山の下に敷く傾いた土台）を
当てはめ、山の中心と幅を求める。山の
形が分かれば、それを基準に「基板のノイズにしては大きすぎる差」を見分けられる
（次の `_dif_sep`）。

X と Y を別々に当てはめるのは、2<!--n:count--> つの方向でノイズの性質が違うからである。
AFM は、探針を 1<!--n:count--> 本の走査ラインに沿って往復させて（高速走査軸）1<!--n:count--> 行ずつ測り、
その走査ラインを 1<!--n:count--> 本ずつ送って（低速走査軸）画像を作る。画像では通常、行の
方向（X）が高速走査軸、列の方向（Y）が低速走査軸である。Y 方向に隣り合う画素は
走査ライン 1<!--n:count--> 本分の時間をおいて測られるので、その高さの差には、走査中のドリフトに
よる走査ラインごとの高さのずれが加わる。

ガウス関数の中心と幅の初期値には、高さの差の中央値と、外れ値に強い幅の目安
（四分位範囲を 1.349<!--n:literal in the quoted code--> で割った値）を使う。正規分布では四分位範囲が標準偏差の
1.349<!--n:literal in the quoted code--> 倍になるので、こう割ると標準偏差の目安になる。Y の当てはめは、同じコードを `dif_y`
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
+1 & \Delta > \mu + \kappa\sigma \\
0 & \text{それ以外} \\
-1 & \Delta < \mu - \kappa\sigma
\end{cases}
$$

ここで $\kappa$ は `threshold_factor`（既定 2.0<!--c:lib/pipeline.py::ProcParams.threshold_factor-->）である。つまり $\pm 1$ は「この段差は
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
端から順に読んでいく。同じ値が続く区間ごとにまとめ、繊維を横切ったときに
現れる 2<!--n:count--> 種類の並び方を探す。どちらも上り（+1<!--n:label-->）から始まる山の並びで、谷（−1<!--n:label--> から
+1<!--n:label--> への並び）は探さない。なお実装の都合で、X の地図の最後の行と Y の地図の最後の列は
読まれず、そこには繊維の印が付かない（ループが `range(shape[0] - 1)` までのため）。

- **パターン 1<!--n:label--> — `[+1, 0, -1]`**: 繊維の片側の斜面を上り、てっぺんで平らになり、
  反対側の斜面を下る並び。平らな区間の長さが `fiber_detect_factor`（既定 10<!--c:lib/pipeline.py::ProcParams.fiber_detect_factor--> 画素）より
  短いときに繊維とみなす。つまり、てっぺんが繊維と言えるくらい狭い場合である。
- **パターン 2<!--n:label--> — `[+1, -1]`**: てっぺんの平らな部分が見えないほど尖った山。
  上りと下りを合わせた長さが `noise_detect_factor`（既定 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor--> 画素）を超えるときに
  繊維とみなす。この条件によって、その長さが既定で 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor--> 画素以下の短い段差は
  ノイズとして捨てられる。

見つかった並びの両端の間にある画素に、すべて繊維の印を付ける。X と Y の結果は、
次の手順で合わせる（どちらかで印が付けば繊維とする）。

下のコードでは、`l_arr` が各区間の値、`arg_arr` が各区間の始まる位置である。
パターン 1<!--n:label--> は、てっぺんの平らな区間（0<!--n:label--> の区間）が `fiber_detect_factor` より短いときに
採る。パターン 2<!--n:label--> は、上り（+1<!--n:label-->）の区間の始まりから下り（−1<!--n:label-->）の区間の終わりまでの
長さが `noise_detect_factor` を超えるときに採る。Y の走査は、行と列を入れ替えた
だけの同じコードである。

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

#### 手順 2 — マスクの掃除と膨張

`_bg_generate` は、マスクを使う前に 2<!--n:count--> つの手直しをする。

**ノイズによる誤検出の除去**

手順 1<!--n:label--> の 2<!--n:count--> つのパターン（+1<!--n:label--> → 0<!--n:label--> → −1<!--n:label--> と +1<!--n:label--> → −1<!--n:label--> の並び）は、数画素ほどの大きさのノイズにも
反応する。ノイズの多い画像や広い範囲を撮った画像では、そうした小さな印が画面
全体にびっしり散らばる。

この小さな印は、ほとんどがパターン 1<!--n:label--> から来る。1<!--n:count--> 行の中で印が付く長さは、パターン 1<!--n:label-->
では最短で 2<!--x:1 + 1 + 1 - 1--> 画素（上り・平ら・下りが 1<!--n:definition--> 画素ずつで、最後の 1<!--n:definition--> 画素は印に含めない）、
パターン 2<!--n:label--> では `noise_detect_factor` 画素以上だからである。既定の
`noise_detect_factor` = 10<!--c:lib/pipeline.py::ProcParams.noise_detect_factor--> では、10<!--c:lib/pipeline.py::ProcParams.min_mask_component_area--> 画素より小さなかたまりを作るのはパターン 1<!--n:label-->
だけである（`noise_detect_factor` を小さくすると、パターン 2<!--n:label--> も小さなかたまりを作る。
`BGCalibrator` をプログラムから直接作るときの既定値は 2<!--c:lib/bg_calibrator.py::BGCalibrator.__init__(noise_detect_factor)--> なので、この場合にあたる）。

そこで、斜め隣も含めてつながった（8<!--n:literal in the quoted code--> 連結の）かたまりのうち、面積が
`min_mask_component_area`（既定 10<!--c:lib/pipeline.py::ProcParams.min_mask_component_area--> 画素）より小さいものを消す。これをしないと、
次の膨張で 1<!--n:count--> つの誤検出が一辺 $2d+1$ 画素の正方形に広がる（$d$ は次に説明する
膨張の幅 `mask_dilation`）。マスクの部分は手順 3<!--n:label--> で背景の候補から外され、まわりの
背景の値で埋められる（以下ではこの部分を「穴」と呼ぶ）。誤検出が広がった穴が
画面全体に散らばると、作り直した背景がゴマ塩のようにまだらになり、タイル状・
細胞状の模様となって画像に現れる。

**マスクの膨張**

マスクを `mask_dilation` px（既定 3<!--c:lib/pipeline.py::ProcParams.mask_dilation-->）だけ外側へ太らせる。
繊維の「肩」（斜面のすそ）の画素は `_extract_fiber` では拾いきれず、まだ繊維の
高さが少し残っている。これを背景の候補に残すと背景の推定が持ち上がり、
繊維の両脇を引きすぎて、暗い縁取り（ハロー）ができる。

小さなかたまりを消すのは、膨張が有効（`mask_dilation` > 0<!--n:literal in the quoted code-->）で、しかも
`min_mask_component_area` が 1<!--n:literal in the quoted code--> より大きいときだけである。膨張しないなら誤検出が
広がらないので、この掃除はしない。コードの `tri_difx_fill[1:, :]` と
`tri_dify_fill[:, 1:]` は、X と Y の地図を合わせる前に、どちらも「端の画素を削った
後の画像」と同じマス目にそろえるためのものである。

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

#### 手順 3 — 穴を埋めて背景を作り、元の画像から引く

穴は、**いちばん近い背景の画素**の値で埋める（いちばん近い画素を探すのには
`scipy.ndimage.distance_transform_edt` を使う）。背景の画素にとっていちばん近い背景の
画素は自分自身なので、背景の画素の値は変わらない。

この埋め方では、穴の中は近くの背景の値をそのまま写した平らな面になり、傾きを
再現できない。そこで、埋める前に、背景の画素だけに当てはめたトレンド（§1.2）を
画像から引いておく。傾きを取り除いた画像の上なら、平らに埋めても問題がない。

埋め終わった面を Savitzky–Golay フィルタで X 方向になめらかにし（§1.2）、トレンドを
足し戻す。これが背景になり、`_bg_calibrate` が元の画像から背景を引く。

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

`_call_tophat` は、直径 `tophat_se_size`（既定 25<!--c:lib/pipeline.py::ProcParams.tophat_se_size--> px）の円盤（コードでは
`cv2.MORPH_ELLIPSE`）を使った**オープニング**（opening）で背景を見積もる。

オープニングは、次の 2<!--n:count--> つの操作を続けて行う処理である。細い出っ張りだけを消し、
それ以外は元のまま残す。ここでの「収縮」「膨張」は高さの値に対する操作で、§1.3 の
白黒のマスクの膨張とは対象が違う。

1. **最小値フィルタ（収縮）**: 各画素を、その周りの円盤の中でいちばん低い値に
   置き換える。円盤より細い山は、周りの低い値に置き換わって消える。太い山は、
   縁が削られて細くなるだけで残る。
2. **最大値フィルタ（膨張）**: 各画素を、その周りの円盤の中でいちばん高い値に
   置き換える。削られた太い山の縁が元に戻る。上の 1<!--n:label-->. で消えた細い山は、もう無い
   ので戻らない。

横 1<!--n:example--> 列の数値で、窓の幅を 3<!--n:example--> 画素にした例を示す。

```text
                     細い山 (幅 2)     太い山 (幅 4)
元の値               0 0 5 5 0 0      0 5 5 5 5 0
最小値フィルタの後    0 0 0 0 0 0      0 0 5 5 0 0
最大値フィルタの後    0 0 0 0 0 0      0 5 5 5 5 0
                     消えた           元どおり
```

この方式では、繊維が「円盤より細い山」にあたる。オープニングをかけると繊維だけが
消えて基板が残るので、それを背景とする。そのため円盤は、画像の中でいちばん太い
繊維より大きくしなければならない（`tophat_se_size` の説明では、目安は典型的な繊維の
幅の 2〜3<!--n:rule of thumb from the tophat_se_size docstring--> 倍）。円盤より太い繊維は消えずに背景に残り、背景と一緒に引かれて
しまう。元の画像からオープニングの結果を引いた残り `original - opening` は、画像処理で
white top-hat と呼ばれる操作にあたる。

この方式は繊維のマスクを作らないので、トレンドの曲面も繊維を含めた全部の画素に
当てはめる。トレンドを引いた画像にオープニングをかけ、X 方向になめらかにしてから、
トレンドを戻す。

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

各行と、それを説明している箇所の対応は次のとおりである。

| コードの行 | 説明している箇所 |
|---|---|
| `se = ...` | 直径 `tophat_se_size` の円盤を作る（この節の冒頭） |
| `bg_trend = ...` | 繊維も含めた全部の画素にトレンドを当てはめる（§1.2 の「トレンドの当てはめ」） |
| `opened_detrended = ...` | トレンドを引いた画像にオープニングをかける（下の「先に傾き（トレンド）を引いてからオープニングをかける」） |
| `self.bg_open = ...` | オープニングの結果にトレンドを戻したもの（実装上の途中結果。この後の計算には使わない） |
| `self.bg_sm = ...` | X 方向に Savitzky–Golay フィルタでなめらかにし、トレンドを戻して背景にする（§1.2） |
| `calibrated_image = ...` | 元の画像から背景を引く。最初の行と列を切り落とす理由は「全体を通じた表記規則」にある |
| `calibrated_image -= ...` | 画像全体の中央値を引く（下の「最後に中央値を引いて高さをそろえ直す」） |

欠かせないポイントが 2<!--n:count--> つある。

**先に傾き（トレンド）を引いてからオープニングをかける。** 傾いたままの画像に
オープニングをかけると、画像の端から円盤の半径までの帯で値がずれる。そこでは
円盤が画像の外にはみ出し、最小値フィルタが画像の中に残った部分だけから最小値を
取るので、最大値フィルタでも元に戻らないからである。

**最後に中央値を引いて高さをそろえ直す。** オープニングは、凹凸の「下側の縁」を
なぞるような見積もりになる。ノイズのある基板では、ノイズの谷の底に張り付いて
しまう。そのため背景を引いた後の基板の高さは、ノイズの谷の深さの分だけプラス側に
浮く。画像全体の中央値を引いてこれを 0<!--n:definition--> nm に戻し、`global_threshold`、
`low_threshold`、`bp_height` が、他の 2<!--n:count--> 方式（背景をなめらかにして作るので、
ノイズの真ん中を通る）と同じ意味になるようにする。繊維が画像のおよそ半分より少ない
面積しか覆っていなければ、中央値は繊維に引っぱられず基板の高さを表す。

（実装上の注意）この方式は繊維のマスクを作らないので、マスク作りの途中結果も
計算しない。同じ `BGCalibrator` で前に別の方式を実行したときの途中結果が残らない
ように、それらは `None`（値が無いという印）にしておく。

### 1.5 `spline1d` — ラインノイズの目立つ測定データ向きの方式

`_call_spline1d` は、`trendfill` と同じ繊維のマスクを使う。そのうえで、
`spline1d_axis` が指す向きのライン 1<!--n:count--> 本ごとに、次数 `spline1d_degree`（既定 2<!--c:lib/pipeline.py::ProcParams.spline1d_degree-->）の
1<!--n:definition--> 次元 B スプライン（点をなめらかにつなぐ曲線）で穴を埋める。ラインどうしは互いに影響しない。`'x'` では
ライン 1<!--n:count--> 本が画像の 1<!--n:count--> **行**、`'y'` では 1<!--n:count--> **列**である。各ラインの穴は、そのライン
自身の値だけから埋めるので、埋めた背景はそのライン独自の高さの水準を保つ。
高速走査軸（探針が走査ラインに沿って往復する方向）が X、つまり行の方向である普通の撮り方では、
`'x'` のラインは走査ラインそのものである。このとき保たれる水準は走査ラインごとの高さのずれ
（走査中のドリフトなどが作る横縞）である。このずれは背景に含まれるので、背景を
引くと横縞も一緒に消える。どちらの向きを選んでも、後の Savitzky–Golay による
平滑化は X 方向（行に沿った方向）にしかかからない。

`trendfill` と同じく、穴を埋める前に、背景の画素だけに当てはめたトレンドを画像
から引いておく。穴埋めが試料の傾きやたわみを再現しなくて済むようにするためで
ある。ただし順番が `trendfill` と違い、トレンドを**先に**足し戻してから
Savitzky–Golay フィルタをかける。
<!-- TODO(review): spline1d だけトレンドを平滑化の前に足し戻す理由は、コードにもコメントにも書かれていない。作者に確認すること。 -->

既定の向きは `'x'` である。ラインの中の、繊維で隠れていない値（有効サンプル）が
`spline1d_degree` + 1<!--n:literal in the quoted code--> 個より少ないとき、または次数が 2<!--n:literal in the quoted code--> より小さいときは、
スプラインの代わりに直線で埋める。

ラインの両端では、わざと**形を外へ延ばさない（外挿しない）**。各ラインの最初と
最後の有効サンプルより外側には、片側にしか背景のデータが無い。そこに 1<!--n:definition--> 次元の
方法で形を置くと（スプラインをそのまま延ばす、直線の傾きを延ばすなど）、その
ラインだけに合わせた形になる。その誤差は延ばす区間が長いほど大きくなり、
しかも隣のラインとは無関係に出るので、ラインごとに勝手な帯模様ができてしまう。
そこで `_spline1d_fill` は、両端の区間を**そのライン自身の、端にいちばん近い背景の
値の平均**で一定に埋める。平均する値の数（`end_window`）には `savgol_window`
（既定 31<!--c:lib/pipeline.py::ProcParams.savgol_window-->）を使う。既定の `'x'` では、トレンドを引いた後の画像で
ラインごとに残る量は、ほぼ走査ラインの高さのずれだけである。これはラインに
沿って一定なので、平均の高さで一定に埋めれば、傾きを延ばさずにこのずれを
見積もれる（`'y'` のときは、走査ラインではなく画像の列ごとに、その列の平均の高さで
埋めることになる）。たくさんの値を
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

各行と、それを説明している箇所の対応は次のとおりである。

| コードの行 | 説明している箇所 |
|---|---|
| `_detect_fiber_mask(...)`、`_bg_generate(...)` | `trendfill` と同じ繊維のマスクを作る（§1.3 の手順 1<!--n:label-->・2<!--n:label-->）。`_bg_generate` が作る背景は捨て、どこが背景の画素か（`bg_only`）だけを使う |
| 最初の `...`（省略した行） | 端を切り落とした画像と、背景の画素の印を用意する（実装上の準備）。背景の画素がまったく無いときは、トレンドも背景も全面ゼロにする |
| `bg_trend = ...`、`detrended = ...` | 背景の画素だけにトレンドを当てはめて引き、繊維の画素は空き（値なし）にする（この節の 2<!--n:label--> 番目の段落） |
| `bg_int = self._spline1d_fill(...)` | ラインごとにスプラインで穴を埋め、両端は一定の高さで埋める（この節の最初の段落と、両端の扱いの段落。下の `_spline1d_fill` のコード） |
| `unfilled = ...` から `if unfilled.any():` の終わりまで | それでも埋まらない画素を、2<!--n:definition--> 次元でいちばん近い背景の画素の値で埋める（両端の扱いの段落の最後） |
| `bg_int = bg_int + bg_trend` | トレンドを、平滑化より**先に**足し戻す（この節の 2<!--n:label--> 番目の段落） |
| 後の `...`（省略した行） | 平滑化する前の背景を残しておく（実装上の途中結果） |
| `self.bg_sm = ...` | X 方向に Savitzky–Golay フィルタでなめらかにする（§1.2） |
| `calibrated_image = ...` | 元の画像から背景を引く（「全体を通じた表記規則」） |

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
| `trendfill`（既定） | ふつうはこれを使う。繊維を背景の候補から外すので、繊維そのものを削ってしまわない。 | 高さの差の分布への当てはめ（`lmfit`）で繊維のマスクを作り、トレンドの当てはめ、穴埋め、平滑化を行う。 |
| `tophat` | 特殊な試料で、繊維のマスク作りが思いどおりに働かないとき。 | 繊維のマスクは作らず、トレンドの当てはめ、オープニング、平滑化だけを行う。 |
| `spline1d` | ラインノイズ（走査中のドリフトやフィードバックの不調で生じる、走査ラインごとの高さのずれ）が目立つスキャン。 | `trendfill` のマスク作りと `_bg_generate` をすべて実行したうえで、ラインごとの 1<!--n:definition--> 次元スプラインによる穴埋めを加える。 |

もう使えない方式（`spline2d`）を選んだパラメータファイルを読み込むと、
`bg_calibrator.BG_METHOD_REMOVED` がその方式の名前を挙げて知らせ、実行を止める。
残っている別の方式に勝手に読み替えることはしない。別の方式に置き換えると、
保存してある `_param.json` で再現できるはずの数値が変わってしまうからである。

---

## 2. 二値化

**コード:** `lib/segmenter.py` — `Segmenter.__call__`。
**入力:** `calibrated_image`。**出力:** `binarized_image`。

この段階は、背景補正後の高さ画像の各画素を、繊維かそれ以外かに分ける。結果は、
繊維の画素に印を付けた白黒の画像（マスク）である。まず高さのしきい値で印を付け
（§2.1）、そこから繊維でないものを順に取り除いていく（§2.2〜§2.5）。必要なら
見落とした繊維を拾い直し（§2.6）、最後に小さな隙間を埋める（§2.7）。

この段階は、フィルタを順につないだものである。パラメータを調整するときに途中の
結果をそれぞれ確かめられるよう、フィルタごとに別の関数になっている。

| 順番 | 処理 | 関数 | 節 |
|---|---|---|---|
| 1<!--n:label--> | 高さのしきい値で印を付ける | `_binaryzation` | §2.1 |
| 2<!--n:label--> | 小さすぎるかたまりを消す | `_remove_small_fragments` | §2.2 |
| 3<!--n:label--> | 線のような形でないかたまりを消す | `_remove_nonlinear_objects` | §2.3 |
| 4<!--n:label--> | 細い橋でつながった破片を切り離す（任意） | `_remove_connecting_fragments` | §2.4 |
| 5<!--n:label--> | 低すぎるかたまりを消す | `remove_low_component` | §2.5 |
| 6<!--n:label--> | 見落とした繊維を拾い直す（任意） | `_recover_missed_ridges` | §2.6 |
| 7<!--n:label--> | 小さな隙間を埋める | `skimage.morphology.closing` | §2.7 |

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

### 2.1 2 つのしきい値の両方を超える画素を残す

`_binaryzation` は、**2<!--n:count--> つのしきい値の両方**を超えた画素だけを繊維とする。

$$
\text{mask} = (h > t_{\text{global}}) \;\wedge\; (h > t_{\text{local}}(x,y))
$$

全体のしきい値 `global_threshold`（既定 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm）は、基板から測った高さそのもので
ある。背景補正が欠かせないのは、この値のためである。局所のしきい値は、
`skimage.filters.threshold_local` を窓の幅 `wsize_localbin` px（既定 17<!--c:lib/pipeline.py::ProcParams.wsize_localbin-->）で使ったもので、
その画素の周りの重み付き平均であり、場所ごとに変わる。

両方を満たすことを求めるのは、わざとである。局所のしきい値だけでは、何もない
場所（周りにノイズしかない場所）でノイズを繊維として拾ってしまう。全体の
しきい値がそれを取り除く。一方、「両方」を求めるので、局所のしきい値は、全体の
しきい値を通った画素を減らすことしかできない。残るのは、基板からの高さが全体の
しきい値を超え、しかも周りの重み付き平均より高い画素である。
<!-- TODO(review): 以前ここにあった「大域検定だけでは局所的に沈んだ領域にある繊維を取りこぼす」は、論理積では局所検定がそうした繊維を拾えないため、局所検定を加える理由として成り立たない。局所検定を加えた意図を作者に確認すること。 -->

`skimage.filters.threshold_local` は既定の引数のまま呼んでいるので、局所のしきい値は、
窓の中の値をガウス関数で重み付けした平均である。平均にそのまま比べ、上乗せはしない
（オフセット 0<!--n:library default (skimage.filters.threshold_local offset)-->）。

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
うち、面積が `area_min`（既定 100<!--c:lib/pipeline.py::ProcParams.area_min--> 画素）以下のものを消す。続けて 3<!--n:literal in the quoted code-->×3<!--n:literal in the quoted code--> の
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

`_remove_nonlinear_objects` は、かたまりが「線」のような形かどうかを調べる。
繊維は線のような形をしているが、汚れの粒や、探針のせいで画像に現れる実在しない
形（アーティファクト）はそうではない。

- 面積が 1000<!--n:literal in the quoted code--> 画素以上のかたまりは、この検査をせずに残す。
  <!-- TODO(review): 1000 画素以上のかたまりを検査しない理由は、コードにもコメントにも書かれていない（大きな汚れの塊も残る）。作者に確認すること。 -->
- かたまりを囲む長方形（バウンディングボックス）が縦も横も `h_length`
  （既定 20<!--c:lib/pipeline.py::ProcParams.h_length--> px）より短いかたまりは消す。必要な長さの線が入りようがないから
  である。
- それ以外のかたまりは、囲む長方形の中で Canny 法（画像の縁を取り出す標準的な
  方法）で輪郭を取り出し、Hough 変換で直線を探す。Hough 変換は、考えられる直線
  ごとに、その上に乗る輪郭の点の数を数える方法で、この数を「投票数」と呼ぶ。
  投票数が多い直線（Hough ピーク）ほど、輪郭のうち多くの点がその直線に乗って
  いる。投票数が `h_length` 以上の直線をすべて拾い、その投票数を合計する。直線
  らしさの点数は

  $$
  s_{\text{ratio}} = \frac{\sum \text{Hough ピークの投票数}}{\sum \text{輪郭の画素数}}
  $$

  であり、「このかたまりの輪郭のうち、どれだけの割合が直線で説明できるか」を
  表す。$s_{\text{ratio}}$ が `h_sratio`（既定 0.5<!--c:lib/pipeline.py::ProcParams.h_sratio-->）より小さいかたまりを消す（コードには
  「画素数が 1000<!--n:literal in the quoted code--> より少ない」という条件も書いてあるが、1<!--n:label--> つ目の項目で 1000<!--n:literal in the quoted code--> 画素以上は
  すでに除いてあるので、結果は変わらない）。

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

なお、`h_length` はこの関数の中で 2<!--n:count--> つの役目を持つ。囲む長方形の判定では画素で
測った長さとして、Hough のピーク探しでは、直線とみなすのに必要な最小の投票数
（線の長さの目安）として使われる。

### 2.4 細い橋でつながった破片を切り離す（既定では無効）

`_remove_connecting_fragments` は、マスクを一回り縮め（収縮）、面積が
`area_min_connecting`（既定 3<!--c:lib/pipeline.py::ProcParams.area_min_connecting--> 画素）以下のかたまりを消し、膨張で元の太さに
戻してからクロージング（§2.7）をかける。ねらいは、幅 1<!--n:intent--> 画素の細い橋でつながった破片を
切り離すことである。これが実行されるのは `apply_no_connecting` が有効なときだけで、
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

```python
# source: lib/segmenter.py::Segmenter.remove_low_component
labels = np.arange(1, n_labels)
max_heights = ndi_maximum(height_image, labels=label_image, index=labels)
low_labels = labels[np.asarray(max_heights) < self.low_threshold]
if low_labels.size > 0:
    out_binary_image[np.isin(label_image, low_labels)] = 0
return out_binary_image
```

### 2.6 見落とした繊維を拾い直す（リッジ回収。既定では無効）

`_recover_missed_ridges` は、ここまでのしきい値処理が丸ごと見落とした繊維を
拾うための、2<!--n:count--> 回目の探索である。リッジとは、尾根のように細長く盛り上がった
構造のことで、ここでは繊維を指す。`ridge_recovery` が有効（既定では無効）で、しかも
画素の大きさ（1<!--n:definition--> 画素が何 nm か）が分かっているときだけ実行する。設定値が実際の
長さ（nm）で書かれているからである。画素の大きさは、スキャンの大きさが入力
ファイルなどに記録されているときに分かる。

1. **Frangi** フィルタ（血管のような細長い構造を強調するフィルタ）を、複数の
   スケール（見る構造の太さの目安）でかける。スケールは、`ridge_min_width_nm` から
   `ridge_max_width_nm` までを画素に換算した範囲を、等比で 5<!--n:literal in the quoted code--> 通りに分けたもので
   ある。実際の長さで指定するので、1<!--n:count--> つの設定値が、どの解像度のスキャンでも
   同じ大きさの構造を指す。
2. フィルタの出力を**ヒステリシス**（高いしきい値を超えた部分と、そこから
   低いしきい値の上でつながった部分を残す方法）で二値化する。高いしきい値は
   大津法（ヒストグラムを 2<!--n:count--> つのグループに分けたとき、2<!--n:count--> つが最もはっきり分かれる
   位置をしきい値にする方法）、低いしきい値は三角法（ヒストグラムの山の頂点と
   分布の端を直線で結び、その直線からヒストグラムがいちばん離れる位置をしきい値に
   する方法）で決める。コードでは `skimage.filters.threshold_otsu` と
   `skimage.filters.threshold_triangle` を使う。
3. すでに繊維とされた画素を**先に**除いてから、残りをつながったかたまりに分ける。
   こうすれば、すでに見つかった繊維に一点だけ触れている長い繊維も拾える。逆に、
   すでにある繊維にまったく触れていないかたまりだけを拾うやり方では、そうした
   繊維は丸ごと捨てられてしまう。しかも長い繊維ほど触れやすい。
4. 残ったかたまりのうち、細線化した画素の数に画素の大きさを掛けた長さが
   `ridge_min_length_nm`（既定 100<!--c:lib/pipeline.py::ProcParams.ridge_min_length_nm--> nm）以上のものだけを採る。

既定で無効にしているのは、保存してあるパラメータファイルで、それが書かれた
当時の数値を再現できるようにするためである。有効にすると、この段階の処理時間の
大半を Frangi フィルタが占める。

コードでは、スケールの範囲に次の制限を設けている。最小のスケールは 0.6<!--n:literal in the quoted code--> px 以上、
最大のスケールは最小のスケールの 1.5<!--n:literal in the quoted code--> 倍以上にする。また、三角法で決めた低いしきい値が、
大津法で決めた高いしきい値と同じか、それより大きくなったときは、低いしきい値を
高いしきい値の 0.3<!--n:literal in the quoted code--> 倍に置き換える。

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

### 2.7 クロージングで隙間を埋める

最後にマスクへクロージング（closing）をかける。クロージングは §1.4 のオープニングと
順番が逆の処理で、最大値フィルタ（膨張）をかけてから最小値フィルタ（収縮）を
かける。マスクをいったん太らせてから同じだけ細らせるので、太らせたときにふさがった
小さな隙間やくぼみだけが、埋まったまま残る。使うのは `skimage.morphology.closing`
で、窓の形はこの関数の既定の 3<!--n:library default (skimage closing footprint)-->×3<!--n:library default (skimage closing footprint)--> 画素の十字形である。

リッジ回収（§2.6）は、わざとクロージングの「前」に行う。回収した線が、すでにある
かたまりのすぐ隣で終わっていることがある。その線が別の短い繊維として残らず、
クロージングで隣のかたまりとつながるようにするためである。

---

## 3. 細線化

**コード:** `lib/skeletonizer.py`（端点・分岐点の判定などの補助関数は `lib/imp_tools.py`）。
**入力:** `binarized_image`、`calibrated_image`。
**出力:** `skeleton_image`（スケルトン）、`ep`（端点の地図）、`bp`（分岐点の地図）、
およびスケルトンをつながったかたまりに分けた結果（`label_image`、`nLabels`、`data`）。

この段階の目標は、繊維 1<!--n:count--> 本につき幅 1<!--n:definition--> 画素の線（スケルトン）を得ることである。
難しいのは、細線化はマスクの形に忠実に従うのに、そのマスクには欠陥があること
である。マスクの中に開いた穴（マスクに囲まれた背景の部分）、幅のばらつき、繊維の
先端の低い裾などである。こうした欠陥は、
どれもスケルトンの上では枝分かれや輪になって現れる。キンク検出の段階（§4.1）では、
スケルトンを分岐点のところで切ってから、線を 1<!--n:count--> 本ずつたどる。そのため、欠陥から
生まれた分岐点があると、単にノイズが増えるだけではすまず、**本物の繊維が
いくつもの断片に切られてしまう**。この段階の処理の大半は、
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

以下の節は、このコードの順番に沿って説明する。各行と節の対応は次のとおりである。

| コードの行 | 説明している節 |
|---|---|
| `thin_ignoring_image_border(...)` | §3.1（中で使う細線化の仕組みは §3.2） |
| `set_low_bp_coor(...)`、`get_close_eps()`、`prune_branches(...)` | §3.3 |
| `skeletonize(nobranch_image)` | §3.3 の最後（枝を刈った後にもう一度細線化する） |
| `collapse_skeleton_loops(...)` | §3.4 |
| `prune_short_spurs(...)` | §3.5 |
| `prune_terminal_hooks(...)` | §3.6 |
| `remove_small_and_ring(...)` | §3.7 |
| `imp_tools.endPoints(...)`、`imp_tools.branchedPoints(...)` | §3.8 |
| `...`（省略した行） | 途中の結果を残しておく行（実装上のもの。`get_close_eps` は最初のスケルトンをここから読む）と、最後のスケルトンをつながったかたまりに分けて記録する行 |

### 3.1 最初の細線化 — 画像の端で繊維を切らない

最初のスケルトンは `thin_ignoring_image_border` が作る。処理の順番は次のとおりである。

1. マスクをそのまま細線化し、その結果を `plain` とする。
2. 拡張する幅 `pad`（`DEFAULT_BORDER_PAD` = 12<!--c:lib/skeletonizer.py::DEFAULT_BORDER_PAD--> px。利用者が変えるパラメータではなく、固定の
   値）が 0<!--n:literal in the quoted code--> 以下なら、`plain` を返して終わる。
3. 画像のいちばん外側の画素の値を、外へ `pad` 画素分くり返して並べて画像を拡張する
   （`np.pad` の `mode='edge'`）。これを細線化してから拡張した部分を切り落とし、
   その結果を `padded` とする。
4. `plain` にはスケルトンがあるのに `padded` ではスケルトンが消えたかたまりを探し、
   そのかたまりだけ `plain` の結果に戻す。それ以外は `padded` の結果を使う。

**なぜ画像を拡張するのか。** `skimage.morphology.thin` は画像の外を背景とみなす
（§3.2）。そのため、画像の端で切れている繊維を「そこで終わっている繊維」として
細線化する。細線化の線はかたまりの真ん中を通るので、終わっている先端では、線は
先端の形に合わせて曲がる。斜めに切られた先端なら、線は角のほうへ曲がる（図 1<!--n:label--> の
`plain`）。実際には繊維は画像の外へ続いているので、この曲がりは本物の折れでは
ない。画像の外側に端の画素の値をくり返して並べ、繊維が外へ続いているように
すれば、線は曲がらずに画像の端まで届く（図 1<!--n:label--> の `padded`）。

![画像を斜めに横切る繊維の細線化](images/thin_border_oblique.png)

図 1<!--n:label-->: 画像全体を斜めに横切り、上端と下端から外へ出る繊維の合成高さ画像（画像
全体を表示。青線が画像の端）。左から、高さとマスクの縁（height and mask edge）、
拡張せずに細線化した結果（`plain`）、拡張して細線化した結果（`padded`）。黄線は
マスクの縁、赤はスケルトンである。この図のマスクは、説明のため高さが半分を超える
画素として作った（実際の二値化は §2 のしきい値で行う）。`plain` では線の両端が切り口の
角へ曲がる（上端では左の角、下端では右の角）。`padded` では、どちらの端でも尾根の
上をまっすぐ画像の端まで届く。（作図: `scripts/make_doc_figures.py`。実際の
`thin_ignoring_image_border` と同じ計算で描く。）

**拡張すると起きる副作用**

画像の端に沿って横たわる細い繊維（図 2<!--n:label--> の 1<!--n:label--> 枚目の左）は、
拡張すると端の画素がくり返されて、外側へ太くなる。細線化の線は太くなったかたまりの
真ん中を通るので、元の画像の外（拡張した部分）に出てしまう（2<!--n:label--> 枚目）。拡張した
部分を切り落とすと、この線は消える（3<!--n:label--> 枚目）。

**元に戻す処理の役目**

最後の処理は、このように線が消えたかたまりだけを、拡張せずに
細線化した結果（`plain`）に戻す（4<!--n:label--> 枚目）。画像全体を戻さずかたまりごとに戻すのは、
端を横切る繊維では拡張した結果（`padded`）を使い続けるためである。こうして、端を
横切る繊維の線は曲がらず、端に沿った繊維の線も消えない。

**戻さない場合**

端に沿ったかたまりでも、太いものは拡張しても線が残るので、
元には戻さない。このとき線の形は拡張しなかった場合と変わり、その違いは
画像の端から拡張した幅より奥まで及ぶことがある。

![画像の端に沿った繊維と端を横切る繊維の細線化](images/thin_border_along_edge.png)

図 2<!--n:label-->: 画像の上端に沿って横たわる細い繊維（左）と、上端を横切る繊維（右）の合成高さ
画像。上端付近だけを表示している。4<!--n:count--> 枚とも画像の端（青線）の高さをそろえてある。
1<!--n:label--> 枚目（original image）は拡張する前の画像。2<!--n:label--> 枚目（padded image, thinned）は、
拡張した画像を、拡張した上の部分ごと、切り落とす前の状態で細線化したもので、破線が
元の画像の端である。沿った繊維の線は拡張した部分の中に出ている。横切る繊維の線は、
拡張した部分の先端では、ふつうの細線化と同じように少し縮む。3<!--n:label--> 枚目（padding
cropped off）は拡張した部分を切り落とした結果（`padded`）で、沿った繊維の線が消えて
いる。4<!--n:label--> 枚目（after restoring）は `thin_ignoring_image_border` が返す結果で、沿った繊維
だけが `plain` に戻り、横切る繊維は `padded` の曲がらない線のままである。黄線は
マスクの縁、赤はスケルトン。マスクは図 1<!--n:label--> と同じく、説明のため高さが半分を超える
画素として作った。

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

### 3.2 細線化の仕組み

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
（たとえば、マスクの縁から内側へ入り込んだ幅 1<!--n:definition--> 画素の溝の、いちばん奥の画素）を
消さずに残す。

**G3 — $P$ が、今はがしている側にある。** 1<!--n:count--> 回の反復は 2<!--n:count--> 回の小さなステップ
（サブ反復）からなる。1<!--n:label--> つ目のサブ反復では
$(x_2 \lor x_3 \lor \lnot x_8) \land x_1 = 0$ を、2<!--n:label--> つ目では
$(x_6 \lor x_7 \lor \lnot x_4) \land x_5 = 0$ を求める。塗りつぶした長方形で
試すと、1<!--n:label--> つ目は上の端の行と右の端の列を、2<!--n:label--> つ目は左の端の列と下の端の行を
消す。

各サブ反復では、すべての画素を、そのサブ反復を始めた時点の画像で判定する。
つまり、消す画素を先に全部決めてから一度に消す（並列に消す）。2<!--n:count--> つのサブ反復を
交互に繰り返し、1<!--n:count--> 回の反復で何も消えなくなったら終わる。判定には、周りの画素の
並び方 256<!--x:2 ** 8--> 通りのそれぞれについて「消す／消さない」をあらかじめ書いた一覧表を
使う。画像の外は背景として扱う。そのため、スキャンの範囲の外へ続いている
繊維も、画像の端で終わっているものとしてはがされる（§3.1 はこれを避けるために
画像を拡張する）。

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

この例には、細線化の 4<!--n:count--> つの性質が表れている。この段階のこの後の処理は、どれも
この性質への手当てである。

- **線は真ん中を通る。** 両側から 1<!--n:definition--> 枚ずつ皮をはがすので、線は両側のマスクの
  縁のちょうど中間、つまり幅 5<!--n:example--> 画素の帯の真ん中の行に残る。このページで
  「中心軸」と書くときは、この線（マスクの両側の縁の中間を通る線）のことである。
  厳密な中軸変換（`skimage.morphology.medial_axis`。ここでは使っていない）とは
  同じではない。
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

### 3.3 分岐点の高さで決める枝刈り

ここでは、枝を刈るかどうかを分岐点の高さで決める。高さを使う掃除はほかにも
§3.4 のループの高さチェックと §3.6 のフック切除があるが、分岐点を高さで分ける
のはここだけである。

`set_low_bp_coor` は、背景補正後の高さを `bp_height`（既定 10<!--c:lib/pipeline.py::ProcParams.bp_height--> nm）と比べて、
スケルトンの分岐点を**低い**ものと**高い**ものに分ける。§3.3〜§3.5 では、端点から
分岐点までの線を**腕**と呼び、刈ると決めた腕を**枝**と呼ぶ。後で説明する探索で
腕が刈られるのは、低い分岐点にたどり着いたか、行き止まりになったときだけである。
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

「以内」の範囲は、低い分岐点それぞれを中心とする、一辺およそ $2k$ 画素の正方形
（上下左右およそ $k$ 画素以内。$k$ = `branch_length`）である。コードでは、低い分岐点の
印に `scipy.ndimage.maximum_filter`（一辺 $2k$ 画素の正方形の中でいちばん大きい値を
取るフィルタ）をかけて作る。

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

各歩では、まず行き止まりかどうか、次に低い分岐点に接しているか、最後に高い
分岐点に接しているかを調べる。どれも、今いる画素の周りの 3<!--n:definition-->×3<!--n:definition--> 画素で調べる。
腕を刈るときは、それまでにたどった画素を枝として記録する。下のコードでは、
`x` が行番号、`y` が列番号である。

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

探索は画像全体の上を歩くので、端点の周りだけを切り出して調べる場合と違い、
切り出した範囲の外へ続く繊維を行き止まりと読み違えることはない。また、
「もう通った画素」の記録は端点ごとに別々に持つ。そのため、どの端点から調べても
結果は同じである。

画像の端から `branch_length` 以内にある端点は調べない。端の近くで終わる腕は、枝の
先ではなく、画像の外へ抜けていく繊維だからである。

`prune_branches` は、刈ると決めた枝の画素をスケルトンから引く。

```python
# source: lib/skeletonizer.py::Skeletonizer.prune_branches
branches_image = self.calc_branches_image(calibrated_image, init_skeleton_image)
return init_skeleton_image - branches_image
```

枝を刈った後のスケルトンは、`Skeletonizer.__call__` が `skimage.morphology.skeletonize`
（2<!--n:definition--> 次元の画像では、既定で Zhang と Suen の細線化。1984<!--n:citation-->、*Comm. ACM* 27<!--n:citation-->(3<!--n:citation-->), 236–239<!--n:citation-->）で
もう一度細線化し、刈った跡を幅 1<!--n:definition--> 画素に整える。手を加えた場所以外はすでに幅 1<!--n:definition--> 画素
なので、そこは変わらない。§3.4 でも同じ使い方をする。ただし、太いマスクに
かけると `skimage.morphology.thin` と結果が違うことがあるので、最初のスケルトンは
必ず `skimage.morphology.thin` で作る（§3.1）。

### 3.4 偽物の輪（ループ）をつぶす

二値マスクに穴があると、つながり方を保つ細線化（§3.2）は、穴を囲む二重の経路を
残し、その輪の上に分岐点を作る。`collapse_skeleton_loops` は、こうしてスケルトンに
**ぐるりと囲まれた**背景の領域を探す。

スケルトンは斜めも含めて（8<!--n:definition--> 連結で）つながっているので、背景のほうは上下左右
だけで（4<!--n:literal in the quoted code--> 連結で）つながったかたまりに分ける。背景も斜めでつながるとすると、
スケルトンが斜めに 1<!--n:count--> 歩進むところで、線の内側と外側の背景が角で触れてつながって
しまい、輪の内側を外側と区別できないからである。こうして分けたかたまりのうち、
囲む長方形が画像の端に触れていないものが、本当の穴である。面積が `max_loop_area`
（既定 100<!--c:lib/pipeline.py::ProcParams.max_loop_area--> 画素）以下の穴を塗りつぶしてから細線化し直し、二重の経路を
1<!--n:count--> 本の線に戻す。すでに幅 1<!--n:definition--> 画素の線は、細線化し直しても変わらない。そのため、
塗りつぶした場所から離れたスケルトンの画素は、同じ位置に残る。キンクや端点の
ように画素の位置で決まる点も、そうした場所では変わらない。

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

### 3.5 短いとげ（スパー）を刈る

`prune_short_spurs` は、片方が行き止まりの端点で、もう片方が分岐点につながって
いる、長さ `spur_length`（既定 12<!--c:lib/pipeline.py::ProcParams.spur_length--> px）以下の短いとげ（スパー）を取り除く。

§3.3 と違って高さを使わず、**形（長さ）だけで判断する**。ここが肝心な点である。
繊維の本体から生えたとげは繊維と同じ高さにあるので、高さのしきい値では本物の
交差と見分けられない。しかし長さの上限なら見分けられる。本物の繊維の腕が
そこまで短いことはめったにないからである（ただし、12<!--c:lib/pipeline.py::ProcParams.spur_length--> px が何 nm にあたるかは
画素の大きさで変わる。§5）。

届く範囲に分岐点が無い、ぽつんと離れた短い切れ端は、ここでは扱わない。そうした
切れ端は、§3.3 の条件に当たれば刈られ、面積が `min_area` より小さければ §3.7 で
取り除かれる。

端点が画像の端から `border_margin` = 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px 以内にある腕は、決して刈らない。§3.3 と
同じく、端の近くで終わる腕は、枝の先ではなく画像の外へ続く繊維だからである
（ただし、端からの幅は §3.3 の `branch_length` より狭い）。たとえば、2<!--n:count--> 本の繊維が
画像の端のすぐ手前で触れ合うと、そこに本物の合流点ができ、端までの短い腕が
残る。この腕を刈ると合流点が無くなり、残った 2<!--n:count--> 本の腕が 1<!--n:count--> 本の線としてつながって
しまう。
<!-- TODO(review): §3.3 は branch_length、ここは 2 px と端の幅が違う理由がコードに書かれていない。作者の確認が要る。 -->

端点からたどっていき、次のどれかで止まる。

- **合流点に着いた**: たどってきた腕を刈る（合流点そのものは残す）。合流点とは、
  分岐点のうち、今もスケルトン上の隣の画素を 3<!--n:literal in the quoted code--> つ以上持つものである
  （`_junction_degree`）。分岐点の地図はひと回りの最初に作るので、同じ回の中で
  隣のとげを刈ると、隣の画素が 2<!--n:count--> つに減った分岐点が地図に残る。そのため数え直す。
- **合流点でない場所で道が 2<!--n:count--> つ以上に分かれた、または行き止まりになった**: 刈らない。
- **`spur_length` を超えて歩いた**: 刈らない。

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

### 3.6 線の端の釣り針形の曲がり（フック）を切り取る

`prune_terminal_hooks` は、§3.3〜§3.5 の 3<!--n:count--> つの処理（枝刈り・ループつぶし・とげ刈り）の
どれでも見つけられない欠陥を扱う。二値化で、繊維の先端にある低く広がった「裾」までマスクに入ってしまうと、
細線化はその中心軸を裾のほうへたどり、裾の縁に沿って回り込む。その結果、
**分岐点の無い釣り針のような曲がり（フック）**が線の端に残る。枝刈りには分岐点が、
とげの除去には合流点が、ループつぶしには閉じた穴が必要だが、フックはそのどれも
持たない。

![繊維の先端の裾がつくるフックと、その切除](images/terminal_hook.png)

図 3<!--n:label-->: 先端に低く広がった裾がある繊維の合成高さ画像（画像全体を表示。青線が画像の
端）。左から、高さとマスクの縁（height and mask edge）、細線化した結果（thinned）、
`prune_terminal_hooks` をかけた結果。黄線はマスクの縁、赤はスケルトンである。この図の
マスクは、裾まで含むように低い高さで切って作った（実際の二値化は §2 のしきい値で
行う）。細線化の線は、先端で裾の中へ曲がり込む。`prune_terminal_hooks` は、その
曲がり込んだ部分のうち、高さが本体より低い画素だけを取り除く。（作図:
`scripts/make_doc_figures.py`。実際の `thin_ignoring_image_border` と
`prune_terminal_hooks` で描く。）

フックは、端点の近くで線の向きが折り返していることで見つける。端から
`DEFAULT_HOOK_LENGTH` = 12<!--c:lib/skeletonizer.py::DEFAULT_HOOK_LENGTH--> px 以内で、線が折り返す点（折り返し点）の内角が
`DEFAULT_HOOK_APEX_ANGLE_DEG` = 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度より小さくなる場合である。切り取るのは、背景補正後の
高さが、隣に続く繊維本体の高さの中央値の `DEFAULT_HOOK_HEIGHT_RATIO` = 0.5<!--c:lib/skeletonizer.py::DEFAULT_HOOK_HEIGHT_RATIO--> 倍より
低くなっている画素だけである。したがって、折れ曲がっていても高さが本体のこの
割合以上ある端は切られない。

キンクは、折れの内角が 150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg--> 度以下のときに認める（§4.3。内角が小さいほど
鋭い）。折り返し点の内角の 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度はそれよりずっと鋭いので、キンク検出の邪魔を
しない。切り取る量は、見つかったいちばん奥の折り返し点までに限られるので、
まっすぐなまま薄れていく端が短くされることはない。

マスクが裾を含んでいる以上、フックはそのマスクの中心軸としては正しく、白黒の
形だけでは見分けられない。見分けるには高さの情報が要る。そこでこの処理は、
「繊維の中心線は高さの尾根の上になければならない」という考えで、尾根から外れて
低くなった画素だけを切り取る。

コードでは、各端点から線を最大 30<!--x:12 + 6 + 12--> px たどる（`_walk_from_endpoint`）。内訳は、
折り返し点を探す端から 12<!--c:lib/skeletonizer.py::DEFAULT_HOOK_LENGTH--> px、その点の 6<!--c:lib/skeletonizer.py::_HOOK_DIRECTION_WINDOW--> 歩先の向きを見る分、本体の高さを
測る 12<!--c:lib/skeletonizer.py::_HOOK_BODY_WINDOW--> 画素である。たどった
経路の $j$ 番目の点（$j \le 12$）での折り返しの角度は、6<!--c:lib/skeletonizer.py::_HOOK_DIRECTION_WINDOW--> 歩先の点（$j + 6$）へ向かう
ベクトルと、端点へ戻るベクトルとのなす角である。この角度が 120<!--c:lib/skeletonizer.py::DEFAULT_HOOK_APEX_ANGLE_DEG--> 度より小さく
なる $j$ のうち、いちばん奥のものを折り返し点とする。本体の高さは、折り返し点より先の
12<!--c:lib/skeletonizer.py::_HOOK_BODY_WINDOW--> 画素の高さの中央値である（4<!--n:literal in the quoted code--> 画素以上必要）。端点から順に、高さがその半分
より低いあいだだけ画素を取り除く。ただし折り返し点とそれより先は取り除かない。

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

### 3.7 小さなかたまりと輪を取り除く

`remove_small_and_ring` は、`min_area`（既定 10<!--c:lib/pipeline.py::ProcParams.min_area--> 画素）より小さいかたまりと、
**端点を 1<!--n:count--> つも持たない**かたまりを取り除く。端点の無いかたまりは閉じた輪であり、
端から端へたどる繊維の追跡ではたどれない。そのため、本当に輪の形をした繊維も
ここで取り除かれる。

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

### 3.8 端点と分岐点を見つける

`imp_tools.endPoints` と `imp_tools.branchedPoints` は、スケルトンの各画素の周りの
3<!--n:definition-->×3<!--n:definition--> 画素を、端点や分岐点の並び方のひな形と照らし合わせて分類する。できた `ep`（端点）と `bp`（分岐点）の地図は
バンドルに保存され、後の追跡や、`measure.isolated_fiber_flags` の孤立判定（その
繊維が交差や画像の端で切れずに、全長を測れているかの判定。GUI04 が使う）が使う。

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
**入力:** `skeleton_image`、`calibrated_image`、`bp`。**出力:** 繊維ごとのキンクの
位置と角度、端のそばで判定しなかった折れの位置（§4.4）、およびそれらを画像全体で
1<!--n:count--> つにまとめた一覧。

キンクとは、繊維が**一か所で鋭く折れているところ**であり、なだらかな曲がりとは
区別する。見つけるには、何を「鋭い」とみなすかを決めなければならない。見落と
しやすいが、どれくらいの大きさの目で見るか（尺度）も決めなければならない。
画素の細かさで見れば鋭い折れでも、繊維の太さくらいの目で見ればなだらかな曲がり
かもしれないからである。ここでは、画像に写った繊維の幅を尺度にする。探針で
撮ると繊維は実際より太く写るので、この幅を**見かけの幅** $W$ と呼ぶ（測り方は
§4.2）。$W$ よりずっと近い 2<!--n:count--> つの折れは画像の上で見分けられないので、$W$ を
物差しにする（理由は §4.3 の「尺度とノイズ床」）。

`KinkDetector.__call__` は、追跡したかたまりごとに中心線を置き、その上でキンクを
判定する。中心線の各点はスケルトンの点と 1<!--n:count--> 対 1<!--n:count--> に対応する（§4.2）ので、キンクは、
対応するスケルトンの画素の位置として保存する。

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

### 4.1 たどれる線（トラック）を用意する

`imp_tools.remove_bp` は、各分岐点を中心とする一辺 $(2r+1)$ の正方形（$r$ =
`remove_size` = 1<!--c:lib/imp_tools.py::remove_bp(remove_size)-->）の画素を消す。こうして交差のところでスケルトンを切り、残った
かたまりがどれも枝分かれの無い 1<!--n:count--> 本の線になるようにする。面積が `min_area` = 10<!--c:lib/imp_tools.py::remove_bp(min_area)--> 画素
より小さいかたまりは捨てる（§3.7 のパラメータ `min_area` とは別の、固定の値）。

続いて `imp_tools.remove_Lcorner` が、L 字の角の画素（上と左のように、直角を
なす 2<!--n:count--> 方向の隣にだけ線が続く画素）を取り除き、L 字を斜めの段差にする。L 字の角は、偽物の折れとして数えられ
かねないからである（下のひな形では、1<!--n:definition--> のマスはスケルトン、0<!--n:definition--> のマスは背景でなければ
ならない）。

つながったかたまりごとに、`imp_tools.tracking` が一方の端点からもう一方の端点まで
歩き、画素の位置を**並び順どおりに**返す。出発点は、画像を左上から行ごとに読んだ
ときに先に来る端点である。こうして端から順に並べた、繊維 1<!--n:count--> 本分のスケルトンの
画素の列を、以下では**トラック**と呼ぶ。端点がちょうど 2<!--n:literal in the quoted code--> 個ではないかたまりは
たどれないので、画像全体の処理は止めずに、ログに書いてそのかたまりだけ飛ばす。
飛ばしたかたまりは、キンク判定からも計測からも外れる。

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

### 4.2 繊維の中心線を高さの断面から決める

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

この節では、繊維を横切る向きにとった高さの断面を山の形とみて、そのいちばん高い
点を**頂点**、山の両側の低いところを**ふもと**と呼ぶ。

1. `centerline.measure_apparent_width` が、繊維の見かけの幅 $W$ を測る。トラックの
   各点で高さの断面をとり、その半値全幅（ふもとから測って、頂点までの高さの半分
   以上ある部分の幅）を求める。ふもとの高さには、断面の値を低い順に並べて下から
   10<!--n:literal percentile in centerline.measure_apparent_width--> % の位置にある値を使う。$W$ は、トラック全体でのこの幅の中央値で、繊維
   ごとに 1<!--n:count--> つの値である。この後の手順の長さはすべて $W$ の何倍かで決めるので、
   スキャンの大きさが違っても同じ意味になる。
2. トラックを、標準偏差 $W/4$ のガウス関数でなめらかにし、これを**基準線**とする。
   基準線の各点は、その点の横方向の位置を測るときの原点になる。基準線の向きから
   は、測る方向（繊維に直角な方向、法線方向）が決まる。なめらかにした位置を
   そのまま中心線にはしない。そうすると本物の角まで丸まってしまうからである。
   中心線の位置は、次の手順で高さから測った横方向のずれ（オフセット）で決まる。
3. `centerline.refine_centerline` が、その法線に沿って基準線の点から坂を上り、
   いちばん近い頂点を見つける。届く範囲でいちばん高い点を選ぶわけではないので、
   もっと高い隣の繊維に中心線を横取りされることはない。そのうえで点を、**断面の
   高さが、ふもとと頂点のちょうど中間の高さ（半値）まで下がる 2<!--n:count--> つの位置の
   真ん中**に置く。ここでのふもとは、頂点の左右それぞれの最低値のうち、低いほうで
   ある。
4. この 1<!--n:count--> 本の繊維の位置を決められない断面には「信頼できない」と印を付け、その
   オフセットは測らずに、周りの信頼できる点から補間する。次の断面がこれにあたる。
   - 分岐点から $W$ 以内の断面
   - 半値の幅が $1.5\,W$ を超える断面（繊維が 2<!--n:count--> 本並んでいる）
   - 基準線の点が、見つけた山の半値の範囲の外にある断面（見つけた山が、この繊維
     ではなく別の繊維のもの）
   - 探す範囲の中で、半値まで下がる位置が見つからない断面
   - 山の高さ（頂点とふもとの差）が、この繊維の断面での中央値の
     0.25<!--c:lib/centerline.py::_MIN_CREST_AMPLITUDE_FRAC--> 倍に届かない断面（信号が弱すぎる）

   各点のオフセットは、隣り合う点どうしの差（1<!--n:definition--> 次差分）が大きいほど罰を与える
   平滑化（Whittaker 平滑化）で、トラックに沿ってなめらかにつなぐ。罰の強さは、
   なめらかにする幅が $W/4$ になるように決める。
5. 中心線の各点を、基準線の点から法線方向にそのオフセットだけ動かした位置に置く。
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
できる。また、描画と計測はすべて中心線を使い、除外や連結（GUI04 で、繊維を
手で計測から外したり、交差で切れた断片をつないだりする操作）の対象はスケルトンの
画素で指定する。

前処理（GUI01 と `cli.py process`）は、キンクを判定するときにこの関数で中心線を
作る。`fiber_tracking_image.FiberTrackingImage` は、バンドルを開くときに同じ関数で
中心線を作り直す。だから、画面に出るキンクと、それが載っている中心線は、同じ
1<!--n:count--> つの計算から来ている。

バンドルには形式のバージョンが記録されており、形式によって、キンクを判定した
線が違う。バンドルを開くときにどの線の上に繊維を組み立て直すかは、この
形式で決まる（`bundle_schema.centerline_from_meta`）。形式 1.2<!--n:bundle format version--> では、解析に
使った中心線の種類がバンドルに記録されている（`bundle_schema.CENTERLINE_KEY`）。

| バンドルの形式 | キンクを判定した線 | 組み立て直すときに使う線 |
|---|---|---|
| 1.2<!--n:bundle format version--> | 記録された種類の中心線 | 同じ中心線 |
| 1.1<!--n:bundle format version--> | 既定の中心線（半値の中点） | 既定の中心線 |
| 1.0<!--n:bundle format version--> | スケルトントラック | 再解析されるまでスケルトントラック |

#### 中心線と一緒に返すもの

`centerline.place_centerline` は、中心線と一緒に、その上で計算する数値を左右する
3<!--n:count--> つの情報を、`centerline.CenterlineResult` として返す。

- **$W$ と、それが実際に測った値かどうか**: キンク判定の規則の長さは、すべて
  $W$ の何倍かで決まるので、$W$ がそのまま、その繊維のキンクを判定したときの
  物差しになる。$W$ には繊維そのものの幅だけでなく、探針による広がりも含まれる。
  使える半値の区間を持つ断面が少なすぎるときは、代わりに
  `centerline.FALLBACK_WIDTH_PX`（8<!--c:lib/centerline.py::FALLBACK_WIDTH_PX--> px）を使う。これは繊維の幅をもとにした値では
  なく、ただの画素数なので、代わりの値を使ったことを隠さずに知らせる。各繊維は
  自分の $W$（`Fiber.width_px`、`Fiber.width_measured`）を GUI04 の繊維の一覧と CSV に
  渡す。バンドルには、画像全体での $W$ の中央値と、代わりの値を使ったかたまりの数を
  記録する（`bundle_schema.APPARENT_WIDTH_KEY`）。
- **どの点の位置を実際に決められたか**: 手順 4<!--n:label--> で補間した点は、まっすぐな
  区間の上に並ぶので、そこではキンクも曲率も見つけられない。各点が信頼できたか
  どうかの印（`Fiber.line_reliable`）を持ち、信頼できた点の割合が、一覧と CSV に出る。
- **頂点高さ**: 各点での繊維の高さには、中心線の位置で画像から補間した値では
  なく、**断面のいちばん高い値**（`CenterlineResult.crest`）を使う。中心線は半値の
  真ん中にあるので、左右が非対称な断面では、頂点の真上ではなく横にずれる。
  また双線形補間では、画素の中心と中心の間にある頂点の高さに届かない。
  <!-- TODO(review): 頂点高さも断面を双線形補間した標本の最大値なので（centerline._refine）、画素中心の間にある頂点に届かない点は頂点高さも同じであり、この文は頂点高さを選ぶ理由として区別になっていない。意図を作者に確認すること。 -->
  断面を決められなかった点では、補間した
  点から $W/4$ 以内でいちばん高い値を使う。`Fiber.height`、高さプロファイル、
  すべての高さの統計は、この頂点高さを使う。

#### 別の中心線を選ぶ

標準偏差 $W/4$ でなめらかにする半値の中点は既定の方式だが、`centerline_method`
（GUI01 の Kinkdetector グループ、`cli.py process --centerline`）で、
`centerline.CENTERLINE_METHODS` にある 8<!--c:lib/centerline.py::len(CENTERLINE_METHODS)--> 種類の中心線から 1<!--n:count--> つを選べる。
既定の方式は、合成データと同梱スキャンでの比較を見て、経験的に選んだもので
ある（[個別データでの評価](validation.ja.md) §4.2、§4.3）。ほかの方式も選べるのは、
利用者が自分の画像でこの選び方を確かめられるようにするためである。

どの中心線も、どの画素が 1<!--n:count--> 本の繊維に属すかについてはスケルトンの判断をそのまま
使い、スケルトンの点 1<!--n:count--> つにつき 1<!--n:count--> つの点を返す。断面の読み方（頂点へ上ることと、
半値の高さで信頼できるかを判定すること）は共通で、主に違うのは各点を置く位置
である。ただし、次の例外がある。

- `"half_max_05w"` は、基準線とオフセットをなめらかにする幅が $W/2$ である。
- `"quarter_max"` と `"centroid"` は、自分が読む高さまで断面が下がる位置が、探す
  範囲の中で左右のどちらかでも見つからない断面を、信頼できない点として補間する。
  そのため、信頼できる点と、それにつれて頂点高さ（信頼できない点では近くの
  いちばん高い値を使う）が、既定の方式と違うことがある。

それぞれのコードは [GUI04 のファイバー計測](gui04_measurements.ja.md) §2.8 に
引用している。次の表は、それぞれの中心線が点をどこに置くかをまとめたものである
（「なめらかにする幅」は、基準線とスケルトンではガウス関数の標準偏差、オフセット
では手順 4<!--n:label--> の罰の強さを決める幅である）。

| `centerline_method` | 各点を置く位置 |
|---|---|
| `"half_max_025w"`（既定） | 半値の中点。基準線とオフセットをなめらかにする幅は $W/4$ |
| `"half_max_05w"` | 同じく半値の中点。なめらかにする幅は $W/2$ |
| `"skeleton_pixels"` | スケルトンの画素そのもの |
| `"smoothed_skeleton_05w"`、`"smoothed_skeleton_1w"` | スケルトンを長さ方向に、幅 $W/2$ / $W$ でなめらかにしたもの |
| `"quarter_max"` | 高さが 1/4 になる 2<!--n:count--> 点の中点 |
| `"centroid"` | ふもとより上の高さで重みを付けた重心 |
| `"crest"` | 断面の頂点の位置（放物線を当てて、断面に沿って値を読んだ点と点の間まで求める） |

断面の形が向きによって違う（異方的な）繊維は、ねじれるにつれて、断面のいちばん
高い部分を左右交互に向ける。そのため、頂点の位置（`"crest"`）を中心線にすると、
繊維の軸から左右に揺れる。既定の方式が頂点ではなく半値の中点を使うのは、この
ためである（[個別データでの評価](validation.ja.md) §4.2）。探針が太いと、この片寄りは
画像そのものに含まれてしまい、高さから読み取るどの中心線でも取り除けない。

キンク判定の規則とその長さ（W の何倍か）は、どの中心線でも同じである。その
ため、既定の方式より横方向のノイズが大きい中心線は、それだけで折れを多く
報告する。長さ・高さ・キンクはすべて中心線の選び方で変わるので、違う中心線で
得た結果どうしを比べることはできない。

### 4.3 各折れを超過回転で判定する

**コード:** `KinkDetector.judge_line`（`KinkDetector.kinks_on_line` は、同じ結果を
別の形でまとめて返す）。

この節では、中心線が向きを変えているところを**折れ**と呼ぶ。折れはキンクの候補で
あり、下の規則で認められた折れだけを**キンク**と呼ぶ。

#### 超過回転規則

この規則は、中心線の向き $\theta(s)$ を使う。$s$ は中心線に沿って測った長さ（弧長）
である。中心線の上に $s$ で 0.5<!--c:lib/kink_detector.py::_HEADING_STEP_PX--> px ごとに点を取り直し、各点での向きを、標準偏差
$W/4$ のガウス関数でなめらかにしたものが $\theta(s)$ である
（`kink_detector._heading_profile`）。弧長で表した位置 $p$ では、$p$ を中心とする窓の
中で中心線がどれだけ向きを変えるかを、窓のすぐ外側で繊維がもともとどれくらいの
割合で向きを変えていたかと比べる。

$$
T(p) = \theta(p + c) - \theta(p - c), \qquad c = 0.75\,W
$$

$$
r_{\text{L}} = \frac{\theta(p - c) - \theta(p - c - f)}{f}, \qquad
r_{\text{R}} = \frac{\theta(p + c + f) - \theta(p + c)}{f}, \qquad f = W
$$

$$
E(p) = |T(p)| - 2c \, \max\bigl(0,\ \min(\operatorname{sgn} T(p)\, r_{\text{L}},\ \operatorname{sgn} T(p)\, r_{\text{R}})\bigr)
$$

$T$ は、窓の中で向きが変わった角度（回転角）である。$r_{\text{L}}$ と $r_{\text{R}}$ は、
窓の左右の脇で、長さあたりどれだけ向きが変わっているか（回転率）である。窓の長さは
$2c$ なので、$2c$ に脇の回転率を掛けたものは、「窓の中でも脇と同じ割合で回り続けた
とき」の回転になる。$\operatorname{sgn} T(p)$（$T$ の符号）を掛けるのは、窓の中と同じ
向きに曲がっている脇だけを数えるためである。$E$ を**超過回転**と呼ぶ。窓の中での
回転のうち、脇と同じ割合で回り続けただけでは説明できない分である。

しきい値は、折れの内角で表す。内角は折れの内側の角度で、まっすぐなら 180<!--n:definition--> 度、
鋭く折れるほど小さい。内角 $\phi_{\text{max}}$ の折れは、向きを $180^\circ - \phi_{\text{max}}$
だけ変える。そこで折れは

$$
E \ge 180^\circ - \phi_{\text{max}}
$$

のときキンクと判定する。$\phi_{\text{max}}$ は `kinkangle_deg`（既定
150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg--> 度）なので、既定では超過回転が 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v--> 度以上必要である。形式 1.0<!--n:bundle format version--> の
バンドルに使う折れ線規則（§4.6）も、同じ `kinkangle_deg` を内角のしきい値として
読む。
`pipeline.build_stages` が、検出器に渡す前にラジアンに直す。キンクとして*保存
する*角度は、これとは別に、折れの両側の腕の向きから測る（後の「キンクとして保存する角度」を
参照）。

**なぜ回転そのものではなく超過回転を使うのか。** 窓の中の回転だけを見ると、
キンクだけでなく、なだらかな曲がりまで拾ってしまう。たとえば半径 $3\,W$ の円弧は、
$1.5\,W$ 進むあいだに 29<!--x:degrees(2 * 0.75 / 3)--> 度も向きを変える。しかし円弧は、窓の中でも両脇でも
同じ割合で曲がるので、超過回転はほぼ 0<!--n:analytic (an arc turns at one rate)--> になる。一方、まっすぐな腕にはさまれた
角では、窓の中の回転がそのまま残る。両脇の回転率のうち*小さいほう*を使うのは、
曲線が終わるところにある角では、片方の脇は曲がっていてもう片方はまっすぐだが、
それでも角であることに変わりはないからである。どちらかの脇が逆向きに曲がって
いる場合（階段のような段差をつくる 2<!--n:label--> つ目の折れ）は、何も差し引かない。

![合成した中心線の向き θ(s) と、回転 T・超過回転 E](images/kink_heading.png)

図 4<!--n:label-->: 合成した 3<!--n:count--> 本の中心線の向き $\theta(s)$（画像を通さず、線を検出器に直接渡した。
見かけの幅 $W$ は 8<!--n:example--> px）。横軸は弧長を $W$ で割ったもの、縦軸は向き（度）である。
橙色の帯が窓 $p \pm c$、青い帯が長さ $f$ の左右の脇、破線は「窓の中でも脇の回転率で
回り続けた」ときの向き（差し引く分）を表す。左は、まっすぐな腕にはさまれた角である。
脇は回っていないので何も差し引かず、$E = T$ になる。中は、半径 $3\,W$ の円弧である。
窓の中も脇も同じ割合で回るので、破線は曲線に重なり、$E$ はほぼ 0<!--n:analytic (an arc turns at one rate)--> になる。右は、
2<!--n:count--> つの折れが向きを戻し合って段差をつくる線の、1<!--n:label--> つ目の折れである。右の脇は 2<!--n:label--> つ目の
折れで逆向きに回るので、何も差し引かず、$E = T$ になる。各パネルの上に、実際に
計算した $T$ と $E$ を示す。（作図: `scripts/make_doc_figures.py`。$E$ の式が
`KinkDetector.judge_line` と同じであることを、その出力と照合して確かめる。）

コードでは、`_heading_profile` が点の取り直し・向きの計算・なめらかにする処理を
行い、`excess_profile` が任意の位置で $T$ と $E$ を計算する。端の近くでは脇の
区間が中心線の端で切れて短くなるが、割る長さは $f$ のままである。そのぶん脇の
回転率は小さく見積もられ、差し引く量も小さくなる。判定する折れ（§4.4）のうち
この影響を受けるのは、判定しない範囲から $0.25\,W$ 以内のものだけで、差し引く量は
最大で 1/4 小さくなる。位置 $p$ を採るのは、次の
条件をすべて満たすときだけである。

- 両端から $c$ 以上離れている。これより端に近いと、窓が中心線からはみ出して
  $T$ を計算できない（§4.4 の $1.5\,W$ は、計算できた折れのうち、どこまでを
  判定するかの範囲である）。
- $|T(p)|$ がしきい値以上である。$E$ は $|T|$ を超えないので、この条件は次の
  条件から自動的に満たされる。
- $E(p)$ が、しきい値とノイズ床（後の「尺度とノイズ床」で説明する）の両方以上
  である。既定ではノイズ床を使わない（0<!--c:lib/kink_detector.py::NOISE_SIGMAS--> である）。

しきい値は、ラジアンで表した $\pi - \phi_{\text{max}}$（`turn_threshold`）である。

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

- **曲率がまわりより大きくなる点（曲率の極大）**: 曲率とは、向きが長さあたりに
  変わる速さ $|d\theta/ds|$ のことである。曲率の極大のうち、下限以上のものを候補に
  する。下限は、しきい値ちょうどの折れが窓全体で持つ平均の曲率の半分、つまり
  $0.5 \times (\pi - \phi_{\text{max}}) / (2c)$ である
  （`_CURVATURE_FLOOR_FRAC` = 0.5<!--c:lib/kink_detector.py::_CURVATURE_FLOOR_FRAC-->）。
- **$|T|$ そのものの極大**: ただし、$0.75\,W$ 以内に、上の曲率の極大から採った
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

#### キンクとして保存する角度

キンクかどうかを決めるのは角度ではなく $E$ なので、保存された角度が
`kinkangle_deg` 以下になるとは限らない。

バンドルにキンクの角度として保存する値（`ka`）は、180<!--n:definition--> 度から超過回転を引いた値では
ない。折れの両側にのびる 2<!--n:count--> 本の部分（この節では**腕**と呼ぶ。§3.3〜§3.5 の腕とは別の
もの）がなす内角である（`KinkDetector.judge_line`）。各腕の向きは、折れの位置から $W$ の
半分だけ離れたところ（探針が折れを丸めてしまう範囲の外側）から、$W$ 1<!--c:lib/kink_detector.py::_ARM_LENGTH_WIDTHS--> 個分の長さの
区間で平均した向きである。区間は次の折れの手前で打ち切る。こうして、近くにある
次の折れ（たとえば、2<!--n:count--> つの折れが向きを戻し合って段差をつくるときの 2<!--n:label--> つ目の折れ）
の曲がりが、腕の向きに入り込まないようにする（図 5<!--n:label-->）。判定に使った超過回転も、
角度の隣に保存する（§4.5）。

![段差をつくる一対の折れと、最初の折れの腕](images/kink_arms.png)

図 5<!--n:label-->: それぞれ 45<!--n:example--> 度曲がる 2<!--n:count--> つの折れが段差をつくる、合成の中心線（画像を通さず、
線を検出器に直接渡した。見かけの幅 $W$ は 8<!--n:example--> px、折れの間隔は $1.375\,W$）。
青が 1<!--n:label--> つ目の折れの左の腕、橙が右の腕で、右の腕は 2<!--n:label--> つ目の折れの手前
（$p_{\text{next}} - g$）で打ち切ってある。点線は、打ち切らなかった場合の右の腕である。
打ち切らないと、腕の向きに 2<!--n:label--> つ目の折れの曲がりが入り込み、角度は描いた角より
大きく（浅く）読まれる。図の上に、描いた角の内角、保存された角度、打ち切らなかった
場合の角度を示す。（作図: `scripts/make_doc_figures.py`。腕から読んだ角度を、
`KinkDetector.judge_line` が保存する角度と照合して確かめる。）

**腕のなす角の計算のしかた**

中心線の上で、弧長の位置 $p$ にある折れを考える。$g = 0.5\,W$（`_ARM_GAP_WIDTHS`）、$a = 1.0\,W$
（`_ARM_LENGTH_WIDTHS`）とすると、2<!--n:count--> 本の腕は次の弧長の区間である。

$$
A_{\text{L}} = \bigl[\max(s_0,\ p - g - a,\ p_{\text{prev}} + g),\ p - g\bigr],
\qquad
A_{\text{R}} = \bigl[p + g,\ \min(s_1,\ p + g + a,\ p_{\text{next}} - g)\bigr]
$$

ここで、

- $s_0$ と $s_1$ は、向きを求めた最初の点と最後の点の位置である（始まりの端から
  0.25<!--x:0.5 / 2--> px、終わりの端から 0.25〜0.75<!--x:[0.5 / 2, 0.5 * 1.5]--> px 内側）。
- $p_{\text{prev}}$ と $p_{\text{next}}$ は、候補を 1<!--n:count--> つにまとめた後に残った折れ（端の
  そばで判定しなかったものも含む）のうち、前後でいちばん近いものである。無ければ、
  その項は使わない。

各腕の向き $\bar\theta$ は、区間の中に等間隔に取った 16<!--n:literal in the quoted code--> 点で、なめらかにした後の
向きを読み、平均したものである。内角は

$$
\phi = \max\bigl(0,\ \pi - |\bar\theta_{\text{R}} - \bar\theta_{\text{L}}|\bigr)
$$

である。どちらかの区間が $0.25\,W$（`_ARM_MIN_WIDTHS`）より短いとき、つまり
2<!--n:count--> つの折れが近すぎて間に腕が取れないときは、代わりに $\phi = \pi - E$ を保存
する。そのため `ka` には、腕から読んだ角度と、$\pi - E$ の角度の 2<!--n:count--> 種類が混ざる。
角度は最後に $[10^{-6},\ \pi - 10^{-6}]$ rad の範囲に収め、ラジアンのまま `ka` に
書き込む。折れの位置は、弧長で $p$ にいちばん近い中心線の点とし、キンクの位置
（`kp`）には、その点に対応するスケルトンの画素を書く。2<!--n:count--> つの折れが同じ点に
重なったときは、超過回転の大きいほうを残す。

`measure.compute_fiber_stats` は角度を度に直し（`FiberStats.kink_angles_deg`）、
繊維ごとの値を書き出す CSV にはこの値が入る。`measure.fiber_kink_angle` はその
中央値を繊維ごとの代表値とし、GUI03（多くの画像の繊維の値を集めて、グループ
どうしで比べる画面）はこれをヒストグラムにする。

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

規則の長さはすべて $W$ の何倍かで決まる。$W$ は、画像で見分けられる
細かさの限界（分解能）でもある。探針はどの繊維もおよそ $W$ の幅に広げて写すので、
繊維そのものがどれほど鋭く折れていても、角は中心線の上でおよそ $W$ の長さに
広がる。それよりずっと近い 2<!--n:count--> つの折れは、見分けられない。したがって、$W$ が
十分な画素数で写っている限り、同じ繊維を別の画素の大きさで撮っても、同じ
物差しで判定することになる。ただし、それぞれの長さを $W$ の何倍に
するかは理論から一つに決まるものではない。同梱スキャンを目で見て作った基準で
確かめた、経験的な値である（[個別データでの評価](validation.ja.md) §4.4）。

$W$ ではなく画素の数で決まっているのは、次のものである。

- $W$ を測る手順の中の長さ: 幅を測るときに断面を読む範囲（トラックから
  ±12<!--c:lib/centerline.py::_WIDTH_SEARCH_PX--> px）、$W$ を測れなかったときの代わりの値 `centerline.FALLBACK_WIDTH_PX`
  （8<!--c:lib/centerline.py::FALLBACK_WIDTH_PX--> px）など
- 点を取る間隔: 断面は 0.25<!--c:lib/centerline.py::_WIDTH_STEP_PX--> px、向きは 0.5<!--c:lib/kink_detector.py::_HEADING_STEP_PX--> px

`kink_decompose_px` は、この規則では使わない。使うのは形式 1.0<!--n:bundle format version--> のバンドルの
折れ線規則だけである（§4.6）。

**中心線ごとのノイズ床（既定では無効）**

ノイズ床とは、ノイズだけでも出てしまう
大きさの目安のことである。中心線ごとにこれを決める仕組みも用意してある
（`NOISE_SIGMAS`、`KinkJudgement.noise_excess`）。中心線全体で超過回転がどれくらい
ばらつくかを、中央絶対偏差（中央値からのずれの絶対値の中央値）の 1.4826<!--n:literal in KinkDetector.judge_line; MAD to Gaussian standard deviation--> 倍
（ばらつきが正規分布なら、その標準偏差にあたる）として求め、折れの超過回転が
そのばらつきの `NOISE_SIGMAS` 倍を超えることを求めるものである。既定では**無効**である（`NOISE_SIGMAS` = 0<!--c:lib/kink_detector.py::NOISE_SIGMAS-->）。
無効にした理由は [個別データでの評価](validation.ja.md) §4.7 にある。

### 4.4 端のそばの折れは判定せずに示す

中心線の端から $1.5\,W$ 以内に中心がある折れは、**判定しない**。理由は 2<!--n:count--> つある。

- 端に近い折れでは、端の側の腕が短くなる。目で見た基準で、折れをはっきりした
  キンクと呼ぶのに要した長さに、腕が届かない。
- トラックの端には、繊維の本当の端のほかに、§4.1 の `imp_tools.remove_bp` が交差の
  ところで切った切り口もある。切り口では、中心線が分岐のところの裾につられて
  曲がることがある。

この $1.5\,W$ という範囲は、経験的に選んだ値である
（[個別データでの評価](validation.ja.md) §4.9）。

こうした折れも、捨てずに残しておく。`KinkDetector.kinks_on_line` はこれを別にして
返し、バンドルにも別に保存する（`up`）。各繊維には `Fiber.unjudged_indices` として
渡る。GUI04 はこれを灰色の中が空いた丸で描く。こうして、「判定しなかった」ものと
「測ったうえでしきい値に届かなかった」ものを区別できる。ただし、数には一切
入れない。キンクの数・密度・角度・CSV は、判定したキンクだけを扱う。

GUI04 では、繊維を連結したときと、高さによる絞り込みをしたときに、組み立て直した
繊維に同じ規則をもう一度かける。高さによる絞り込みとは、高さの範囲を指定し、
その範囲に入る部分だけを繊維から取り出す機能である
（`fiber_connector.filter_fibers_by_height`）。連結した繊維が切り口をつなげば、その
折れはもう端のそばではなくなり、判定される。反対に、高さによる絞り込みは繊維を
切るので、新しくできた端のそばの折れは判定されなくなる。

### 4.5 キンクのしきい値も結果と一緒にバンドルに保存する

キンクのパラメータは、解析時の設定としてバンドルの中に書き込まれ（`params`）、
後で `bundle_schema.kink_params_from_meta` がそれを読み出す。バンドルを読む側は、
このうち `kinkangle_deg` を必ず使う。バンドルに入っていないトラック（交差を
またいで連結した繊維や、高さの帯で切り出した繊維の一部）でキンクを計算し直す
ときは、保存してあるキンクの点を生んだのと同じ規則を使わなければならないから
である。その規則を、保存したキンクと一緒に持ち運べる場所は、バンドルしかない。
`kink_decompose_px` も読み出すが、使うのは形式 1.0<!--n:bundle format version--> のバンドルのときだけである
（§4.6）。

キンクのパラメータを `_param.json`（バンドルの隣に置くファイル）から読まないのは、わざとで
ある。このファイルは解析の*入力*であり、解析の後でも書き換えられる。そこから
読むと、解析をやり直していないのに、ファイルを書き換えただけで連結した繊維の
キンクが変わってしまう。

バンドルは、各キンクの角度 `ka` の隣に、判定に使った超過回転（`ke`、
`KinkJudgement.kink_excess`）も保存する。角度は折れの形を表し、超過回転は規則が
実際に試した量を表す。両方あれば、規則を実行し直さなくても、各キンクがしきい値
をどれだけ超えていたかを確かめられる。

### 4.6 古い形式（1.0）のバンドルで使う折れ線の規則

形式 1.0<!--n:bundle format version--> のバンドルのキンクは、スケルトントラックの上で、折れ線規則によって
判定されている。`KinkDetector._binary_decompose_simple` が、**Douglas–Peucker** 法の
考え方でトラックを折れ線に単純化する。弦（折れ線の辺）から
`kink_decompose_px`（既定 3.0<!--c:lib/pipeline.py::ProcParams.kink_decompose_px--> px）以上離れたトラックの点があれば、そこに頂点を
加える。`KinkDetector._detect_kink_from_decomposed_indices` は、頂点のうち、内角
$\phi$ が `kinkangle_deg` 以下で、しかも直線から曲がっている分 $\pi - \phi$ が、頂点の
位置の誤差から来る角度の誤差より大きいものを残す。

$$
\pi - \phi > \frac{2d}{\min(A_{\text{prev}},\, A_{\text{next}})}
$$

ここで $d$ は `kink_decompose_px`、$A_{\text{prev}}$ と $A_{\text{next}}$ は頂点の前後の辺
（ここでの腕）の長さである。単純化は頂点の位置を $d$ の精度でしか決めないので、
頂点が $d$ ずれると、長さ $A$ の腕は約 $d/A$ ラジアン傾く。腕は頂点の両側に
1<!--n:count--> 本ずつあるので、内角は約 $2d/A$ 動く。式の右辺はこの誤差である。

この規則は、画素の許容誤差のほかに物差しを持たない。そのため、なめらかな円弧も
頂点で区切って、キンクとして報告することがある。また、スケルトンの上で判定する
ので、画素の鎖の階段状のギザギザや、幅の広いところでの線のふらつきといった、
繊維そのものには無い折れも報告することがある。形式 1.0<!--n:bundle format version--> のバンドルは、解析し
直すまでスケルトントラックと保存済みのキンクをそのまま使い
（`bundle_schema.centerline_from_meta`）、その中でつなぎ直した繊維もこの規則で
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

## 5. 前処理では行わないこと（計測は別の場所で行う）

ここまでの処理が作るのは、画像（背景補正後の高さ、マスク、スケルトン）と点の
一覧（端点、分岐点、キンク）である。そこから数値を計算する作業は別の場所で行う。
この役割分担をはっきりさせてあるので、画像を解析し直さなくても計測だけを
やり直せる。

- **繊維ごとの計測**（繊維に沿った長さ、高さの統計、まっすぐさ、曲率、キンクの密度）は
  `lib/measure.py` にあり、GUI03、GUI04、`cli.py measure` が同じものを使う。どの
  繊維も §4.2 の中心線に沿って測る（形式 1.0<!--n:bundle format version--> のバンドルでは、§4.2 の表の
  とおりスケルトントラックに沿って測る）。中心線は、バンドルを開くときに
  `fiber_tracking_image.FiberTrackingImage` が、保存してあるスケルトンと高さから
  作り直す。次の 2<!--n:count--> つの決まりは、§4.1 の切り方と §4.4 の判定範囲に合わせたもので
  ある。
  - **高さの統計**: §4.2 の頂点高さについて取り、繊維の本当の端ではなく切り口で
    ある端では、最後の $W$ の分を除く（`measure.height_sample_mask`）。
    §4.1 が消すのは分岐点の周りの 3<!--c:lib/imp_tools.py::remove_bp(remove_size)|2 * v + 1-->×3<!--c:lib/imp_tools.py::remove_bp(remove_size)|2 * v + 1--> 画素だけだが、
  交差での相手繊維の裾はその先 1 幅ほど広がるため、それらの標本は一部が相手の
    繊維の高さである。中央値はその影響をほとんど受けないが、最大値は交差の高さを
    拾ってしまう。<!-- TODO(review): 「1 幅ほど」は scripts/measure_docs.py のどの実験も測っていない。CUT_END_EXCLUSION_WIDTHS の根拠として書かれたものである。 -->
    繊維をつなぐ処理が橋渡しのために補間した高さも、画像から測った値ではない
    ので除く。
  - **キンクの密度**（`measure.fiber_kink_density`）: **判定した**長さ、つまり繊維に
    沿った長さから両端の $1.5\,W$ ずつを引いた長さで割る。§4.4 のとおり、それより
    端に近い折れは判定しないからである。繊維全体の長さで割ると、判定していない
    両端の分だけ値が小さく出て、繊維が短いほどそのずれは大きくなる。
- 交差で切れた**断片をつなぎ直す処理**は `lib/fiber_connector.py` にある。つなぐ
  相手を探すのは GUI04 だけで、ほかのところは、その探索で記録した連結の情報を
  そのまま使う。
- **手で除外する処理**は `lib/fiber_selection.py` にある。
- **画素の大きさ**を使うのは計測のときだけである。ここまでの各段階は、既定では
  使わないリッジ回収（§2.6。設定値が nm なので、画素の大きさが分からなければ
  実行しない）を除いて、画素を単位にしている。だからこそ、スキャンの大きさが
  記録されていてもいなくても、各段階のパラメータは同じ意味を持つ。その裏返しとして、
  同じパラメータファイルでも、スキャンの大きさによって実際の長さは変わる。たとえば
  とげの長さの上限 12<!--c:lib/pipeline.py::ProcParams.spur_length--> px は、1<!--n:count--> 辺 1024<!--n:example--> 画素で撮った場合、走査範囲が 2<!--n:example--> µm なら
  約 23<!--x:12 * 2000 / 1024--> nm、10<!--n:example--> µm なら約 117<!--x:12 * 10000 / 1024--> nm にあたる。そこで、スキャンの
  大きさが分かっているときは、画素で決めた各設定が何 nm にあたったかをバンドルに
  記録し（`bundle_schema.PIXEL_LENGTHS_KEY`、`pipeline.pixel_lengths_nm` による）、
  GUI01 はそれをログに出す。この記録があれば、2<!--n:count--> つのバンドルの各段階の設定が、
  実際の長さとして同じだったかどうかを比べられる。

## 6. 結果を再現する

このソフトウェアが出す数値は、次の 3<!--n:count--> つの記録があれば一通りに決まる。

| 記録 | 記録する内容 |
|---|---|
| `<input_stem>_param.json` | 解析に使ったすべての `ProcParams` の項目。項目の名前は変えないことにしているので、古いファイルも読み込める。 |
| `<input_stem>.b2z` | 各段階の出力（画像と点の一覧）、バンドルの形式のバージョン、キンクを判定した中心線（形式 1.2<!--n:bundle format version--> から）、スキャンの大きさとその出どころ、一部の走査ラインだけを解析した場合はその範囲、および解析に使ったパラメータ。 |
| ソフトウェアのバージョン | バンドルに記録される。数値が変わる変更は `CHANGELOG.md` にはっきり書かれる。 |

解析の出力を変える変更は、再現性を壊す変更として扱う。プログラムの使い方が
変わるかどうかに関係なく、その変更が入ったバージョンの `CHANGELOG.md` にはっきり書く。
