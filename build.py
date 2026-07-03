"""
Build helper script for generating a PyInstaller bundle.
PyInstaller バンドルを生成するためのビルド補助スクリプト。

This script scans imports in `Main.py`, `guis/`, and `lib/`, collects
PyInstaller materials for external packages, writes a spec, runs the build,
and copies project and third-party license materials into the bundle.
このスクリプトは `Main.py`、`guis/`、`lib/` の import を走査し、
外部パッケージの PyInstaller 材料を収集して spec を書き出し、ビルドを
実行した後、プロジェクトと第三者依存のライセンス資料をバンドルへコピーする。

`check.py` and `requirements.txt` are intentionally not used as the build
dependency source. PyInstaller also needs standard-library submodules and
plugin-only imports such as `tkinter.colorchooser`, which are visible in source
imports but not in pip package requirements.
`check.py` と `requirements.txt` は、ビルド依存関係の情報源としては
意図的に使わない。PyInstaller には `tkinter.colorchooser` のような
標準ライブラリのサブモジュールやプラグイン内だけの import も必要であり、
それらは pip パッケージ要件ではなくソースコード上の import に現れる。

This only governs what PyInstaller collects, not how the build environment is
provisioned. For a reproducible bundle, install `requirements.lock.txt` into the
build environment before running this script (see README, "Build a standalone
Windows bundle").
これは PyInstaller が収集する対象を規定するだけで、ビルド環境の用意方法とは
別である。再現性のあるバンドルには、本スクリプト実行前に `requirements.lock.txt`
をビルド環境へインストールする（README「Build a standalone Windows bundle」を参照）。
"""

from __future__ import annotations

import ast
import importlib
from importlib import metadata as importlib_metadata
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Requirement markers distinguish runtime dependencies from optional extras.
from packaging.requirements import InvalidRequirement, Requirement

# PyInstaller hook utilities (PyInstaller must be installed beforehand).
from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_DIR = Path(__file__).resolve().parent
GUIS_DIR = PROJECT_DIR / "guis"
LIB_DIR = PROJECT_DIR / "lib"
LOCALE_DIR = PROJECT_DIR / "locale"
MAIN_PY = PROJECT_DIR / "Main.py"
ASSETS_DIR = PROJECT_DIR / "assets"
PROJECT_LICENSE = PROJECT_DIR / "LICENSE"

SPEC_OUT = PROJECT_DIR / "Main.auto.spec"
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"

LOCAL_TOP_LEVEL = {"guis", "lib"}
LICENSE_DIR_NAME = "licenses"
THIRD_PARTY_NOTICES_NAME = "THIRD_PARTY_NOTICES.txt"
MISSING_LICENSE_TEXTS_NAME = "MISSING_LICENSE_TEXTS.txt"
LICENSE_FILE_PREFIXES = (
    "license",
    "licence",
    "copying",
    "notice",
    "copyright",
    "authors",
)
EXTRA_HIDDENIMPORTS = {
    "tkinter.colorchooser",
}


def _canonical_distribution_name(name: str) -> str:
    """
    Return a normalized distribution name for stable paths and comparisons.
    安定したパスと比較に使う正規化済み配布名を返す。
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def _root_distribution_names(import_names: set[str]) -> set[str]:
    """
    Map imported top-level modules to their installed distribution names.
    import されたトップレベルモジュールをインストール済み配布名へ対応付ける。
    """
    package_map = importlib_metadata.packages_distributions()
    names: set[str] = set()
    missing: list[str] = []

    for import_name in sorted(import_names):
        mapped = package_map.get(import_name, [])
        if mapped:
            names.update(mapped)
            continue

        try:
            dist = importlib_metadata.distribution(import_name)
        except importlib_metadata.PackageNotFoundError:
            missing.append(import_name)
            continue
        names.add(dist.metadata.get("Name") or import_name)

    if missing:
        raise RuntimeError(
            "Could not map imported modules to installed distributions: "
            + ", ".join(missing)
        )
    return names


def _runtime_distributions(
    import_names: set[str],
) -> list[importlib_metadata.Distribution]:
    """
    Resolve installed runtime distributions and their dependency closure.
    インストール済み実行時配布とその依存閉包を解決する。

    Optional extras and dependencies whose environment markers do not match
    the build platform are excluded. PyInstaller itself is included for its
    bundled bootloader license, but its build-only dependency closure is not.
    """
    pending = sorted(_root_distribution_names(import_names), reverse=True)
    resolved: dict[str, importlib_metadata.Distribution] = {}

    while pending:
        requested_name = pending.pop()
        try:
            dist = importlib_metadata.distribution(requested_name)
        except importlib_metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                f"Runtime distribution is not installed: {requested_name}"
            ) from exc

        display_name = dist.metadata.get("Name") or requested_name
        key = _canonical_distribution_name(display_name)
        if key in resolved:
            continue
        resolved[key] = dist

        for raw_requirement in dist.requires or []:
            try:
                requirement = Requirement(raw_requirement)
            except InvalidRequirement as exc:
                raise RuntimeError(
                    f"Invalid Requires-Dist entry in {display_name}: "
                    f"{raw_requirement}"
                ) from exc
            if requirement.marker is not None and not requirement.marker.evaluate(
                {"extra": ""}
            ):
                continue
            pending.append(requirement.name)

    try:
        pyinstaller_dist = importlib_metadata.distribution("PyInstaller")
    except importlib_metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "PyInstaller distribution metadata is required to copy its license."
        ) from exc
    pyinstaller_name = pyinstaller_dist.metadata.get("Name") or "PyInstaller"
    resolved[_canonical_distribution_name(pyinstaller_name)] = pyinstaller_dist

    return [resolved[key] for key in sorted(resolved)]


def _distribution_license_label(dist: importlib_metadata.Distribution) -> str:
    """
    Return the clearest available license label for a distribution.
    配布に利用可能な最も明確なライセンス表記を返す。
    """
    name = dist.metadata.get("Name") or ""
    # The PyPI classifier omits the exception that permits shipping its bootloader.
    if _canonical_distribution_name(name) == "pyinstaller":
        return "GPL-2.0-or-later with PyInstaller bootloader exception"

    expression = (dist.metadata.get("License-Expression") or "").strip()
    if expression:
        return expression

    for classifier in dist.metadata.get_all("Classifier") or []:
        prefix = "License :: "
        if classifier.startswith(prefix):
            return classifier.removeprefix(prefix)

    legacy = (dist.metadata.get("License") or "").strip()
    if (
        legacy
        and legacy not in {"UNKNOWN", "{}"}
        and "\n" not in legacy
        and len(legacy) <= 160
    ):
        return legacy
    return "See included license files"


def _is_dist_info_license_path(
    package_path: importlib_metadata.PackagePath,
) -> bool:
    """
    Return whether a path is inside the standardized dist-info license folder.
    パスが標準化されたdist-infoライセンスフォルダ内かどうかを返す。
    """
    parts = package_path.parts
    return any(
        part.casefold().endswith(".dist-info")
        and parts[index + 1].casefold() == "licenses"
        for index, part in enumerate(parts[:-1])
    )


def _is_license_package_path(
    package_path: importlib_metadata.PackagePath,
    declared_files: set[str],
) -> bool:
    """
    Return whether an installed package path contains license material.
    インストール済みパッケージのパスがライセンス資料かどうかを返す。
    """
    posix = package_path.as_posix()
    lower_posix = posix.casefold()

    for declared in declared_files:
        normalized = declared.replace("\\", "/").lstrip("./").casefold()
        if (
            lower_posix == normalized
            or lower_posix.endswith(f"/licenses/{normalized}")
            or lower_posix.endswith(f"/{normalized}")
        ):
            return True

    if _is_dist_info_license_path(package_path):
        return True

    filename = package_path.name.casefold()
    return any(
        filename == prefix
        or filename.startswith(f"{prefix}.")
        or filename.startswith(f"{prefix}-")
        or filename.startswith(f"{prefix}_")
        for prefix in LICENSE_FILE_PREFIXES
    )


def _license_destination_relative(
    package_path: importlib_metadata.PackagePath,
) -> Path:
    """
    Build a safe relative destination while preserving license subdirectories.
    ライセンスのサブディレクトリを保った安全な相対コピー先を組み立てる。
    """
    parts = package_path.parts
    for index, part in enumerate(parts[:-1]):
        if (
            part.casefold().endswith(".dist-info")
            and parts[index + 1].casefold() == "licenses"
        ):
            relative_parts = parts[index + 2 :]
            if relative_parts and all(p not in {"", ".", ".."} for p in relative_parts):
                return Path(*relative_parts)

    if any(part.casefold().endswith(".dist-info") for part in parts):
        return Path(package_path.name)

    safe_parts = [part for part in parts if part not in {"", ".", ".."}]
    if not safe_parts:
        raise RuntimeError(f"Unsafe installed license path: {package_path}")
    return Path(*safe_parts)


def _copy_distribution_license_files(
    dist: importlib_metadata.Distribution,
    license_root: Path,
) -> list[str]:
    """
    Copy one distribution's declared license and notice files.
    1つの配布が宣言するライセンスとNOTICEファイルをコピーする。
    """
    display_name = dist.metadata.get("Name") or "unknown-distribution"
    package_dir = license_root / _canonical_distribution_name(display_name)
    declared_files = {
        value.strip()
        for value in (dist.metadata.get_all("License-File") or [])
        if value.strip()
    }
    package_files = sorted(dist.files or [], key=lambda item: item.as_posix())
    candidates = [
        item
        for item in package_files
        if _is_license_package_path(item, declared_files)
    ]
    standardized = [
        item for item in candidates if _is_dist_info_license_path(item)
    ]
    if standardized:
        # PEP 639 copies all declared texts into this canonical location; using
        # it avoids duplicate copies also present beside package source files.
        candidates = standardized
    copied: list[str] = []

    for package_path in candidates:
        source = Path(dist.locate_file(package_path))
        if not source.is_file():
            continue
        relative = _license_destination_relative(package_path)
        destination = package_dir / relative
        package_root = package_dir.resolve(strict=False)
        destination_resolved = destination.resolve(strict=False)
        if package_root not in destination_resolved.parents:
            raise RuntimeError(
                f"Unsafe license destination for {display_name}: {relative}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if source.read_bytes() != destination.read_bytes():
                raise RuntimeError(
                    f"Conflicting license filenames for {display_name}: {relative}"
                )
        else:
            shutil.copy2(source, destination)
        copied_path = destination.relative_to(license_root).as_posix()
        if copied_path not in copied:
            copied.append(copied_path)

    if not copied:
        legacy_text = (dist.metadata.get("License") or "").strip()
        if "\n" in legacy_text and len(legacy_text) > 160:
            destination = package_dir / "LICENSE.metadata.txt"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(legacy_text + "\n", encoding="utf-8")
            copied.append(destination.relative_to(license_root).as_posix())

    return copied


def _find_python_license_file() -> Path:
    """
    Locate the license for the Python runtime embedded by PyInstaller.
    PyInstallerが同梱するPythonランタイムのライセンスを探す。
    """
    candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
        Path(sys.prefix) / "LICENSE.txt",
        Path(sys.prefix) / "LICENSE",
        Path(sys.executable).resolve().parent / "LICENSE.txt",
        Path(sys.executable).resolve().parent.parent / "LICENSE.txt",
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    raise RuntimeError("Could not locate the Python runtime license file.")


def copy_license_materials(
    import_packages: set[str], *, strict: bool = False
) -> None:
    """
    Copy project and runtime dependency license materials into the bundle.
    プロジェクトと実行時依存のライセンス資料をバンドルへコピーする。

    Parameters
    ----------
    import_packages
        Top-level external package names imported by the application.
        アプリケーションがimportする外部トップレベルパッケージ名。
    strict
        Whether missing full license texts should fail the build.
        ライセンス本文の欠落時にビルドを失敗させるか。

    Returns
    -------
    None
        License files and a manifest are written under `dist/Main`.
        ライセンスファイルとマニフェストを `dist/Main` 配下へ書き出す。

    Raises
    ------
    RuntimeError
        If strict mode is enabled and a runtime license text is missing.
    FileNotFoundError
        If the bundle or project license is missing.
    """
    dest_root = DIST_DIR / "Main"
    if not dest_root.exists():
        raise FileNotFoundError(f"dist/Main not found: {dest_root}")
    if not PROJECT_LICENSE.is_file():
        raise FileNotFoundError(f"Project license not found: {PROJECT_LICENSE}")

    shutil.copy2(PROJECT_LICENSE, dest_root / "LICENSE")

    license_root = dest_root / LICENSE_DIR_NAME
    dest_root_resolved = dest_root.resolve()
    license_root_resolved = license_root.resolve(strict=False)
    if license_root_resolved.parent != dest_root_resolved:
        raise RuntimeError(f"Unsafe license output path: {license_root}")
    if license_root.exists():
        shutil.rmtree(license_root)
    license_root.mkdir(parents=True)

    python_license = _find_python_license_file()
    python_destination = license_root / "python" / python_license.name
    python_destination.parent.mkdir(parents=True)
    shutil.copy2(python_license, python_destination)

    records: list[tuple[str, str, str, list[str]]] = []
    missing: list[tuple[str, str, str]] = []
    for dist in _runtime_distributions(import_packages):
        name = dist.metadata.get("Name") or "unknown-distribution"
        license_label = _distribution_license_label(dist)
        files = _copy_distribution_license_files(dist, license_root)
        if not files:
            missing.append((name, dist.version, license_label))
            continue
        records.append((name, dist.version, license_label, files))

    python_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    manifest_lines = [
        "AFM Nanofiber Analyzer - Third-Party License Manifest",
        "=====================================================",
        "",
        "The project license is distributed as ../LICENSE.",
        "Full third-party license and notice texts are stored below this directory.",
        "",
        f"Python runtime {python_version} - PSF License",
        f"  - {python_destination.relative_to(license_root).as_posix()}",
        "",
    ]
    for name, version, license_label, files in sorted(
        records, key=lambda record: record[0].casefold()
    ):
        manifest_lines.append(f"{name} {version} - {license_label}")
        manifest_lines.extend(f"  - {path}" for path in files)
        manifest_lines.append("")

    if missing:
        manifest_lines.extend(
            [
                "WARNING - Missing full license texts",
                "------------------------------------",
                f"See {MISSING_LICENSE_TEXTS_NAME} for packages whose installed",
                "metadata did not expose a distributable license file.",
                "",
            ]
        )

    manifest_path = license_root / THIRD_PARTY_NOTICES_NAME
    manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")

    missing_path = license_root / MISSING_LICENSE_TEXTS_NAME
    if missing:
        missing_lines = [
            "AFM Nanofiber Analyzer - Missing Third-Party License Texts",
            "==========================================================",
            "",
            "The installed distributions below did not expose a full license file.",
            "Review and add the authoritative license text before public redistribution.",
            "",
        ]
        for name, version, license_label in sorted(
            missing, key=lambda record: record[0].casefold()
        ):
            missing_lines.append(f"- {name} {version} - {license_label}")
        missing_path.write_text("\n".join(missing_lines) + "\n", encoding="utf-8")

    total_files = 1 + sum(len(files) for _, _, _, files in records)
    total_distributions = len(records) + len(missing)
    print(
        f"  [COPY] project LICENSE + {total_files} runtime license files "
        f"for {total_distributions} distributions"
    )
    print(f"  [WRITE] {manifest_path}")
    if missing:
        print(
            f"  [WARN] Full license text was not found for {len(missing)} "
            f"distribution(s); details: {missing_path}"
        )
        if strict:
            missing_names = ", ".join(
                name for name, _, _ in sorted(
                    missing, key=lambda record: record[0].casefold()
                )
            )
            raise RuntimeError(
                "Missing full license texts in strict mode: " + missing_names
            )


def _iter_project_python_files() -> list[Path]:
    """
    Return Python files whose imports define the bundle dependencies.
    バンドル依存関係を決める import を含む Python ファイルを返す。
    """
    files = [MAIN_PY]
    for folder in (GUIS_DIR, LIB_DIR):
        if folder.exists():
            files.extend(sorted(folder.glob("*.py")))
    return [p for p in files if p.exists()]


def _read_python_source(path: Path) -> str:
    """
    Read a Python source file with common project encodings.
    プロジェクトで使われる一般的なエンコーディングで Python ソースを読む。
    """
    for encoding in ("utf-8", "cp932"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _is_importable_module(name: str) -> bool:
    """
    Return whether a dotted name can be resolved as a module.
    ドット区切り名がモジュールとして解決できるかを返す。
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
        return False


def _module_names_from_import(node: ast.AST) -> set[str]:
    """
    Extract importable module names from one AST import node.
    AST の import ノード 1 件から import 可能なモジュール名を取り出す。
    """
    names: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            names.add(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level:
            return names
        base = node.module or ""
        if base:
            names.add(base)
        for alias in node.names:
            if alias.name == "*":
                continue
            candidate = f"{base}.{alias.name}" if base else alias.name
            if _is_importable_module(candidate):
                names.add(candidate)
    return names


def collect_project_imports() -> set[str]:
    """
    Collect import names used by Main.py and project GUI/lib modules.
    Main.py とプロジェクトの GUI/lib モジュールが使う import 名を収集する。

    Returns
    -------
    set of str
        Full module names discovered from static import statements.
        静的 import 文から見つかった完全なモジュール名の集合。
    """
    imports: set[str] = set(EXTRA_HIDDENIMPORTS)
    for path in _iter_project_python_files():
        tree = ast.parse(_read_python_source(path), filename=str(path))
        for node in ast.walk(tree):
            imports.update(_module_names_from_import(node))
    return imports


def _stdlib_module_names() -> set[str]:
    """
    Return top-level module names provided by the Python standard library.
    Python 標準ライブラリが提供するトップレベルモジュール名を返す。
    """
    names = set(sys.builtin_module_names)
    names.update(getattr(sys, "stdlib_module_names", set()))
    return names


def _is_external_top_level(name: str, stdlib: set[str]) -> bool:
    """
    Return whether a dotted import name belongs to an external package.
    ドット区切りの import 名が外部パッケージに属するかを返す。

    External means the top-level package is neither a local project package
    (`guis`, `lib`) nor part of the Python standard library, so PyInstaller
    must collect it.
    外部とは、トップレベルパッケージがローカルのプロジェクトパッケージ
    (`guis`, `lib`) でも Python 標準ライブラリでもないことを指し、
    PyInstaller による収集が必要となる。
    """
    top_level = name.split(".", 1)[0]
    return top_level not in LOCAL_TOP_LEVEL and top_level not in stdlib


def imported_modules_to_collect_packages(imports: set[str]) -> set[str]:
    """
    Select external top-level packages that need PyInstaller collection.
    PyInstaller の収集対象にする外部トップレベルパッケージを選ぶ。

    Parameters
    ----------
    imports
        Full module names found in project source files.
        プロジェクトソースから見つかった完全なモジュール名。

    Returns
    -------
    set of str
        External top-level package names passed to PyInstaller hook helpers.
        PyInstaller hook 補助関数へ渡す外部トップレベルパッケージ名。
    """
    stdlib = _stdlib_module_names()
    packages: set[str] = set()
    for name in imports:
        if _is_external_top_level(name, stdlib):
            packages.add(name.split(".", 1)[0])
    return packages


def ensure_project_on_syspath() -> None:
    """
    Ensure project root is on `sys.path` for dynamic imports.
    動的 import のためにプロジェクトルートを `sys.path` に追加する。

    Returns
    -------
    None
        `sys.path` is updated in place when needed.
        必要に応じて `sys.path` をインプレースで更新する。
    """
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))


def verify_project_modules_importable() -> None:
    """
    Import GUI/lib modules to surface missing dependencies early.
    GUI/lib モジュールを実際に import し、依存不足を早期に顕在化させる。

    This is a pre-flight sanity check independent from dependency
    collection: if a module fails to import, the build cannot succeed,
    so we abort with a clear error message before running PyInstaller.
    これは依存収集とは独立した事前検証である。import に失敗するなら
    ビルドは成功しないので、PyInstaller 実行前に明確なエラーで中断する。

    Raises
    ------
    SystemExit
        If any module fails to import.
        いずれかのモジュールが import に失敗した場合。
    """
    ensure_project_on_syspath()

    errors: list[tuple[str, Exception]] = []

    for folder, prefix in ((GUIS_DIR, "guis"), (LIB_DIR, "lib")):
        if not folder.exists():
            print(f"  [SKIP] {folder.name}/ not found.")
            continue
        for p in sorted(folder.glob("*.py")):
            if p.name == "__init__.py":
                continue
            mod = f"{prefix}.{p.stem}"
            try:
                importlib.import_module(mod)
                print(f"  imported: {mod}")
            except Exception as e:
                errors.append((mod, e))

    if errors:
        print("\n[ERROR] Some modules failed to import. Install missing deps first:")
        for mod, e in errors:
            print(f"  - {mod}: {type(e).__name__}: {e}")
        raise SystemExit(1)


def collect_pyinstaller_materials(
    packages: set[str], project_imports: set[str]
) -> tuple[list[str], list, list]:
    """
    Collect PyInstaller materials from top-level packages.
    トップレベルパッケージ集合から PyInstaller 材料を収集する。

    Parameters
    ----------
    packages
        Top-level import names of external dependencies.
        外部依存のトップレベル import 名集合。
    project_imports
        Full import names discovered in project source files.
        プロジェクトソースから見つかった完全な import 名。

    Returns
    -------
    tuple
        `(hiddenimports, datas, binaries)` for spec generation.
        spec 生成に使う `(hiddenimports, datas, binaries)`。
    """
    stdlib = _stdlib_module_names()
    hiddenimports: list[str] = sorted(
        name
        for name in project_imports
        if name in EXTRA_HIDDENIMPORTS or _is_external_top_level(name, stdlib)
    )
    datas: list = []
    binaries: list = []

    for pkg in sorted(packages):
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hiddenimports += h
        except Exception:
            # Fallback to submodule collection when collect_all fails.
            try:
                hiddenimports += collect_submodules(pkg)
            except Exception:
                # Last resort: include just top-level package as hidden import.
                hiddenimports.append(pkg)

    # Deduplicate while preserving the first-seen order.
    unique_hidden = list(dict.fromkeys(hiddenimports))

    return unique_hidden, datas, binaries


def write_spec(hiddenimports, datas, binaries, console: bool = False) -> None:
    """
    Generate and write PyInstaller spec file.
    PyInstaller 用の spec ファイルを生成して保存する。

    Parameters
    ----------
    hiddenimports
        Hidden imports for Analysis.
        Analysis に渡す hidden import 一覧。
    datas
        Data file mappings for Analysis.
        Analysis に渡すデータファイル定義。
    binaries
        Binary file mappings for Analysis.
        Analysis に渡すバイナリ定義。
    console
        Whether to build console-enabled executable.
        コンソール表示付きでビルドするかどうか。

    Returns
    -------
    None
        The generated spec file is written to `SPEC_OUT`.
        生成した spec ファイルを `SPEC_OUT` に書き出す。
    """
    # Bundle assets based on this project layout.
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


def run_pyinstaller() -> None:
    """
    Execute PyInstaller with generated spec.
    生成した spec を使って PyInstaller を実行する。

    Returns
    -------
    None
        PyInstaller is executed as a subprocess.
        PyInstaller をサブプロセスとして実行する。
    """
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_OUT)]
    print("[RUN]", " ".join(cmd))
    subprocess.check_call(cmd)


def copy_plugin_folders() -> None:
    """
    Copy project plugin/resource folders into `dist/Main/`.
    `dist/Main/` へプロジェクトのプラグイン/リソースフォルダをコピーする。

    Existing destination folders are removed before copy to keep output clean.
    出力をクリーンに保つため、コピー先が既存なら削除してから再コピーする。

    Raises
    ------
    FileNotFoundError
        If `dist/Main` does not exist after build.
        ビルド後に `dist/Main` が存在しない場合。
    """
    dest_root = DIST_DIR / "Main"
    if not dest_root.exists():
        raise FileNotFoundError(f"dist/Main not found: {dest_root}")

    for src in (GUIS_DIR, LIB_DIR, ASSETS_DIR, LOCALE_DIR):
        if not src.exists():
            print(f"  [SKIP] {src.name}/ not found, skipping.")
            continue
        dest = dest_root / src.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        print(f"  [COPY] {src.name}/ -> {dest}")


def main() -> None:
    """
    Run full build workflow from import scanning to final copy.
    import 走査から最終コピーまでのビルド処理全体を実行する。

    Returns
    -------
    None
        Build artifacts are written under the project `build` and `dist` paths.
        ビルド成果物をプロジェクト内の `build` と `dist` に出力する。
    """
    if not MAIN_PY.exists():
        raise FileNotFoundError("Main.py not found")

    print("== 1) Verify project modules are importable ==")
    verify_project_modules_importable()

    print("\n== 2) Scan project imports ==")
    project_imports = collect_project_imports()
    packages = imported_modules_to_collect_packages(project_imports)
    print(f"  project imports: {len(project_imports)}")
    print(f"  external packages: {sorted(packages)}")

    print("\n== 3) Collect PyInstaller materials ==")
    hiddenimports, datas, binaries = collect_pyinstaller_materials(
        packages, project_imports
    )
    print(f"  hiddenimports: {len(hiddenimports)}")
    print(f"  datas: {len(datas)}")
    print(f"  binaries: {len(binaries)}")

    print("\n== 4) Write spec ==")
    use_console = "--debug" in sys.argv
    write_spec(hiddenimports, datas, binaries, console=use_console)

    print("\n== 5) Run PyInstaller ==")
    run_pyinstaller()

    print("\n== 6) Copy plugin folders to dist/Main/ ==")
    copy_plugin_folders()

    print("\n== 7) Copy project and third-party licenses ==")
    copy_license_materials(
        packages, strict="--strict-licenses" in sys.argv
    )

    print("\n[DONE] Build succeeded.")


if __name__ == "__main__":
    # Script entry point when called directly.
    main()
