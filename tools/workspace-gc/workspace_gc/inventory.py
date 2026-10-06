"""Live inventory and classification of git checkouts under the roots.

Classes:
  A  removable                - clean, nothing unique, every commit on a
                                network remote, not in use
  B  removable after push     - like A, but commits exist only locally
  C  needs owner              - dirty, stashes, unique ignored data, device
                                backups, keep-listed, unverifiable remote,
                                or not inspectable
  D  keep                     - in use, referenced by an active work item,
                                main checkout, or owns linked worktrees
"""

from __future__ import annotations

import fnmatch
import os
import stat
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from . import git
from .git import GitError
from .signals import Signals

HOME = os.path.expanduser("~")
DEFAULT_ROOTS = [os.path.join(HOME, "workspaces")]
DEFAULT_MAIN_ROOTS = [os.path.join(HOME, "projects")]
# Built in and not removable by configuration: the restricted Echoport
# worktree must never be inspected or removed by this tool.
BUILTIN_KEEP = [os.path.join(HOME, "workspaces", "ws-echoport-retention-race")]
DEFAULT_KEEP_FILE = os.path.join(HOME, ".config", "workspace-gc", "keep")

# Ignored directories whose contents are rebuilt by tooling. They are reported
# with sizes and do not make a checkout "unique".
PAYLOAD_DIRS = frozenset({
    "build", ".build", "DerivedData", ".venv", "venv", "node_modules", "target",
    "dist", ".tox", ".nox",
})
# Further ignored names that hold nothing worth keeping (caches, editor state).
REGENERABLE = PAYLOAD_DIRS | frozenset({
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    "htmlcov", ".coverage", ".DS_Store", ".eggs", ".gradle", ".next", ".nuxt",
    ".parcel-cache", ".turbo", ".swiftpm", ".cache", "_build", ".idea", ".vscode",
    ".pnpm-store", ".sass-cache", "coverage", ".angular", ".svelte-kit",
    # mkdocs/sphinx output, editor state, tool caches, installed Ansible collections
    "site", ".zed", ".ansible", ".uv-cache", "ansible_collections",
})
REGENERABLE_GLOBS = ("*.pyc", "*.pyo", "*.egg-info", ".coverage.*", "*.log", "*.tsbuildinfo")
DISCOVERY_SKIP = PAYLOAD_DIRS | {".git", "__pycache__"}
MAX_DEPTH = 3
CLASS_NAMES = {"A": "removable", "B": "removable after push",
               "C": "needs owner", "D": "keep"}


@dataclass
class Checkout:
    path: str
    root: str
    workspace: str              # top-level directory under the root
    kind: str = "unknown"       # worktree | clone | main
    cls: str = ""
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    keep_listed: bool = False
    common_dir: str = ""
    owner_repo: str = ""        # for worktrees: the repository that owns them
    branch: str = ""
    head: str = ""
    last_commit: str = ""
    dirty: int = 0
    untracked: int = 0
    stashes: int = 0
    linked_worktrees: list[str] = field(default_factory=list)
    network_remotes: list[str] = field(default_factory=list)
    alternates: list[str] = field(default_factory=list)
    remote_errors: list[str] = field(default_factory=list)
    unpushed: int = -1
    hidden: list[str] = field(default_factory=list)          # status/history blind spots
    deletion_blockers: list[str] = field(default_factory=list)
    lending_unknown: list[str] = field(default_factory=list)  # unreadable alternates files
    missing_tips: int = 0        # remote tips whose objects are not available locally
    borrows_from: list[str] = field(default_factory=list)   # objects/info/alternates
    borrowed_by: list[str] = field(default_factory=list)    # repos borrowing our objects
    unpushed_commits: list[str] = field(default_factory=list)
    ignored_unique: list[str] = field(default_factory=list)
    device_backups: list[str] = field(default_factory=list)
    payloads: list[dict] = field(default_factory=list)
    in_use: list[str] = field(default_factory=list)
    work_items: list[dict] = field(default_factory=list)
    size_kb: int = 0
    last_activity: str = ""     # newest of last commit, git-dir files, checkout dir
    idle_hours: float = -1.0
    error: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("alternates", None)
        return d


# ---------------------------------------------------------------- discovery

def _is_under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def load_keep_patterns(keep: list[str], keep_file: str | None) -> list[str]:
    pats = list(BUILTIN_KEEP)
    if keep_file and os.path.isfile(keep_file):
        with open(keep_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    pats.append(line)
    pats.extend(keep)
    out = []
    for p in pats:
        p = os.path.expanduser(p)
        out.append(os.path.normpath(p) if not any(c in p for c in "*?[") else p)
    return out


def keep_match(path: str, patterns: list[str]) -> str:
    candidates = {path, os.path.realpath(path)}
    for pat in patterns:
        for c in candidates:
            if any(ch in pat for ch in "*?["):
                if fnmatch.fnmatch(c, pat) or fnmatch.fnmatch(c, pat.rstrip("/") + "/*"):
                    return pat
            elif _is_under(c, pat) or _is_under(c, os.path.realpath(pat)):
                return pat
    return ""


def discover(roots: list[str], max_depth: int = MAX_DEPTH) -> list[tuple[str, str]]:
    """(checkout, root) pairs. Symlinks are never followed; the root itself is
    never a checkout."""
    found = []
    for root in roots:
        rroot = os.path.realpath(os.path.expanduser(root))
        if not os.path.isdir(rroot):
            continue
        for dirpath, dirnames, filenames in os.walk(rroot, followlinks=False):
            depth = 0 if dirpath == rroot else dirpath[len(rroot) + 1:].count(os.sep) + 1
            if dirpath != rroot and (".git" in dirnames or ".git" in filenames):
                found.append((dirpath, rroot))
                dirnames[:] = []
                continue
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in DISCOVERY_SKIP and depth < max_depth
                and not os.path.islink(os.path.join(dirpath, d))
            )
    return sorted(set(found))


# ---------------------------------------------------------------- alternates

class AlternatesError(Exception):
    pass


def read_alternates(objects_dir: str, keep_patterns: list[str] | None = None,
                    _seen: set[str] | None = None) -> list[str]:
    """Object directories that `objects_dir` borrows from, transitively
    (objects/info/alternates, as written by clone --shared/--reference).
    A missing file means "borrows nothing"; any other read error raises
    AlternatesError, because then nothing can be said."""
    seen = _seen if _seen is not None else set()
    out = []
    path = os.path.join(objects_dir, "info", "alternates")
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return out
    except OSError as exc:
        raise AlternatesError(f"{path}: {exc.strerror or exc}") from exc
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith('"'):
            line = line.strip('"')
        target = line if os.path.isabs(line) else os.path.join(objects_dir, line)
        target = os.path.realpath(target)
        if target in seen:
            continue
        seen.add(target)
        out.append(target)
        # A keep-listed lender is recorded but never read.
        if keep_match(target, keep_patterns or []):
            continue
        try:
            os.stat(target)
        except FileNotFoundError:
            continue  # broken link: nothing further to follow
        except OSError as exc:
            raise AlternatesError(f"{target}: {exc.strerror or exc}") from exc
        out += read_alternates(target, keep_patterns, seen)
    return out


GIT_DIR_INTERNALS = frozenset({"objects", "refs", "logs", "hooks", "info", "lfs",
                               "worktrees"})
STORE_SCAN_DEPTH = 6


def find_object_stores(bases: list[str], keep_patterns: list[str],
                       max_depth: int = STORE_SCAN_DEPTH) -> tuple[list[str], list[str]]:
    """(object directories, scan errors) of every git repository below
    `bases` - bare repositories, .git directories of nested clones, clones
    inside other checkouts - independent of candidate discovery. Symlinks are
    not followed, keep-listed directories are not entered, and dependency
    payload directories (node_modules, .venv, ...) are skipped. A directory
    that cannot be listed is a scan error: a borrower could hide there."""
    stores, errors = [], []

    def onerror(exc: OSError) -> None:
        errors.append(f"cannot list {exc.filename}: {exc.strerror or exc}")

    for base in bases:
        rbase = os.path.realpath(os.path.expanduser(base))
        try:
            st = os.stat(rbase)
        except FileNotFoundError:
            continue  # a root that does not exist hides nothing
        except OSError as exc:
            errors.append(f"cannot access {rbase}: {exc.strerror or exc}")
            continue
        if not stat.S_ISDIR(st.st_mode):
            continue
        if not os.access(rbase, os.R_OK | os.X_OK):
            errors.append(f"cannot list {rbase}")
            continue
        for dirpath, dirnames, filenames in os.walk(rbase, followlinks=False, onerror=onerror):
            depth = 0 if dirpath == rbase else dirpath[len(rbase) + 1:].count(os.sep) + 1
            is_git_dir = "objects" in dirnames and "HEAD" in filenames
            if is_git_dir:
                stores.append(os.path.join(dirpath, "objects"))
            dirnames[:] = [
                d for d in dirnames
                if depth < max_depth
                and not (is_git_dir and d in GIT_DIR_INTERNALS)
                and d not in PAYLOAD_DIRS
                and not os.path.islink(os.path.join(dirpath, d))
                and not keep_match(os.path.join(dirpath, d), keep_patterns)
            ]
    return sorted(set(stores)), errors


def lender_map(stores: list[str], keep_patterns: list[str] | None = None
               ) -> tuple[dict[str, list[str]], list[str]]:
    """(borrowed objects dir -> borrowing objects dirs, unreadable stores)."""
    lenders: dict[str, list[str]] = {}
    unreadable = []
    for store in stores:
        try:
            targets = read_alternates(store, keep_patterns)
        except AlternatesError as exc:
            unreadable.append(str(exc))
            continue
        for target in targets:
            lenders.setdefault(target, []).append(store)
    return lenders, unreadable


def _repo_of_store(store: str) -> str:
    parent = os.path.dirname(store)
    return os.path.dirname(parent) if os.path.basename(parent) == ".git" else parent


def borrowers_of(repo: str, lenders: dict[str, list[str]]) -> list[str]:
    own = os.path.realpath(os.path.join(repo, ".git", "objects"))
    return sorted({_repo_of_store(b) for b in lenders.get(own, []) if b != own})


def lending_scope(roots: list[str], main_roots: list[str], keep_patterns: list[str]
                  ) -> tuple[dict[str, list[str]], list[str]]:
    stores, errors = find_object_stores(list(roots) + list(main_roots), keep_patterns)
    lenders, unreadable = lender_map(stores, keep_patterns)
    return lenders, errors + unreadable


# ---------------------------------------------------------------- inspection

class Inspector:
    """Per-run caches for remote lookups and repository metadata."""

    def __init__(self, main_roots: list[str] | None = None, use_cache: bool = True,
                 keep_patterns: list[str] | None = None):
        self.main_roots = [os.path.realpath(os.path.expanduser(r)) for r in (main_roots or [])]
        self.keep_patterns = list(keep_patterns or [])
        self.use_cache = use_cache
        self._lock = threading.Lock()
        self._ls: dict[str, tuple[set[str] | None, str]] = {}
        self._root_index: dict[str, list[str]] | None = None

    # -- remotes

    def ls_remote(self, url: str) -> tuple[set[str] | None, str]:
        with self._lock:
            if self.use_cache and url in self._ls:
                return self._ls[url]
        try:
            res: tuple[set[str] | None, str] = (git.ls_remote(url), "")
        except GitError as exc:
            res = (None, str(exc))
        with self._lock:
            self._ls[url] = res
        return res

    @staticmethod
    def common_dir(repo: str) -> str:
        return git.out(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo).strip()

    def resolve_remotes(self, repo: str, seen: set[str] | None = None, depth: int = 0
                        ) -> tuple[list[str], list[str], int]:
        """Network URLs reachable from repo's remotes, following local-path
        remotes (another checkout used as origin). Returns (urls, alternate
        object dirs of the local repos on the chain, number of remotes)."""
        seen = seen if seen is not None else set()
        real = os.path.realpath(repo)
        if real in seen or depth > 6:
            return [], [], 0
        seen.add(real)
        try:
            cfg = git.out(["config", "--get-regexp", r"^remote\..*\.url$"], repo, check=False)
        except GitError:
            return [], [], 0
        urls, alternates, count = [], [], 0
        for line in cfg.splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            count += 1
            url = parts[1]
            if git.is_network_url(url):
                urls.append(url)
                continue
            local = git.local_url_path(url, repo)
            if not os.path.exists(local) or keep_match(local, self.keep_patterns):
                continue  # keep-listed repositories are never inspected
            try:
                cdir = self.common_dir(local)
            except GitError:
                continue
            alternates.append(os.path.join(cdir, "objects"))
            u2, a2, _ = self.resolve_remotes(local, seen, depth + 1)
            urls += u2
            alternates += a2
        return list(dict.fromkeys(urls)), list(dict.fromkeys(alternates)), count

    def root_index(self, extra_repos: list[str]) -> dict[str, list[str]]:
        """root commit -> repos, over main-root checkouts and discovered ones;
        used only for repositories that have no remote at all."""
        with self._lock:
            if self._root_index is not None:
                return self._root_index
        repos = list(extra_repos)
        for mr, _ in discover(self.main_roots, max_depth=2):
            repos.append(mr)
        index: dict[str, list[str]] = {}
        for r in dict.fromkeys(repos):
            if keep_match(r, self.keep_patterns):
                continue
            try:
                roots = git.out(["rev-list", "--max-parents=0", "HEAD"], r).split()
            except GitError:
                continue
            for c in roots:
                index.setdefault(c, []).append(r)
        with self._lock:
            self._root_index = index
        return index

    def sibling_objects(self, repo: str, extra_repos: list[str]) -> list[str]:
        """Object dirs of other local repositories sharing a root commit."""
        try:
            roots = git.out(["rev-list", "--max-parents=0", "HEAD"], repo).split()
        except GitError:
            return []
        index = self.root_index(extra_repos)
        me = os.path.realpath(repo)
        out = []
        for rc in roots:
            for other in index.get(rc, []):
                if os.path.realpath(other) == me:
                    continue
                try:
                    out.append(os.path.join(self.common_dir(other), "objects"))
                except GitError:
                    pass
        return list(dict.fromkeys(out))

    # -- containment

    def unpushed(self, repo: str, revs: list[str], urls: list[str], alternates: list[str]
                 ) -> tuple[int, list[str], list[str], int]:
        """(count, sample commits, remote errors, missing tips) for commits
        reachable from revs that are not reachable from any branch or tag of
        any reachable network URL. Only remote tips whose objects exist
        locally (including alternates) can be used; `missing tips` counts the
        others, so a non-zero count with missing tips means "unknown", not
        "unpushed". Any git failure raises GitError - never a number."""
        tips: set[str] = set()
        errors = []
        for url in urls:
            shas, err = self.ls_remote(url)
            if shas is None:
                errors.append(f"{url}: {err}")
            else:
                tips |= shas
        present = []
        missing = 0
        if tips:
            check = git.run(["cat-file", "--batch-check=%(objectname) %(objecttype)"], repo,
                            input="\n".join(sorted(tips)) + "\n", alternates=alternates)
            for line in check.stdout.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] in ("commit", "tag"):
                    present.append(parts[0])
                elif len(parts) == 2 and parts[1] == "missing":
                    missing += 1
        stdin = "".join(f"^{s}\n" for s in present)
        raw = git.out(["rev-list", "--count", "--stdin", *revs], repo,
                      input=stdin, alternates=alternates).strip()
        if not raw.isdigit():
            raise GitError(f"rev-list --count gave no number: {raw[:60]!r}")
        count = int(raw)
        sample = []
        if count:
            sample = git.out(["log", "--stdin", "--format=%h %cs %s", "-n", "8", *revs], repo,
                             input=stdin, alternates=alternates).splitlines()
        return count, sample, errors, missing


def _workspace_of(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)
    return os.path.join(root, rel.split(os.sep)[0])


def _regenerable(rel: str, extra: list[str]) -> bool:
    parts = [p for p in rel.rstrip("/").split("/") if p]
    for p in parts:
        if p in REGENERABLE or p in extra:
            return True
        if any(fnmatch.fnmatch(p, g) for g in REGENERABLE_GLOBS):
            return True
    return False


def _du_kb(path: str) -> int:
    try:
        proc = subprocess.run(["du", "-sk", path], capture_output=True, text=True, timeout=600)
        return int(proc.stdout.split()[0]) if proc.stdout else 0
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return 0


def _newest_mtime(path: str, gdir: str) -> float:
    """Newest mtime of the checkout directory and the files directly in its
    git dir (index, HEAD, ORIG_HEAD, FETCH_HEAD, ...) plus logs/HEAD."""
    newest = 0.0
    candidates = [path, os.path.join(gdir, "logs", "HEAD")]
    try:
        candidates += [e.path for e in os.scandir(gdir) if e.is_file(follow_symlinks=False)]
    except OSError:
        pass
    for c in candidates:
        try:
            newest = max(newest, os.lstat(c).st_mtime)
        except OSError:
            pass
    return newest


def find_device_backups(path: str) -> list[str]:
    """Quick check used for every checkout (bounded depth). Removal
    candidates additionally get the exhaustive deletion_scan()."""
    found = []
    backups = os.path.join(path, ".cache", "device-db-backups")
    try:
        if os.path.isdir(backups) and not os.path.islink(backups) and os.listdir(backups):
            found.append(os.path.relpath(backups, path))
    except OSError:
        found.append(os.path.relpath(backups, path) + " (unreadable)")
    for dirpath, dirnames, _ in os.walk(path, followlinks=False):
        depth = dirpath[len(path):].count(os.sep)
        for d in list(dirnames):
            if d.startswith("device-preservation-"):
                found.append(os.path.relpath(os.path.join(dirpath, d), path))
        dirnames[:] = [d for d in dirnames
                       if d not in DISCOVERY_SKIP and not d.startswith("device-")
                       and d != "device-db-backups" and depth < 3]
    return sorted(set(found))


def deletion_scan(path: str) -> list[str]:
    """Exhaustive walk of everything a removal would delete (symlinks not
    followed). Returns blockers: directories that are not readable, writable
    and searchable (so a delete could stop half-way), traversal errors, and
    device backups anywhere in the tree, including payload directories.
    An empty list is required before any removal."""
    blockers = []
    parent = os.path.dirname(path)
    if not os.access(parent, os.W_OK | os.X_OK):
        blockers.append(f"parent not writable: {parent}")

    def onerror(exc: OSError) -> None:
        blockers.append(f"cannot read {exc.filename}: {exc.strerror or exc}")

    for dirpath, dirnames, _ in os.walk(path, followlinks=False, onerror=onerror):
        if not os.access(dirpath, os.R_OK | os.W_OK | os.X_OK):
            blockers.append(f"not writable: {dirpath}")
        rel = os.path.relpath(dirpath, path)
        if rel.replace(os.sep, "/").endswith(".cache/device-db-backups") or \
                os.path.basename(dirpath).startswith("device-preservation-"):
            blockers.append(f"device backup: {rel}")
            dirnames[:] = []
        if len(blockers) >= 10:
            break
    return blockers


def scan_ignored(path: str, regenerable: list[str]) -> tuple[list[dict], list[str]]:
    """(payload dirs, ignored entries that are not regenerable)."""
    payloads, unique = [], []
    ignored = git.out(["ls-files", "-o", "-i", "--exclude-standard", "--directory"], path)
    for rel in ignored.splitlines():
        if not rel:
            continue
        name = os.path.basename(rel.rstrip("/"))
        if name in PAYLOAD_DIRS and rel.endswith("/"):
            payloads.append({"path": rel.rstrip("/"), "kb": 0})
        elif not _regenerable(rel, regenerable):
            unique.append(rel)
    return payloads, unique


def hidden_state(path: str, gdir: str, common_dir: str) -> list[str]:
    """Things that can hide changes or history from `git status` and
    `rev-list`, or keep data outside what the checks look at: index entries
    flagged assume-unchanged or skip-worktree, submodules, grafts, an
    unexpected .git/modules store."""
    reasons = []
    flagged = 0
    for line in git.out(["ls-files", "-v"], path).splitlines():
        tag = line[:1]
        if tag.islower() or tag == "S":
            flagged += 1
    if flagged:
        reasons.append(f"{flagged} index entr{'y' if flagged == 1 else 'ies'} flagged "
                       "assume-unchanged/skip-worktree (status may hide changes)")
    gitlinks = sum(1 for ln in git.out(["ls-files", "-s"], path).splitlines()
                   if ln.startswith("160000 "))
    if gitlinks or os.path.exists(os.path.join(path, ".gitmodules")) \
            or os.path.isdir(os.path.join(gdir, "modules")) \
            or os.path.isdir(os.path.join(common_dir, "modules")):
        reasons.append("has submodules (their repositories are not checked)")
    if os.path.exists(os.path.join(common_dir, "info", "grafts")):
        reasons.append("grafts file present (history may be rewritten)")
    return reasons


def inspect(co: Checkout, ins: Inspector, *, keep_patterns: list[str], regenerable: list[str],
            sizes: bool = True, all_repos: list[str] | None = None) -> Checkout:
    path = co.path
    pat = keep_match(path, keep_patterns)
    if pat:
        # Not inspected at all: no git command, no du.
        co.keep_listed = True
        co.notes.append(f"keep-list ({pat}); not inspected")
        return co
    if any(_is_under(path, mr) for mr in ins.main_roots):
        co.kind = "main"
    dotgit = os.path.join(path, ".git")
    if os.path.islink(dotgit) or os.path.islink(path):
        co.error = "symlinked checkout or .git"
        return co
    try:
        gdir = git.out(["rev-parse", "--path-format=absolute", "--git-dir"], path).strip()
        co.common_dir = ins.common_dir(path)
        top = os.path.realpath(git.out(["rev-parse", "--show-toplevel"], path).strip())
        if top != os.path.realpath(path):
            co.error = f"git toplevel is {top}"
            return co
        if co.kind != "main":
            if os.path.isfile(dotgit):
                if os.path.realpath(gdir) == os.path.realpath(co.common_dir):
                    co.error = ".git file but not a linked worktree (submodule?)"
                    return co
                co.kind = "worktree"
                co.owner_repo = os.path.dirname(co.common_dir) \
                    if os.path.basename(co.common_dir) == ".git" else co.common_dir
            else:
                co.kind = "clone"
        head = git.run(["rev-parse", "--verify", "-q", "HEAD"], path, check=False)
        if head.returncode != 0:
            co.error = "no commits (unborn HEAD)"
            return co
        co.head = head.stdout.strip()
        br = git.run(["symbolic-ref", "-q", "--short", "HEAD"], path, check=False)
        co.branch = br.stdout.strip() if br.returncode == 0 else "(detached)"
        co.last_commit = git.out(["log", "-1", "--format=%cs", "HEAD"], path).strip()
        commit_ts = int(git.out(["log", "-1", "--format=%ct", "HEAD"], path).strip() or 0)
        newest = max(commit_ts, _newest_mtime(path, gdir))
        co.idle_hours = round(max(0.0, time.time() - newest) / 3600, 1)
        co.last_activity = time.strftime("%Y-%m-%d %H:%M", time.localtime(newest))

        status = git.out(["status", "--porcelain=v1", "-uall", "--ignore-submodules=none"], path)
        lines = [ln for ln in status.splitlines() if ln]
        co.untracked = sum(1 for ln in lines if ln.startswith("??"))
        co.dirty = len(lines) - co.untracked

        if co.kind == "clone":
            co.stashes = len(git.out(["stash", "list"], path).splitlines())
            wl = git.out(["worktree", "list", "--porcelain"], path)
            me = os.path.realpath(path)
            for block in wl.split("\n\n"):
                fields = dict((ln.split(" ", 1) + [""])[:2] for ln in block.splitlines() if ln)
                wt = fields.get("worktree")
                if wt and os.path.realpath(wt) != me and "prunable" not in fields:
                    co.linked_worktrees.append(wt)

        co.payloads, co.ignored_unique = scan_ignored(path, regenerable)
        co.hidden = hidden_state(path, gdir, co.common_dir)
        co.device_backups = find_device_backups(path)

        urls, alternates, nremotes = ins.resolve_remotes(path)
        if not urls and nremotes == 0 and all_repos is not None:
            roots = git.out(["rev-list", "--max-parents=0", "HEAD"], path).split()
            index = ins.root_index(all_repos)
            for rc in roots:
                for other in index.get(rc, []):
                    if os.path.realpath(other) == os.path.realpath(path):
                        continue
                    u2, a2, _ = ins.resolve_remotes(other)
                    if u2:
                        try:
                            alternates.append(os.path.join(ins.common_dir(other), "objects"))
                        except GitError:
                            pass
                        urls += u2
                        alternates += a2
            if urls:
                co.notes.append("no remote configured; network remote found via a repository "
                                "with the same root commit")
            urls = list(dict.fromkeys(urls))
            alternates = list(dict.fromkeys(alternates))
        co.network_remotes = urls
        co.alternates = alternates
        if urls:
            revs = ["HEAD"] if co.kind == "worktree" else ["HEAD", "--branches", "--tags"]
            co.unpushed, co.unpushed_commits, co.remote_errors, co.missing_tips = ins.unpushed(
                path, revs, urls, alternates)
            if co.unpushed and co.missing_tips and all_repos is not None:
                # Remote tips we lack may live in another local repository of the
                # same project (read-only, via alternates).
                extra = ins.sibling_objects(path, all_repos)
                if extra:
                    alternates = list(dict.fromkeys(alternates + extra))
                    co.alternates = alternates
                    (co.unpushed, co.unpushed_commits, co.remote_errors,
                     co.missing_tips) = ins.unpushed(path, revs, urls, alternates)
    except GitError as exc:
        co.error = str(exc)
        return co
    if sizes:
        co.size_kb = _du_kb(path)
        for p in co.payloads:
            p["kb"] = _du_kb(os.path.join(path, p["path"]))
    return co


# ---------------------------------------------------------------- classify

def apply_signals(co: Checkout, sig: Signals) -> None:
    ws = co.workspace
    for cwd in sig.herdr_cwds:
        if _is_under(cwd, ws):
            co.in_use.append(f"herdr pane in {cwd}")
    for cwd in sig.process_cwds:
        if _is_under(cwd, ws):
            co.in_use.append(f"process cwd {cwd}")
    co.in_use = sorted(set(co.in_use))
    for ref in sig.work_refs:
        if _is_under(co.path, ref.worktree) or _is_under(ref.worktree, co.path):
            co.work_items.append({"slug": ref.slug, "stage": ref.stage, "active": ref.active})


def classify(co: Checkout, min_idle_hours: float = 0) -> None:
    r = co.reasons
    if co.keep_listed:
        co.cls = "C"
        r.append("keep-listed")
        return
    if co.kind == "main":
        co.cls = "D"
        r.append("main checkout")
        return
    if co.error:
        co.cls = "C"
        r.append(f"not inspectable: {co.error}")
        return
    d_reasons = []
    if co.in_use:
        d_reasons.append("in use (" + "; ".join(co.in_use[:3]) + ")")
    active = [w["slug"] for w in co.work_items if w["active"]]
    if active:
        d_reasons.append("active work item: " + ", ".join(active))
    if min_idle_hours > 0 and 0 <= co.idle_hours < min_idle_hours:
        d_reasons.append(f"recently active ({co.last_activity}, idle {co.idle_hours:g}h "
                         f"< {min_idle_hours:g}h)")
    if co.borrowed_by:
        d_reasons.append("objects borrowed (alternates) by " + ", ".join(co.borrowed_by[:3]))
    if co.linked_worktrees:
        d_reasons.append(f"owns {len(co.linked_worktrees)} linked worktree(s)")
    c_reasons = list(co.hidden)
    if co.lending_unknown and co.kind == "clone":
        c_reasons.append("cannot tell who borrows its objects: " + "; ".join(co.lending_unknown[:2]))
    if co.dirty or co.untracked:
        c_reasons.append(f"dirty ({co.dirty} changed, {co.untracked} untracked)")
    if co.stashes:
        c_reasons.append(f"{co.stashes} stash(es)")
    if co.device_backups:
        c_reasons.append("device backups: " + ", ".join(co.device_backups))
    if co.ignored_unique:
        shown = ", ".join(co.ignored_unique[:5])
        more = f" (+{len(co.ignored_unique) - 5} more)" if len(co.ignored_unique) > 5 else ""
        c_reasons.append(f"ignored files that are not regenerable: {shown}{more}")
    if not co.network_remotes:
        c_reasons.append("no network remote found")
    elif co.unpushed < 0 or (co.remote_errors and len(co.remote_errors) == len(co.network_remotes)):
        c_reasons.append("network remote unreachable: " + "; ".join(co.remote_errors[:2]))
    elif co.unpushed > 0 and co.missing_tips:
        c_reasons.append(f"containment unknown: {co.unpushed} commit(s) not reachable from the "
                         f"remote tips present locally, and {co.missing_tips} remote tip(s) are "
                         "missing locally")
    elif co.unpushed > 0 and co.remote_errors:
        c_reasons.append(f"{co.unpushed} commit(s) not found on reachable remotes and "
                         "another remote could not be checked")
    if d_reasons:
        co.cls = "D"
        r.extend(d_reasons + c_reasons)
    elif c_reasons:
        co.cls = "C"
        r.extend(c_reasons)
    elif co.unpushed > 0:
        co.cls = "B"
        r.append(f"{co.unpushed} commit(s) on no network branch or tag")
    else:
        co.cls = "A"
        r.append("clean and fully on " + ", ".join(co.network_remotes))
    for w in co.work_items:
        if not w["active"]:
            co.notes.append(f"referenced by closed work item {w['slug']} ({w['stage']})")


# ---------------------------------------------------------------- run

@dataclass
class Inventory:
    roots: list[str]
    checkouts: list[Checkout]
    signals: Signals
    prune: dict[str, list[str]] = field(default_factory=dict)
    keep_patterns: list[str] = field(default_factory=list)


def build(roots: list[str], sig: Signals, *, main_roots: list[str] | None = None,
          keep: list[str] | None = None, keep_file: str | None = DEFAULT_KEEP_FILE,
          regenerable: list[str] | None = None, sizes: bool = True, jobs: int = 8,
          only: str | None = None, use_cache: bool = True,
          min_idle_hours: float = 0) -> Inventory:
    rroots = [os.path.realpath(os.path.expanduser(r)) for r in roots]
    patterns = load_keep_patterns(keep or [], keep_file)
    ins = Inspector(main_roots if main_roots is not None else DEFAULT_MAIN_ROOTS, use_cache,
                    keep_patterns=patterns)
    pairs = discover(rroots)
    if only is not None:
        pairs = [(p, r) for p, r in pairs if p == only]
    all_repos = [p for p, _ in discover(rroots) if not keep_match(p, patterns)]
    cos = [Checkout(path=p, root=r, workspace=_workspace_of(p, r)) for p, r in pairs]
    lenders, unreadable = lending_scope(rroots, ins.main_roots, patterns)

    def work(co: Checkout) -> Checkout:
        inspect(co, ins, keep_patterns=patterns, regenerable=regenerable or [],
                sizes=sizes, all_repos=all_repos)
        if not co.keep_listed:
            if co.kind == "clone":
                co.borrowed_by = borrowers_of(co.path, lenders)
                co.lending_unknown = list(unreadable)
            if os.path.isdir(os.path.join(co.path, ".git")):
                try:
                    co.borrows_from = read_alternates(os.path.join(co.path, ".git", "objects"),
                                                      patterns)
                except AlternatesError as exc:
                    co.notes.append(str(exc))
            if co.borrows_from:
                co.notes.append("borrows objects from " + ", ".join(co.borrows_from))
        if co.owner_repo and keep_match(co.owner_repo, patterns):
            co.error = f"owning repository {co.owner_repo} is keep-listed"
        apply_signals(co, sig)
        classify(co, min_idle_hours)
        if co.cls == "A":
            co.deletion_blockers = deletion_scan(co.path)
            if co.deletion_blockers:
                co.cls = "C"
                co.reasons.insert(0, "cannot be deleted safely (read-only or unreadable "
                                  "parts, or device backups): "
                                  + "; ".join(co.deletion_blockers[:3]))
        return co

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        cos = list(pool.map(work, cos))
    # local-origin relations, informational
    by_path = {c.path: c for c in cos}
    for c in cos:
        if c.keep_listed or c.error:
            continue
        cfg = git.run(["config", "--get-regexp", r"^remote\..*\.url$"], c.path, check=False).stdout
        for line in cfg.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and not git.is_network_url(parts[1]):
                target = os.path.realpath(git.local_url_path(parts[1], c.path))
                if target in by_path:
                    by_path[target].notes.append(f"local remote of {c.path}")
    return Inventory(roots=rroots, checkouts=cos, signals=sig, keep_patterns=patterns)


def prune_targets(inv: Inventory) -> list[str]:
    """Repositories whose stale worktree entries may be pruned: owners of the
    worktrees found under the roots, and clones under the roots."""
    repos = set()
    for c in inv.checkouts:
        if c.keep_listed or c.error:
            continue
        if c.kind == "worktree" and c.owner_repo:
            repos.add(c.owner_repo)
        elif c.kind == "clone":
            repos.add(c.path)
    return sorted(r for r in repos
                  if os.path.isdir(r) and not keep_match(r, inv.keep_patterns))


def prune_preview(repo: str) -> list[str]:
    proc = git.run(["worktree", "prune", "-n", "-v"], repo, check=False)
    return [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]
