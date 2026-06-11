import ast
import os
import sys
import subprocess
from pathlib import Path
import importlib
import pkgutil
import shutil

# PyInstaller hook utilities（PyInstallerインストール済みが前提）
from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_DIR = Path(__file__).resolve().parent
GUIS_DIR = PROJECT_DIR / "guis"
LIB_DIR = PROJECT_DIR / "lib"
MAIN_PY = PROJECT_DIR / "Main.py"
ASSETS_DIR = PROJECT_DIR / "assets"

SPEC_OUT = PROJECT_DIR / "Main.auto.spec"
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"


def iter_py_files(folder: Path):
    if not folder.exists():
        return []
    return sorted([p for p in folder.glob("*.py") if p.name != "__init__.py"], key=lambda p: p.name.lower())

def top_level_name(mod: str) -> str:
    return mod.split(".", 1)[0]

def extract_imports_from_file(pyfile: Path) -> set[str]:
    """
    ASTで import / from import を拾う。
    ただし動的import(importlib)は拾えないので、後段の「実際にimportしてみる」で補強する。
    """
    src = pyfile.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(src, filename=str(pyfile))
    mods = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(top_level_name(n.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(top_level_name(node.module))

    return mods

def is_probably_stdlib(name: str) -> bool:
    """
    標準ライブラリ／内蔵モジュールなら True（＝collect対象から除外）
    外部パッケージなら False（＝collect_all 対象）
    """
    if not name:
        return True

    # Python 3.10+：標準ライブラリ名の公式リスト
    stdnames = getattr(sys, "stdlib_module_names", None)
    if stdnames is not None and name in stdnames:
        return True

    # built-in（C拡張の内蔵など）
    try:
        spec = importlib.util.find_spec(name)
    except Exception:
        # 判定不能は安全側（=除外しない）に倒す
        return False

    if spec is None:
        # 見つからない＝外部かもしれない（後段で import 失敗が出る）
        return False

    origin = spec.origin
    if origin is None or origin in ("built-in", "frozen"):
        return True

    # site-packages / dist-packages 由来は外部
    o = origin.replace("\\", "/").lower()
    if "/site-packages/" in o or "/dist-packages/" in o:
        return False

    # それ以外（Pythonインストール配下のlib等）は標準扱い
    return True

def ensure_project_on_syspath():
    # ビルド時に guis/ lib/ を import できるように
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))

def import_all_plugins_and_libs():
    """
    実際に import してみて、import 失敗をビルド時に顕在化させる。
    また、import によってロードされた依存の痕跡も拾える（sys.modules など）。
    """
    ensure_project_on_syspath()

    imported = []
    errors = []

    # guis
    for p in iter_py_files(GUIS_DIR):
        mod = f"guis.{p.stem}"
        try:
            importlib.import_module(mod)
            imported.append(mod)
        except Exception as e:
            errors.append((mod, e))

    # lib
    for p in iter_py_files(LIB_DIR):
        mod = f"lib.{p.stem}"
        try:
            importlib.import_module(mod)
            imported.append(mod)
        except Exception as e:
            errors.append((mod, e))

    return imported, errors

def infer_external_top_levels_from_sysmodules() -> set[str]:
    """
    import 実行後の sys.modules から、外部っぽいトップレベル名を集める。
    """
    tops = set()
    for name in list(sys.modules.keys()):
        if not name or name.startswith(("guis.", "lib.")):
            continue
        tl = top_level_name(name)
        if tl and not is_probably_stdlib(tl):
            tops.add(tl)
    return tops

def collect_pyinstaller_materials(packages: set[str]):
    """
    packages（トップレベル）から PyInstaller の hiddenimports/datas/binaries を生成。
    """
    hiddenimports = []
    datas = []
    binaries = []

    for pkg in sorted(packages):
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hiddenimports += h
        except Exception:
            # collect_all が失敗することもあるので submodules にフォールバック
            try:
                hiddenimports += collect_submodules(pkg)
            except Exception:
                # 最後の手段：トップレベルだけでも hidden import
                hiddenimports.append(pkg)

    # 重複除去（順序保持）
    def uniq(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return uniq(hiddenimports), datas, binaries

def write_spec(hiddenimports, datas, binaries, console=False):
    # assets を同梱（あなたの構成に合わせて）
    asset_datas = []
    if (ASSETS_DIR / "afm_symbol.png").exists():
        asset_datas.append((str(ASSETS_DIR / "afm_symbol.png"), "assets"))

    datas_all = datas + asset_datas

    spec = f"""# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{MAIN_PY.as_posix()}'],
    pathex=['{PROJECT_DIR.as_posix()}'],
    binaries={binaries!r},
    datas={datas_all!r},
    hiddenimports={hiddenimports!r},
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console={console},
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Main',
)
"""
    SPEC_OUT.write_text(spec, encoding="utf-8")
    print(f"[OK] Wrote spec: {SPEC_OUT}")

def run_pyinstaller():
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_OUT)]
    print("[RUN]", " ".join(cmd))
    subprocess.check_call(cmd)

def _copy_plugin_folders():
    """
    dist/Main/ へ guis/, lib/, assets/ フォルダを中身ごとコピーする。
    既存のコピー先ディレクトリは一旦削除してから上書きする。
    """
    

    dest_root = DIST_DIR / "Main"
    if not dest_root.exists():
        raise FileNotFoundError(f"dist/Main not found: {dest_root}")

    for src in (GUIS_DIR, LIB_DIR, ASSETS_DIR):
        if not src.exists():
            print(f"  [SKIP] {src.name}/ not found, skipping.")
            continue
        dest = dest_root / src.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        print(f"  [COPY] {src.name}/ -> {dest}")


def main():
    if not MAIN_PY.exists():
        raise FileNotFoundError("Main.py not found")

    print("== 1) Import plugins/libs to surface missing deps ==")
    imported, errors = import_all_plugins_and_libs()

    for m in imported:
        print("  imported:", m)

    if errors:
        print("\n[ERROR] Some modules failed to import. Install missing deps first:")
        for mod, e in errors:
            print(f"  - {mod}: {type(e).__name__}: {e}")
        raise SystemExit(1)

    print("\n== 2) Extract imports by AST ==")
    ast_tops = set()
    for p in iter_py_files(GUIS_DIR) + iter_py_files(LIB_DIR):
        ast_tops |= extract_imports_from_file(p)
    ast_tops = {x for x in ast_tops if x and not is_probably_stdlib(x)}
    print("  AST top-levels:", sorted(ast_tops))

    print("\n== 3) Infer deps from sys.modules after imports ==")
    sysmod_tops = infer_external_top_levels_from_sysmodules()
    print("  sys.modules top-levels:", sorted(sysmod_tops))

    # 両方を統合（AST + 実import痕跡）
    packages = ast_tops | sysmod_tops

    # ここで「プロジェクト内パッケージ名」を除外（guis/lib 自体など）
    packages.discard("guis")
    packages.discard("lib")

    # AST で検出漏れしやすいパッケージを補完（必要に応じて追加）tkinterdnd2はMacでの安定動作のため廃止。今後同モジュールがMac対応したら復活
    # EXTRA_PACKAGES = {"tkinterdnd2"}
    # packages |= EXTRA_PACKAGES

    print("\n== 4) Collect PyInstaller materials ==")
    hiddenimports, datas, binaries = collect_pyinstaller_materials(packages)
    print(f"  packages: {sorted(packages)}")
    print(f"  hiddenimports: {len(hiddenimports)}")
    print(f"  datas: {len(datas)}")
    print(f"  binaries: {len(binaries)}")

    print("\n== 5) Write spec ==")
    use_console = "--debug" in sys.argv
    write_spec(hiddenimports, datas, binaries, console=use_console)

    print("\n== 6) Run PyInstaller ==")
    run_pyinstaller()

    print("\n== 7) Copy plugin folders to dist/Main/ ==")
    _copy_plugin_folders()

    print("\n[DONE] Build succeeded.")

if __name__ == "__main__":
    main()
