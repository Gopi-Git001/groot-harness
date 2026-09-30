"""Deterministic page-file helpers: extract files from slices, resolve imports, read exports, walk the import graph."""

import posixpath
import re

ALLOWED_PACKAGES = {
    "react", "react-dom", "clsx", "tailwind-merge", "class-variance-authority", "lucide-react",
    "@radix-ui/react-slot", "@radix-ui/react-dialog", "@radix-ui/react-accordion",
}
HARNESS_OWNED = {"src/main.tsx"}
PAGE_ROOTS = ("src/App.tsx", "src/index.css")
CONFIG_FILES = {"tailwind.config.ts", "tailwind.config.js", "vite.config.ts", "postcss.config.js",
                "tsconfig.json", "package.json", "index.html"}

_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_PATH_COMMENT = re.compile(r"^\s*(?://|/\*|<!--|#)\s*((?:\.{0,2}/)?[\w@./\[\]-]+\.(?:tsx|ts|jsx|js|css|json|html))\b")
_IMPORT = re.compile(
    r"""(?:^|[;\n])\s*(?:import|export)\s+(?:type\s+)?[^'";]*?\bfrom\s*['"]([^'"]+)['"]"""
    r"""|(?:^|[;\n])\s*import\s*['"]([^'"]+)['"]"""
    r"""|\bimport\(\s*['"]([^'"]+)['"]\s*\)"""
    r"""|@import\s+['"]([^'"]+)['"]"""
)
_EXPORT_DECL = re.compile(r"\bexport\s+(?:default\s+)?(?:async\s+)?(?:function|const|let|class|interface|type|enum)\s+(\w+)")
_EXPORT_LIST = re.compile(r"\bexport\s*(?:type\s*)?\{([^}]*)\}")
_RESOLVE_SUFFIXES = ("", ".tsx", ".ts", ".jsx", ".js", ".css", "/index.tsx", "/index.ts")


def normalize_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    path = re.sub(r"^(\./|/)+", "", path)
    if path.startswith("@/"):
        path = "src/" + path[2:]
    if path in CONFIG_FILES or path.startswith("src/"):
        return path
    return "src/" + path


def extract_files(code: str) -> dict[str, str]:
    """Files from fenced blocks whose first line is a path comment."""
    files = {}
    for block in _FENCE.findall(code):
        first, _, rest = block.partition("\n")
        match = _PATH_COMMENT.match(first)
        if match:
            files[normalize_path(match.group(1))] = rest.rstrip() + "\n"
    return files


def imports(content: str) -> list[str]:
    return [next(g for g in m.groups() if g) for m in _IMPORT.finditer(content)]


def package_name(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def is_local(spec: str) -> bool:
    return spec.startswith((".", "@/", "/"))


def resolve(spec: str, importer: str, paths: set[str]) -> str | None:
    """Resolve a local import to a page path, or None if it points nowhere."""
    if spec.startswith("@/"):
        base = "src/" + spec[2:]
    elif spec.startswith("/"):
        base = spec.lstrip("/")
    else:
        base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
    return next((base + s for s in _RESOLVE_SUFFIXES if base + s in paths), None)


def broken_imports(files: dict[str, str]) -> dict[str, list[str]]:
    """Per file: local imports that resolve to nothing, and packages outside the allowed list."""
    paths = set(files) | HARNESS_OWNED
    broken: dict[str, list[str]] = {}
    for path, content in files.items():
        for spec in imports(content):
            if is_local(spec):
                ok = resolve(spec, path, paths) is not None
            else:
                ok = package_name(spec) in ALLOWED_PACKAGES or spec.startswith("react/")
            if not ok:
                broken.setdefault(path, []).append(spec)
    return broken


_IMPORT_CLAUSE = re.compile(r"""\bimport\s+(?!type\b)([^'";]+?)\s+from\s*['"]([^'"]+)['"]""")
_REEXPORT_CLAUSE = re.compile(r"""\bexport\s*(?!type\b)\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]""")


def _member_defined(target: str, name: str, member: str) -> bool:
    """Does the target file give component `name` a `member` (Name.Member = ..., or an object/assign)?"""
    if re.search(rf"\b{name}\.{member}\s*=", target):
        return True
    built = re.search(rf"\b{name}\s*=\s*(?:Object\.assign\(|\{{)", target)
    return bool(built) and bool(re.search(rf"\b{member}\b", target[built.start():]))


def missing_exports(files: dict[str, str]) -> dict[str, list[str]]:
    """Per file: imported names (default or named) that the local target file does not export."""
    paths = set(files) | HARNESS_OWNED
    missing: dict[str, list[str]] = {}
    for path, content in files.items():
        for clause, spec in _IMPORT_CLAUSE.findall(content):
            target = resolve(spec, path, paths) if is_local(spec) else None
            if not target or target not in files or not target.endswith((".ts", ".tsx")):
                continue
            if re.search(r"\bexport\s*\*\s*from", files[target]):
                continue  # Star re-exports: names cannot be checked without following them.
            available = set(exports(files[target]))
            default, _, named = clause.partition("{")
            default = default.strip().rstrip(",").strip()
            if namespace := re.fullmatch(r"\*\s+as\s+(\w+)", default):
                # `import * as NS`: every `NS.Member` used must be exported.
                members = dict.fromkeys(re.findall(rf"\b{namespace.group(1)}\.(\w+)", content))
                for name in members:
                    if name not in available:
                        missing.setdefault(path, []).append(
                            f"uses {namespace.group(1)}.{name}, but {target} does not export '{name}'")
                continue
            wanted = ["default"] if default else []
            locals_ = {"default": default} if default else {}
            for part in named.rstrip("} ").split(","):
                part = part.strip()
                if part and not part.startswith("type "):
                    original, _, alias = part.partition(" as ")
                    wanted.append(original.strip())
                    locals_[original.strip()] = (alias or original).strip()
            for name in wanted:
                if name not in available:
                    label = "a default export" if name == "default" else f"'{name}'"
                    missing.setdefault(path, []).append(f"imports {label} from '{spec}', but {target} does not export it")
            # <Select.Trigger> on an imported component needs Select.Trigger to exist in the target file.
            for exported, local in locals_.items():
                source_name = local if exported == "default" else exported
                for member in dict.fromkeys(re.findall(rf"<{local}\.(\w+)", content)):
                    if not _member_defined(files[target], source_name, member):
                        missing.setdefault(path, []).append(
                            f"uses <{local}.{member}>, but {target} does not define {source_name}.{member}")

        # Barrel re-exports: `export { A, B as C } from './x'` needs A and B exported by ./x.
        for names, spec in _REEXPORT_CLAUSE.findall(content):
            target = resolve(spec, path, paths) if is_local(spec) else None
            if not target or target not in files or re.search(r"\bexport\s*\*\s*from", files[target]):
                continue
            available = set(exports(files[target]))
            for part in names.split(","):
                name = part.strip().split(" as ")[0].strip()
                if name and not name.startswith("type ") and name not in available:
                    missing.setdefault(path, []).append(f"re-exports '{name}' from '{spec}', but {target} does not export it")
    return missing


def import_problems(files: dict[str, str]) -> dict[str, list[str]]:
    """Broken imports and missing exports, per file."""
    problems = {p: [f"'{s}' resolves to nothing or is not an allowed package" for s in specs]
                for p, specs in broken_imports(files).items()}
    for path, found in missing_exports(files).items():
        problems.setdefault(path, []).extend(found)
    return problems


def exports(content: str) -> list[str]:
    names = _EXPORT_DECL.findall(content)
    for group in _EXPORT_LIST.findall(content):
        names += [part.split(" as ")[-1].strip() for part in group.split(",") if part.strip()]
    if re.search(r"\bexport\s+default\b", content):
        names.append("default")
    return list(dict.fromkeys(names))


def reachable(files: dict[str, str], roots=PAGE_ROOTS) -> set[str]:
    """Files reachable through local imports from the page roots."""
    paths = set(files)
    seen: set[str] = set()
    stack = [r for r in roots if r in paths]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        for spec in imports(files[path]):
            if is_local(spec) and (target := resolve(spec, path, paths)):
                stack.append(target)
    return seen


def rewrite_imports(files: dict[str, str], moved: dict[str, str]) -> list[str]:
    """Point imports of removed paths at their replacements. Returns a log line per rewrite."""
    log = []
    paths = set(files) | set(moved)
    for path, content in files.items():
        def swap(match: re.Match) -> str:
            spec = match.group(2)
            target = resolve(spec, path, paths) if is_local(spec) else None
            if target in moved:
                new = "@/" + re.sub(r"\.(tsx|ts|jsx|js)$", "", moved[target])[len("src/"):]
                log.append(f"{path}: '{spec}' -> '{new}'")
                return f"{match.group(1)}{new}{match.group(3)}"
            return match.group(0)
        files[path] = re.sub(r"""(\bfrom\s*['"]|\bimport\s*\(?\s*['"])([^'"]+)(['"])""", swap, content)
    return log


def duplicate_exports(files: dict[str, str]) -> dict[str, list[str]]:
    """Named exports (not 'default') defined in more than one file."""
    owners: dict[str, list[str]] = {}
    for path, content in files.items():
        if path.endswith((".ts", ".tsx")):
            for name in exports(content):
                if name != "default":
                    owners.setdefault(name, []).append(path)
    return {name: paths for name, paths in owners.items() if len(paths) > 1}


# Token names tailwind.config.ts maps to `hsl(var(--name) / <alpha-value>)`.
COLOR_TOKENS = [
    "background", "foreground", "card", "card-foreground", "popover", "popover-foreground",
    "primary", "primary-foreground", "secondary", "secondary-foreground", "muted", "muted-foreground",
    "accent", "accent-foreground", "destructive", "destructive-foreground", "border", "input", "ring",
]
DEFAULT_TOKENS = {
    "background": "0 0% 100%", "foreground": "222 47% 11%", "card": "0 0% 100%",
    "card-foreground": "222 47% 11%", "popover": "0 0% 100%", "popover-foreground": "222 47% 11%",
    "primary": "221 83% 45%", "primary-foreground": "0 0% 100%", "secondary": "210 40% 96%",
    "secondary-foreground": "222 47% 11%", "muted": "210 40% 96%", "muted-foreground": "215 19% 35%",
    "accent": "210 40% 94%", "accent-foreground": "222 47% 11%", "destructive": "0 72% 45%",
    "destructive-foreground": "0 0% 100%", "border": "214 32% 88%", "input": "214 32% 88%",
    "ring": "221 83% 45%",
}
_TOKEN_DECL = re.compile(r"--(?:color-)?([a-z-]+)\s*:\s*([^;]+);")
_JSX = re.compile(r"</[A-Za-z][\w.]*\s*>|<[A-Za-z][\w.]*(?:\s[^<>]*)?/>")


def _to_hsl_triplet(value: str) -> str | None:
    """'#5D4037', 'rgb(93, 64, 55)', 'hsl(15 26% 29%)' or '15 26% 29%' -> '15 26% 29%'."""
    value = value.strip().split("/*")[0].strip()
    if re.fullmatch(r"\d+(\.\d+)?\s+\d+(\.\d+)?%\s+\d+(\.\d+)?%", value):
        return value
    if m := re.fullmatch(r"hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%.*\)", value):
        return f"{m.group(1)} {m.group(2)}% {m.group(3)}%"
    if m := re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value):
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    elif m := re.fullmatch(r"rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+).*\)", value):
        rgb = [int(m.group(i)) for i in (1, 2, 3)]
    else:
        return None
    r, g, b = (c / 255 for c in rgb)
    hi, lo = max(r, g, b), min(r, g, b)
    light = (hi + lo) / 2
    if hi == lo:
        hue = sat = 0.0
    else:
        d = hi - lo
        sat = d / (1 - abs(2 * light - 1))
        hue = {r: ((g - b) / d) % 6, g: (b - r) / d + 2, b: (r - g) / d + 4}[hi] * 60
    return f"{round(hue)} {round(sat * 100)}% {round(light * 100)}%"


def normalize_tokens(css: str) -> tuple[str, list[str]]:
    """Rewrite color tokens into the form tailwind.config.ts reads (`--primary: H S% L%`),
    accepting `--color-*` names and hex/rgb/hsl values, and add defaults for missing tokens."""
    notes: list[str] = []
    found: dict[str, str] = {}  # First (light theme) value of each token.

    def rewrite(match: re.Match) -> str:
        name, value = match.group(1), match.group(2)
        if name not in COLOR_TOKENS:
            return match.group(0)
        triplet = _to_hsl_triplet(value)
        if triplet is None:
            return match.group(0)
        found.setdefault(name, triplet)
        new = f"--{name}: {triplet};"
        if new != match.group(0):
            notes.append(f"{match.group(0).strip()} -> {new}")
        return new

    css = _TOKEN_DECL.sub(rewrite, css)
    # Token values are now bare HSL triplets, so plain var() uses must be wrapped in hsl().
    token_names = "|".join(sorted(COLOR_TOKENS, key=len, reverse=True))
    css, uses = re.subn(rf"(?<!hsl\()var\(--(?:color-)?({token_names})\)", r"hsl(var(--\1))", css)
    if uses:
        notes.append(f"wrapped {uses} var(--token) uses in hsl()")
    missing = [t for t in COLOR_TOKENS if t not in found]
    if missing:
        # Derive missing tokens from the page's own palette where a sibling token exists.
        related = {"ring": "primary", "secondary": "muted", "secondary-foreground": "muted-foreground",
                   "border": "muted", "input": "muted", "card-foreground": "foreground",
                   "popover-foreground": "foreground", "card": "background", "popover": "background"}
        def value(token: str) -> str:
            source = related.get(token)
            return found.get(source) or DEFAULT_TOKENS[token]
        defaults = "\n".join(f"    --{t}: {value(t)};" for t in missing)
        block = f"@layer base {{\n  :root {{\n{defaults}\n  }}\n}}\n"
        # Defaults go first so the page's own :root/.dark rules still override them.
        anchor = css.rfind("@tailwind utilities;")
        at = css.find("\n", anchor) + 1 if anchor >= 0 else 0
        css = css[:at] + block + css[at:]
        notes.append(f"added default tokens: {', '.join(missing)}")
    return css, notes


def jsx_in_ts(path: str, content: str) -> bool:
    return path.endswith(".ts") and bool(_JSX.search(content))


def render_files(files: dict[str, str]) -> str:
    """Files as fenced blocks with path comments (the page's single-document form)."""
    blocks = []
    for path in sorted(files):
        lang = path.rsplit(".", 1)[-1]
        comment = f"/* {path} */" if lang == "css" else f"// {path}"
        blocks.append(f"```{lang}\n{comment}\n{files[path].rstrip()}\n```")
    return "\n\n".join(blocks)
