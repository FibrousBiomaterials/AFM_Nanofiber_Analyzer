# -*- coding: utf-8 -*-
"""
Review fiber-connection candidates and record the judgements for training.
ファイバー連結候補を検分し、学習用に判断を記録する。

The connection model cannot be distilled from the existing pipeline: no rule in
it knows which skeleton fragments belong to the same fibril, and that judgement
is exactly what is being learned. This GUI is where a person supplies it. It
loads a ``.b2z`` bundle, proposes candidate connections between fragment ends,
lets the reviewer mark each one, and writes the result to a label sidecar
beside the bundle. Output is one ``<stem>_connect_labels.json`` per bundle; the
``.b2z`` itself is never modified.
連結モデルは既存パイプラインから蒸留できない。どの骨格断片が同一フィブリルに属するかを
知る規則はパイプラインに無く、その判断こそが学習対象だからである。本 GUI はそれを人が
与える場所である。``.b2z`` バンドルを読み込み、断片端どうしの連結候補を提示し、検分者が
各候補に印を付け、結果をバンドルの隣のラベル sidecar へ書き出す。出力はバンドルごとに
1 つの ``<stem>_connect_labels.json`` で、``.b2z`` 自体は決して変更しない。

Candidates are proposed by distance alone, deliberately more loosely than the
classical connector's combined distance, angle, and height gates. A reviewer
who only ever saw pairs the rule already likes could not supply a genuine
negative, nor reveal a correct join the rule's gates throw away.
候補は距離のみで提示し、古典的な連結器が用いる距離・角度・高さの複合ゲートより意図的に
緩くする。規則が既に気に入っているペアしか検分者が見ないなら、本物の負例を与えることも、
規則のゲートが捨てている正しい連結を明らかにすることもできないためである。

This is an annotation tool, not a measurement tool. GUI04 remains the place
fiber statistics are produced, and is not modified: a model must first be shown
to beat the classical rule in GUI06 before it is offered there.
本ツールはアノテーション用であり計測用ではない。ファイバー統計を生成する場所は GUI04 の
ままで、GUI04 は変更しない。モデルは GUI06 で古典ルールを上回ると示せてから、はじめて
GUI04 で提供される。
"""

# ===== Plugin metadata =====
# Main.py reads this dictionary with AST parsing for the launcher screen.
# Values must remain plain string literals because they are passed to literal_eval.
# Main.py がこのファイルを AST 解析で読み取るため、値は literal_eval 可能な
# 文字列リテラルのままにする（_() で包まない）。
PLUGIN_INFO = {
    "name": "ML Connect Annotator",
    "description": (
        "Review fiber-connection candidates in a .b2z bundle and record which "
        "fragment ends belong to the same fibril. Click a candidate to cycle "
        "its verdict, add a connection the proposals missed, and save the "
        "judgements to a label file beside the bundle. Those labels train the "
        "connection model; the bundle itself is never modified."
    )
}

# ===== Standard library =====
import os
import queue
import threading
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== GUI libraries =====
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# ===== Project libraries =====
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, setup_ttk_theme, setup_matplotlib_style,
    create_scrolled_text, compute_auto_vrange,
    save_figure_with_dialog, drain_ui_queue, LogMixin, ToolTip,
)

# Verdict identifiers, mirroring lib.ml_connect_labels. Kept as local literals
# so plugin startup does not import the label module; the worker imports it.
# 判定識別子。lib.ml_connect_labels と一致させる。プラグイン起動時に当該モジュールを
# import しないようローカルのリテラルとして保持し、ワーカーが import する。
VERDICT_UNREVIEWED = "unreviewed"
VERDICT_CONNECT = "connect"
VERDICT_REJECT = "reject"
VERDICT_UNCERTAIN = "uncertain"

# The order a click cycles through. Starting from unreviewed, one click means
# "connect" because that is the common judgement on a proposed candidate; a
# second says "reject"; a third defers.
# クリックで巡回する順序。unreviewed から 1 回のクリックで "connect" とするのは、
# 提示された候補に対する判断として最も多いためである。2 回目で "reject"、
# 3 回目で保留。
VERDICT_CYCLE = (
    VERDICT_UNREVIEWED, VERDICT_CONNECT, VERDICT_REJECT, VERDICT_UNCERTAIN)

# Colors used to draw a candidate by verdict. Plot styling, not localized text.
# 判定ごとに候補を描く色。プロットの体裁であり、ローカライズ対象の文字列ではない。
VERDICT_COLORS = {
    VERDICT_UNREVIEWED: "#9e9e9e",
    VERDICT_CONNECT: "#2e7d32",
    VERDICT_REJECT: "#c62828",
    VERDICT_UNCERTAIN: "#ef6c00",
}

# Click tolerance in pixels of the image: a click farther than this from every
# candidate's midpoint changes nothing, so a stray click cannot silently
# relabel a candidate the reviewer did not mean to touch.
# 画像画素単位のクリック許容距離。すべての候補の中点からこれより遠いクリックは
# 何も変えない。誤クリックが、検分者の意図しない候補を黙って付け替えないようにする。
CLICK_TOLERANCE_PX = 12.0


class App(tk.Tk, LogMixin):
    """
    Main window for reviewing and recording fiber-connection judgements.
    ファイバー連結の判断を検分・記録するメインウィンドウ。
    """

    def __init__(self) -> None:
        """
        Initialize the window, state, controls, and figure.
        ウィンドウ・状態・操作部・図を初期化する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])

        setup_matplotlib_style(font_size=10)
        self._clam_bg = setup_ttk_theme(self)
        apply_window_size(self, 1320, 860, min_w=1050, min_h=700)

        # Loaded bundle state; all None until a bundle is opened.
        # 読み込んだバンドルの状態。バンドルを開くまではすべて None。
        self._bundle_path: str = ""
        self._calibrated: Optional[np.ndarray] = None
        self._skeleton_hash: str = ""
        self._input_sha256: Optional[str] = None
        # Candidates as dicts: {"a": (x, y), "b": (x, y), "frags": (i, j),
        # "verdict": str, "source": str}. Endpoint coordinates are the identity,
        # matching what the label sidecar records.
        # 候補は辞書 {"a": (x, y), "b": (x, y), "frags": (i, j), "verdict": str,
        # "source": str}。端点座標が同一性を担い、ラベル sidecar の記録と一致する。
        self._candidates: List[Dict] = []
        self._endpoints: List[Tuple[int, int]] = []
        self._gate_px: float = 20.0
        # Endpoint picked first while adding a connection by hand.
        # 手動で連結を追加する際に最初に選んだ端点。
        self._pending_manual: Optional[Tuple[int, int]] = None
        self._dirty = False

        self.ui_queue: queue.Queue = queue.Queue()
        self.is_running = False

        self._build_ui()
        self._log_initial_message()
        self._update_controls_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        """
        Build the two-pane layout: controls left, image and log right.
        2 ペイン構成を構築する。左が操作部、右が画像とログ。
        """
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=1)
        outer.add(right, weight=4)

        self._build_bundle_panel(left)
        self._build_review_panel(left)
        self._build_action_bar(left)

        self._build_figure_panel(right)
        self._build_log_panel(right)

    def _build_bundle_panel(self, parent: ttk.Frame) -> None:
        """
        Build the bundle-open control and the candidate distance gate.
        バンドルを開く操作部と、候補の距離ゲートを構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("バンドル（.b2z）"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        self.btn_open = ttk.Button(
            lf, text=_("バンドルを開く..."), command=self.on_open_bundle)
        self.btn_open.pack(anchor="w", padx=6, pady=4)

        self.bundle_var = tk.StringVar(value=_("未読み込み。"))
        ttk.Label(lf, textvariable=self.bundle_var, justify="left").pack(
            anchor="w", padx=6, pady=(0, 4))

        row = ttk.Frame(lf)
        row.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(row, text=_("候補の距離上限 (px)")).pack(side=tk.LEFT)
        self.gate_var = tk.StringVar(value="20")
        entry = ttk.Entry(row, textvariable=self.gate_var, width=7)
        entry.pack(side=tk.LEFT, padx=4)
        ToolTip(entry, _("この距離より近い端点の組を候補として提示します。"
                         "古典的な連結器より緩くすることで、規則が捨てる正しい連結も"
                         "検分できます。"))

    def _build_review_panel(self, parent: ttk.Frame) -> None:
        """
        Build the verdict legend and the review-progress counters.
        判定の凡例と検分の進捗カウンタを構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("検分"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        # Legend: the verdict identifiers stay fixed English (they are written
        # verbatim into the label file), while the surrounding hint is localized.
        # 凡例：判定識別子はラベルファイルへそのまま書かれるため固定英語のまま、
        # 周囲の説明のみローカライズする。
        for verdict in VERDICT_CYCLE:
            row = ttk.Frame(lf)
            row.pack(fill=tk.X, padx=6, pady=1)
            swatch = tk.Canvas(row, width=14, height=14, highlightthickness=0)
            swatch.create_rectangle(
                0, 0, 14, 14, fill=VERDICT_COLORS[verdict], outline="")
            swatch.pack(side=tk.LEFT, padx=(0, 6))
            ttk.Label(row, text=verdict).pack(side=tk.LEFT)

        ttk.Separator(lf, orient="horizontal").pack(fill=tk.X, padx=6, pady=4)

        self.counts_var = tk.StringVar(value="")
        ttk.Label(lf, textvariable=self.counts_var, justify="left").pack(
            anchor="w", padx=6, pady=(0, 4))

        self.manual_var = tk.BooleanVar(value=False)
        self.chk_manual = ttk.Checkbutton(
            lf, text=_("連結を手動で追加"), variable=self.manual_var,
            command=self._on_manual_toggle)
        self.chk_manual.pack(anchor="w", padx=6, pady=(0, 4))
        ToolTip(self.chk_manual,
                _("端点を 2 つ続けてクリックすると、候補に無い連結を追加します。"
                  "距離ゲートが落とした正しい連結を教師にする唯一の方法です。"))

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        """
        Build the save/reset controls and the progress indicator.
        保存・リセット操作部と進捗表示を構築する。
        """
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, padx=4, pady=(2, 6))

        self.btn_save = ttk.Button(
            bar, text=_("ラベルを保存"), command=self.on_save)
        self.btn_save.pack(side=tk.LEFT, padx=2)
        self.btn_mark_rest = ttk.Button(
            bar, text=_("残りを reject"), command=self.on_mark_rest_reject)
        self.btn_mark_rest.pack(side=tk.LEFT, padx=2)
        ToolTip(self.btn_mark_rest,
                _("未判断の候補をまとめて reject にします。"
                  "正しい連結に印を付け終えた後の仕上げに使います。"))

        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=110)
        self.progress.pack(side=tk.RIGHT, padx=4)

    def _build_figure_panel(self, parent: ttk.Frame) -> None:
        """
        Build the image canvas, its toolbar, and the click handler.
        画像キャンバス、そのツールバー、クリックハンドラを構築する。
        """
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig = plt.Figure(figsize=(7.2, 6.4), dpi=90)
        self.ax = self.fig.add_subplot(111)
        self.ax.axis("off")

        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # NavigationToolbar2Tk uses pack internally, so isolate it in its own
        # frame. Pan and zoom matter here: a dense scan can carry hundreds of
        # candidates that are unreadable at full extent.
        # NavigationToolbar2Tk は内部で pack を使うため専用フレームへ隔離する。
        # Pan と Zoom は重要である。高密度の走査では候補が数百に達し、全体表示では
        # 判読できない。
        toolbar_frame = ttk.Frame(parent)
        toolbar_frame.pack(fill=tk.X, padx=4)
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()
        try:
            self.toolbar.configure(bg=self._clam_bg)
        except tk.TclError:
            pass

        ttk.Button(toolbar_frame, text=_("図を保存..."),
                   command=self.on_save_figure).pack(side=tk.RIGHT, padx=6)

        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.draw()

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        """
        Build the log text area.
        ログテキスト領域を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("ログ"))
        lf.pack(fill=tk.X, padx=4, pady=4)
        self.log_text, _sb = create_scrolled_text(lf, height=5, width=40)
        self.log_text.configure(state=tk.DISABLED)

    # ----- Logging ---------------------------------------------------------
    # `_log` / `_log_exception` come from LogMixin (they drive self.log_text).
    # `_log` / `_log_exception` は LogMixin 由来（self.log_text を操作する）。

    def _log_initial_message(self) -> None:
        """
        Log a short usage hint at startup.
        起動時に短い使い方の案内をログへ表示する。
        """
        self._log(_("バンドルを開き、候補をクリックして判定を切り替えます。"
                    "保存するとバンドルの隣にラベルファイルが書かれます。"))

    # ----- Bundle loading --------------------------------------------------

    def on_open_bundle(self) -> None:
        """
        Choose a bundle and load its fragments and candidates in a worker.
        バンドルを選び、その断片と候補をワーカーで読み込む。
        """
        if self.is_running:
            return
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title=_(".b2z バンドルを選択"),
            filetypes=[("b2z bundles", "*.b2z"), ("All files", "*.*")])
        if not path:
            return
        try:
            gate = float(self.gate_var.get().strip())
            if gate <= 0:
                raise ValueError(_("候補の距離上限は正の数にしてください。"))
        except ValueError as exc:
            messagebox.showerror(_("入力エラー"), str(exc))
            return

        self.ui_queue = queue.Queue()
        self._set_running(True)
        self._log(_("{name} を読み込み中...").format(name=os.path.basename(path)))
        threading.Thread(
            target=self._worker_load, args=(path, gate), daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _worker_load(self, path: str, gate: float) -> None:
        """
        Rebuild fragments, propose candidates, and merge any existing labels.
        断片を再構築し、候補を提示し、既存ラベルがあれば統合する。

        Runs off the main thread because rebuilding fragments from a dense scan
        takes seconds. Existing labels are merged by endpoint pair so reopening
        a bundle resumes the review instead of discarding it.
        高密度走査からの断片再構築には数秒かかるためメインスレッド外で実行する。
        既存ラベルは端点ペアで突き合わせて統合し、バンドルを開き直したときに検分を
        破棄せず再開できるようにする。
        """
        try:
            from lib import ml_connect_features as cf
            from lib import ml_connect_labels as cl
            from lib.blosc2_io import load_bundle, load_bundle_meta
            from lib.measure import load_tracking_image
        except ImportError as exc:
            self.ui_queue.put(("fatal", {"text": str(exc)}))
            return

        try:
            arrays = load_bundle(path, keys=["calibrated", "skeletonized"])
            calibrated = arrays["calibrated"]
            skeleton_hash = cl.skeleton_sha256(arrays["skeletonized"])
            meta = load_bundle_meta(path)

            self.ui_queue.put(("log", _("断片を再構築中...")))
            # The pixel size only scales a length no candidate uses, so 1.0
            # avoids requiring a scan size just to annotate.
            # ピクセルサイズは候補が使わない長さを縮尺するだけなので、1.0 とし、
            # アノテーションのためだけに走査範囲を要求しないようにする。
            image = load_tracking_image(path, 1.0)
            fragments = image.fibers_in_image_parallel()
            ends = cf.fragment_ends(fragments)
            pairs = cf.candidate_pairs(fragments, max_gap_px=gate)

            candidates = [
                {"a": a.xy, "b": b.xy,
                 "frags": (a.fragment_index, b.fragment_index),
                 "verdict": VERDICT_UNREVIEWED, "source": "proposed"}
                for a, b in pairs
            ]

            # Merge a previously saved review, matching on the endpoint pair.
            # 以前保存した検分結果を端点ペアで突き合わせて統合する。
            label_path = cl.label_path_for(path)
            restored = 0
            if os.path.exists(label_path):
                labels = cl.load_labels(
                    label_path, expected_skeleton_hash=skeleton_hash)
                by_key = {cl.decision_key(d): d for d in labels["decisions"]}
                for cand in candidates:
                    key = _key(cand["a"], cand["b"])
                    saved = by_key.pop(key, None)
                    if saved is not None:
                        cand["verdict"] = saved["verdict"]
                        cand["source"] = saved["source"]
                        restored += 1
                # Anything left was added by hand and is not in the proposal
                # set; keep it so a manual connection survives reopening.
                # 残ったものは手動追加で提示集合に無い。手動連結が開き直しで
                # 失われないよう保持する。
                for saved in by_key.values():
                    pa, pb = cl.decision_key(saved)
                    candidates.append({
                        "a": pa, "b": pb, "frags": tuple(saved.get("fragments", ()))[:2],
                        "verdict": saved["verdict"], "source": saved["source"]})
                    restored += 1

            self.ui_queue.put(("loaded", {
                "path": path,
                "calibrated": calibrated,
                "skeleton_hash": skeleton_hash,
                "input_sha256": meta.get("input_sha256"),
                "candidates": candidates,
                "endpoints": [e.xy for e in ends],
                "gate": gate,
                "restored": restored,
            }))
        except Exception as exc:  # noqa: BLE001 - report any load failure.
            self.ui_queue.put(("fatal", {
                "text": str(exc), "trace": traceback.format_exc()}))

    # ----- Queue polling ---------------------------------------------------

    def _poll_ui_queue(self) -> None:
        """
        Drain worker messages and keep polling while a worker is active.
        ワーカーメッセージを処理し、ワーカー実行中はポーリングを継続する。
        """
        def _on_loaded(payload):
            self._set_running(False)
            self._handle_loaded(payload)
            return False

        def _on_fatal(payload):
            self._set_running(False)
            messagebox.showerror(_("エラー"), payload.get("text", _("不明なエラー")))
            trace = payload.get("trace", "")
            if trace:
                self._log(trace)
            return False

        should_continue = drain_ui_queue(self.ui_queue, {
            "log": self._log,
            "loaded": _on_loaded,
            "fatal": _on_fatal,
        })
        if should_continue:
            self.after(50, self._poll_ui_queue)

    def _handle_loaded(self, payload: Dict) -> None:
        """
        Store the loaded bundle and draw its candidates.
        読み込んだバンドルを保存し、その候補を描画する。
        """
        self._bundle_path = payload["path"]
        self._calibrated = payload["calibrated"]
        self._skeleton_hash = payload["skeleton_hash"]
        self._input_sha256 = payload["input_sha256"]
        self._candidates = payload["candidates"]
        self._endpoints = payload["endpoints"]
        self._gate_px = payload["gate"]
        self._pending_manual = None
        self._dirty = False

        self.bundle_var.set(os.path.basename(self._bundle_path))
        self._log(_("候補 {n} 件を提示しました。").format(n=len(self._candidates)))
        if payload["restored"]:
            self._log(_("既存ラベルから {n} 件を復元しました。").format(
                n=payload["restored"]))
        self._draw()
        self._update_counts()
        self._update_controls_state()

    # ----- Drawing ---------------------------------------------------------

    def _draw(self) -> None:
        """
        Draw the calibrated image, the fragment ends, and every candidate.
        補正済み画像・断片端・全候補を描画する。
        """
        self.ax.clear()
        self.ax.axis("off")
        if self._calibrated is None:
            self.canvas.draw()
            return

        vmin, vmax = compute_auto_vrange(self._calibrated)
        self.ax.imshow(self._calibrated, cmap="afmhot", vmin=vmin, vmax=vmax)

        if self._endpoints:
            xs = [p[0] for p in self._endpoints]
            ys = [p[1] for p in self._endpoints]
            self.ax.plot(xs, ys, linestyle="none", marker="o", markersize=2.5,
                         color="#29b6f6", markeredgewidth=0)

        for cand in self._candidates:
            (ax_, ay), (bx, by) = cand["a"], cand["b"]
            # A hand-added connection is dashed so it stays distinguishable
            # from a proposed one after reopening the bundle.
            # 手動追加の連結は破線にし、バンドルを開き直した後も提示候補と
            # 区別できるようにする。
            style = "--" if cand["source"] == "manual" else "-"
            self.ax.plot([ax_, bx], [ay, by], style, linewidth=1.4,
                         color=VERDICT_COLORS[cand["verdict"]])

        if self._pending_manual is not None:
            px, py = self._pending_manual
            self.ax.plot([px], [py], linestyle="none", marker="o",
                         markersize=9, markerfacecolor="none",
                         markeredgecolor="#ffffff", markeredgewidth=1.6)

        self.fig.tight_layout()
        self.canvas.draw()

    # ----- Interaction -----------------------------------------------------

    def _on_click(self, event) -> None:
        """
        Cycle a candidate's verdict, or build a manual connection.
        候補の判定を巡回させる、または手動連結を作る。

        Ignored while a toolbar mode is active so panning or zooming cannot
        relabel a candidate as a side effect.
        ツールバーのモード実行中は無視する。パンやズームの副作用で候補が
        付け替えられないようにする。
        """
        if self.is_running or event.inaxes is not self.ax:
            return
        if getattr(self.toolbar, "mode", ""):
            return
        if event.xdata is None or event.ydata is None:
            return

        click = (float(event.xdata), float(event.ydata))
        if self.manual_var.get():
            self._handle_manual_click(click)
            return

        index = self._nearest_candidate(click)
        if index is None:
            return
        cand = self._candidates[index]
        position = VERDICT_CYCLE.index(cand["verdict"])
        cand["verdict"] = VERDICT_CYCLE[(position + 1) % len(VERDICT_CYCLE)]
        self._dirty = True
        self._draw()
        self._update_counts()

    def _handle_manual_click(self, click: Tuple[float, float]) -> None:
        """
        Pick two endpoints and add the connection between them.
        端点を 2 つ選び、その間の連結を追加する。

        Only real fragment endpoints can be chosen: a label naming a coordinate
        that is not an endpoint would be rejected when the sidecar is read back
        against the skeleton, so the restriction is enforced at input time.
        選べるのは実在する断片端点のみである。端点でない座標を指すラベルは、
        sidecar を骨格と照合して読み戻すときに拒否される。よって入力の時点で
        制限する。
        """
        endpoint = self._nearest_endpoint(click)
        if endpoint is None:
            return
        if self._pending_manual is None:
            self._pending_manual = endpoint
            self._draw()
            return
        if endpoint == self._pending_manual:
            self._pending_manual = None
            self._draw()
            return

        key = _key(self._pending_manual, endpoint)
        if any(_key(c["a"], c["b"]) == key for c in self._candidates):
            self._log(_("その組はすでに候補にあります。"))
        else:
            # A hand-added pair is one the reviewer asserts connects; that is
            # the only reason to add a pair the proposals left out.
            # 手動追加のペアは検分者が「連結する」と主張するものである。提示から
            # 漏れたペアを追加する理由はそれ以外に無い。
            self._candidates.append({
                "a": self._pending_manual, "b": endpoint, "frags": (),
                "verdict": VERDICT_CONNECT, "source": "manual"})
            self._dirty = True
            self._log(_("連結を手動で追加しました。"))
        self._pending_manual = None
        self._draw()
        self._update_counts()

    def _nearest_candidate(self, click: Tuple[float, float]) -> Optional[int]:
        """
        Return the index of the candidate whose midpoint is nearest the click.
        クリックに中点が最も近い候補の添字を返す。

        Returns ``None`` when nothing is within `CLICK_TOLERANCE_PX`.
        `CLICK_TOLERANCE_PX` 以内に何も無ければ ``None`` を返す。
        """
        best_index, best_distance = None, CLICK_TOLERANCE_PX
        for index, cand in enumerate(self._candidates):
            (ax_, ay), (bx, by) = cand["a"], cand["b"]
            mid = (0.5 * (ax_ + bx), 0.5 * (ay + by))
            distance = float(np.hypot(mid[0] - click[0], mid[1] - click[1]))
            if distance < best_distance:
                best_index, best_distance = index, distance
        return best_index

    def _nearest_endpoint(self, click: Tuple[float, float]) -> Optional[Tuple[int, int]]:
        """
        Return the fragment endpoint nearest the click, or None if too far.
        クリックに最も近い断片端点を返す。遠すぎる場合は None。
        """
        best_point, best_distance = None, CLICK_TOLERANCE_PX
        for point in self._endpoints:
            distance = float(np.hypot(point[0] - click[0], point[1] - click[1]))
            if distance < best_distance:
                best_point, best_distance = point, distance
        return best_point

    def _on_manual_toggle(self) -> None:
        """
        Clear a half-finished manual pick when the mode is turned off.
        モードを解除したとき、途中の手動選択を破棄する。
        """
        if not self.manual_var.get() and self._pending_manual is not None:
            self._pending_manual = None
            self._draw()

    def on_mark_rest_reject(self) -> None:
        """
        Set every still-undecided candidate to ``reject``.
        未判断の候補をすべて ``reject`` にする。

        This is the honest way to finish a review: the remaining proposals were
        looked at and found wrong. It is deliberately an explicit action rather
        than an assumption made at save time, because "not marked" and "marked
        wrong" must not be the same thing (see `lib.ml_connect_labels`).
        検分を終える誠実な方法である。残った提示候補は、見た上で誤りと判断された。
        保存時に暗黙に仮定するのではなく明示的な操作にしているのは、「印を付けて
        いない」と「誤りと印を付けた」が同じであってはならないためである
        （`lib.ml_connect_labels` 参照）。
        """
        if not self._candidates:
            return
        remaining = [c for c in self._candidates
                     if c["verdict"] == VERDICT_UNREVIEWED]
        if not remaining:
            self._log(_("未判断の候補はありません。"))
            return
        if not messagebox.askyesno(
            _("確認"),
            _("未判断の {n} 件を reject にします。よろしいですか。").format(
                n=len(remaining))):
            return
        for cand in remaining:
            cand["verdict"] = VERDICT_REJECT
        self._dirty = True
        self._draw()
        self._update_counts()

    # ----- Saving ----------------------------------------------------------

    def on_save(self) -> None:
        """
        Write the current judgements to the label sidecar.
        現在の判断をラベル sidecar へ書き出す。
        """
        if self.is_running or not self._candidates:
            return
        try:
            from lib import ml_connect_labels as cl
            from lib.fiber_connector import ConnectParams
        except ImportError as exc:
            messagebox.showerror(_("エラー"), str(exc))
            return

        from dataclasses import asdict
        # Record the gates the proposals came from. Which candidates a reviewer
        # saw depends on them, so without this the labels cannot be interpreted
        # later, nor can it be told which connections were never offered.
        # 提示の元になったゲートを記録する。検分者がどの候補を見たかはこれに依存
        # するため、これが無いと後からラベルを解釈できず、どの連結がそもそも
        # 提示されなかったかも分からない。
        params = asdict(ConnectParams())
        params["clusters_range"] = float(self._gate_px)

        decisions = [
            cl.make_decision(
                cl.point(*cand["a"]), cl.point(*cand["b"]), cand["verdict"],
                source=cand["source"],
                fragments=list(cand["frags"]) if cand["frags"] else None)
            for cand in self._candidates
        ]
        try:
            labels = cl.make_labels(
                self._bundle_path, self._skeleton_hash, params, decisions,
                created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                input_sha256=self._input_sha256)
            path = cl.save_labels(cl.label_path_for(self._bundle_path), labels)
        except Exception as exc:  # noqa: BLE001 - report any save failure.
            messagebox.showerror(_("保存に失敗しました"), str(exc))
            return

        self._dirty = False
        self._log(_("ラベルを保存しました: {p}").format(p=os.path.basename(path)))
        decided = sum(1 for c in self._candidates
                      if c["verdict"] in (VERDICT_CONNECT, VERDICT_REJECT))
        messagebox.showinfo(
            _("保存しました"),
            _("{decided} 件の判断を保存しました。\n{p}").format(
                decided=decided, p=path))

    def on_save_figure(self) -> None:
        """
        Save the current view via the shared helper.
        現在の表示を共有ヘルパー経由で保存する。
        """
        save_figure_with_dialog(self, self.fig, initial_name="connect_review")

    # ----- State -----------------------------------------------------------

    def _update_counts(self) -> None:
        """
        Refresh the per-verdict counters shown beside the legend.
        凡例の横に表示する判定ごとのカウンタを更新する。
        """
        if not self._candidates:
            self.counts_var.set("")
            return
        counts = {v: 0 for v in VERDICT_CYCLE}
        for cand in self._candidates:
            counts[cand["verdict"]] = counts.get(cand["verdict"], 0) + 1
        total = len(self._candidates)
        decided = counts[VERDICT_CONNECT] + counts[VERDICT_REJECT]
        # Verdict names stay fixed English; the summary sentence is localized.
        # 判定名は固定英語のまま。要約文はローカライズする。
        lines = [
            _("候補 {total} 件中 {decided} 件が学習に使えます。").format(
                total=total, decided=decided),
            "  connect={c}  reject={r}".format(
                c=counts[VERDICT_CONNECT], r=counts[VERDICT_REJECT]),
            "  uncertain={u}  unreviewed={n}".format(
                u=counts[VERDICT_UNCERTAIN], n=counts[VERDICT_UNREVIEWED]),
        ]
        self.counts_var.set("\n".join(lines))

    def _update_controls_state(self) -> None:
        """
        Enable the review controls only once a bundle is loaded.
        バンドルを読み込んだときのみ検分の操作部を有効化する。
        """
        if self.is_running:
            return
        state = tk.NORMAL if self._candidates else tk.DISABLED
        self.btn_save.configure(state=state)
        self.btn_mark_rest.configure(state=state)
        self.chk_manual.configure(state=state)

    def _set_running(self, running: bool) -> None:
        """
        Toggle controls and the progress bar while a worker is active.
        ワーカー実行中に操作部と進捗バーを切り替える。
        """
        self.is_running = running
        self.btn_open.configure(state=tk.DISABLED if running else tk.NORMAL)
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()
            self._update_controls_state()

    def _confirm_discard(self) -> bool:
        """
        Ask before discarding unsaved judgements; return whether to proceed.
        未保存の判断を破棄する前に確認し、続行してよいかを返す。

        The judgements exist only in memory until saved, and a review can
        represent a lot of human effort, so opening another bundle must not
        drop it silently.
        判断は保存するまでメモリ上にしか存在せず、検分には多大な人手がかかりうる。
        別のバンドルを開く操作でそれを黙って捨ててはならない。
        """
        if not self._dirty:
            return True
        return messagebox.askyesno(
            _("未保存の判断"),
            _("保存していない判断があります。破棄して続行しますか。"))

    def _on_close(self) -> None:
        """
        Confirm before closing with unsaved judgements.
        未保存の判断がある状態で閉じる前に確認する。
        """
        if self._confirm_discard():
            self.destroy()


def _key(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """
    Return an order-independent key for an endpoint pair.
    端点ペアに対する順序非依存のキーを返す。

    A connection is undirected, so the same pair written either way must match;
    this mirrors `lib.ml_connect_labels.decision_key` so a saved review is
    matched back to its candidate when a bundle is reopened.
    連結は無向なので、どちらの順で書かれた同じペアも一致しなければならない。
    `lib.ml_connect_labels.decision_key` と同じ規則にし、バンドルを開き直したとき
    保存済みの検分結果が候補へ突き合わされるようにする。
    """
    return (a, b) if a <= b else (b, a)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
