# 操作マニュアル

このマニュアルでは AFM Nanofiber Analyzer の使い方を説明します。解析が何を
計算しているかは [algorithms.ja.md](../algorithms.ja.md)、
[gui04_measurements.ja.md](../gui04_measurements.ja.md)、
[gui03_statistics.ja.md](../gui03_statistics.ja.md) で説明しています。

## GUI を使う

各ツールはランチャー（`python Main.py`、または README で説明している起動スクリプト
`run_venv` / `run_conda`）から起動します。ランチャーにはツールごとのボタンが
あります。

- [Format Converter（GUI00）](gui00_format_converter.ja.md): このソフトが読めない
  形式のファイルを、GUI01 で解析できる `.gwy` ファイルに変換する。

## Jupyter を使って Python で解析する

[`notebooks/quickstart.ja.ipynb`](notebooks/quickstart.ja.ipynb) は、GUI を使わずに
Python から解析を実行します。AFM 像を解析して `.b2z` バンドルを作り、すべての繊維を
計測して pandas の表にし、高さ像に計測した中心線とキンクを重ねて描き、表を CSV に
保存し、複数の像をまとめて計測します。
[`notebooks/quickstart.ipynb`](notebooks/quickstart.ipynb) は説明が英語の同じ
ノートブックです。

このパッケージは PyPI では公開していません。リポジトリをチェックアウトした
フォルダから JupyterLab と一緒にインストールし、JupyterLab でノートブックを開いて
ください。

```
python -m pip install .
python -m pip install jupyterlab
python -m jupyter lab
```

ノートブックは `testdata/` に同梱したスキャンを、ノートブック自身のフォルダからの
相対パスで読みます。最初のコードセルで自分のファイルに置き換えてください。
ノートブックは出力なしで保存しているので、表と図は実行すると表示されます。
`tests/test_manual_notebooks.py` がテストスイートの中でノートブックを実行するので、
コードは現在の API に合わせて保たれます。
