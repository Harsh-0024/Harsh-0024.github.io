#!/usr/bin/env python3
"""Build the portfolio site from every public repository on GitHub.

    python3 build/build_site.py OUTPUT_DIR [CLONES_DIR]

It lists the owner's public repositories, clones each one with its full
history, and writes the home page plus one page per project into OUTPUT_DIR.
New repositories appear on their own; portfolio.toml can hide, feature,
rename or describe them. Set GITHUB_TOKEN to avoid GitHub's low anonymous
rate limit (the Actions runner provides one).
"""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request

import markdown

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
CONFIG = tomllib.loads((ROOT / "portfolio.toml").read_text(encoding="utf-8"))
OWNER = CONFIG["profile"]["github"]
SITE = f"https://{OWNER.lower()}.github.io"
MY_NAMES = set(CONFIG["site"]["my_names"])
HIDE = set(CONFIG["site"].get("hide", [])) | {f"{OWNER}.github.io"}
FEATURED = CONFIG["site"].get("featured", [])
PROJECTS = CONFIG.get("projects", {})

DESCRIPTION = (
    f"{CONFIG['profile']['name']} builds tools for training, focus and time. Every project, "
    "commit and line of code from GitHub, rebuilt every night."
)
# The tab icon: a gold ring around a gold dot, drawn inline so no image file is needed.
FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='8' fill='%23111316'/%3E"
    "%3Ccircle cx='16' cy='16' r='9' fill='none' stroke='%23E2B74D' stroke-width='2.5'/%3E"
    "%3Ccircle cx='16' cy='16' r='4.5' fill='%23E2B74D'/%3E%3C/svg%3E"
)


# ---------- GitHub and git ----------

def api(path: str):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"{OWNER}-portfolio"},
    )
    if os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def git(repo_dir: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo_dir), *args], text=True)


def clone(name: str, clones: Path) -> Path:
    """Clone with full history and every branch, or refresh an earlier clone."""
    dest = clones / name
    if dest.exists():
        git(dest, "fetch", "--quiet", "--prune", "origin")
    else:
        subprocess.check_call(["git", "clone", "--quiet", f"https://github.com/{OWNER}/{name}.git", str(dest)])
    return dest


def is_up(url: str) -> bool:
    """True if the URL answers with a page. Sleeping free-tier servers get 25 seconds to wake."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": f"{OWNER}-portfolio"})
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status < 400
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


# ---------- Reading one repository ----------

def read_commits(repo_dir: Path, only_mine: bool) -> list[dict]:
    """Every commit on every branch on GitHub, newest first.

    \x1e separates commits and \x1f separates fields, so messages can contain
    any normal character. --numstat adds per-file line counts.
    """
    out = git(
        repo_dir, "log", "--remotes=origin", "--date-order", "--numstat",
        "--decorate-refs=refs/remotes/origin/", "--decorate-refs-exclude=refs/remotes/origin/HEAD",
        "--format=\x1e%h\x1f%H\x1f%p\x1f%aI\x1f%an\x1f%s\x1f%D",
    )
    commits = []
    for record in out.split("\x1e")[1:]:
        header, *stat_lines = record.split("\n")
        short_hash, full_hash, parents, date, author, subject, refs = header.split("\x1f")
        if only_mine and author not in MY_NAMES:
            continue
        added = removed = files = 0
        for line in stat_lines:
            parts = line.split("\t")
            if len(parts) == 3:
                files += 1
                if parts[0] != "-":  # binary files show "-" instead of counts
                    added += int(parts[0])
                    removed += int(parts[1])
        commits.append({
            "h": short_hash, "H": full_hash, "p": parents.split(), "d": date, "s": subject,
            "r": [r.strip().removeprefix("origin/") for r in refs.split(",") if r.strip()],
            "ad": added, "de": removed, "f": files,
        })
    # In a fork only my commits are kept, so drop links to commits that were left out.
    kept = {c["h"] for c in commits}
    for c in commits:
        c["p"] = [p for p in c["p"] if p in kept]
    return commits


def read_branches(repo_dir: Path, default: str, only_mine: bool) -> list[dict]:
    lines = git(
        repo_dir, "for-each-ref", "--sort=-committerdate",
        "--format=%(refname)\x1f%(objectname:short)\x1f%(committerdate:iso-strict)",
        "refs/remotes/origin/",
    ).splitlines()
    authors = [f"--author=^{re.escape(n)} <" for n in MY_NAMES] if only_mine else []
    count = lambda rng: int(git(repo_dir, "rev-list", "--count", *authors, rng))
    branches = []
    for line in lines:
        ref, short_hash, date = line.split("\x1f")
        name = ref.removeprefix("refs/remotes/origin/")
        if name == "HEAD":
            continue
        branch = f"origin/{name}"
        branches.append({
            "name": name, "h": short_hash, "d": date,
            "ahead": count(f"origin/{default}..{branch}"),
            "behind": count(f"{branch}..origin/{default}"),
            "total": count(branch),
        })
    return branches


def render_readme(repo_dir: Path, name: str, branch: str, title: str) -> str:
    """The README as HTML, with relative links and images pointed at GitHub."""
    files = [p for p in repo_dir.iterdir() if p.name.lower() in ("readme.md", "readme.markdown")]
    if not files:
        return ""
    html = markdown.markdown(files[0].read_text(encoding="utf-8", errors="replace"),
                             extensions=["fenced_code", "tables", "sane_lists"])
    raw = f"https://raw.githubusercontent.com/{OWNER}/{name}/{branch}/"
    blob = f"https://github.com/{OWNER}/{name}/blob/{branch}/"
    relative = r'(?!https?:|#|mailto:|data:|//)'
    html = re.sub(rf'src="{relative}\.?/?([^"]+)"', lambda m: f'src="{raw}{m.group(1)}"', html)
    html = re.sub(rf'href="{relative}\.?/?([^"]+)"', lambda m: f'href="{blob}{m.group(1)}"', html)
    html = re.sub(r"<(script|iframe|style)\b.*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r'\son\w+="[^"]*"', "", html)
    html = html.replace("<a href=", '<a target="_blank" rel="noopener" href=')
    # The page already shows the project's name, so a README that opens with a
    # one-line title (often just the repo name) loses it.
    html = re.sub(r"^\s*<h1>.*?</h1>\s*", "", html, count=1, flags=re.S)
    # A README that only repeats the GitHub description adds nothing.
    text = re.sub(r"<[^>]+>", "", html).strip()
    return "" if len(text) < 160 else html


def slug_for(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def pretty_name(name: str) -> str:
    return re.sub(r"[-_]+", " ", name).strip().title()


# ---------- Page assembly ----------

def page(template: str, title: str, description: str, data: dict, url: str, image: str | None,
         extra: dict | None = None) -> str:
    # "</" is escaped so a commit message can never close the <script> tag early.
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    body = (TEMPLATES / template).read_text(encoding="utf-8").replace("__DATA__", payload)
    for key, value in (extra or {}).items():
        body = body.replace(key, value)
    esc = lambda s: s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    head = [
        '<!doctype html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f'<title>{esc(title)}</title>',
        f'<meta name="description" content="{esc(description)}">',
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(description)}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:url" content="{url}">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="theme-color" content="#F3F4F1" media="(prefers-color-scheme: light)">',
        '<meta name="theme-color" content="#111316" media="(prefers-color-scheme: dark)">',
        f'<link rel="icon" href="{FAVICON}">',
        f'<link rel="canonical" href="{url}">',
    ]
    if image:
        head.append(f'<meta property="og:image" content="{image}">')
    # Each template carries the rest of its <head> (fonts, styles) and its own </head><body>.
    return "\n".join(head) + "\n" + body + "\n</html>\n"


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    clones = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT / ".clones")
    clones.mkdir(parents=True, exist_ok=True)
    if out.exists():
        shutil.rmtree(out)
    (out / "projects").mkdir(parents=True)

    repos = [r for r in api(f"/users/{OWNER}/repos?per_page=100&type=owner")
             if not r["private"] and r["name"] not in HIDE and not r["archived"] and r["size"] > 0]

    projects = []
    for repo in repos:
        name = repo["name"]
        cfg = PROJECTS.get(name, {})
        default = repo["default_branch"]
        path = clone(name, clones)
        fork = repo["fork"]
        commits = read_commits(path, only_mine=fork)
        if not commits:
            print(f"Skipping {name}: no commits of mine.")
            continue
        parent = api(f"/repos/{OWNER}/{name}").get("parent", {}).get("full_name") if fork else None
        live = cfg.get("live")
        if not live and repo.get("has_pages"):
            live = f"{SITE}/{name}/"
        if live and not is_up(live):
            print(f"{name}: {live} did not answer, so it gets no Live button tonight.")
            live = None
        title = cfg.get("name") or pretty_name(name)
        projects.append({
            "repo": name, "slug": slug_for(name), "name": title,
            "tagline": cfg.get("tagline") or (repo.get("description") or "").strip(),
            "stack": cfg.get("stack", []), "live": live, "fork": fork, "parent": parent,
            "default": default, "langs": api(f"/repos/{OWNER}/{name}/languages"),
            "commits": commits, "branches": read_branches(path, default, only_mine=fork),
            "readme": render_readme(path, name, default, title),
        })
        print(f"Read {name}: {len(commits)} commits.")

    # Every time is shown in my own timezone: the one most commits were made in.
    # Cloud sessions record UTC, and their clock time would otherwise look hours off.
    all_commits = [c for p in projects for c in p["commits"]]
    home_tz = timezone(Counter(datetime.fromisoformat(c["d"]).utcoffset() for c in all_commits).most_common(1)[0][0])
    for p in projects:
        for item in p["commits"] + p["branches"]:
            item["d"] = datetime.fromisoformat(item["d"]).astimezone(home_tz).isoformat()
    now = datetime.now(timezone.utc)
    local_now = now.astimezone(home_tz)
    zone = {"UTC+05:30": "IST"}.get(local_now.tzname(), local_now.tzname())
    stamp = {
        "built": local_now.strftime(f"%-d %b %Y, %H:%M {zone}"), "builtIso": now.isoformat(),
        "today": local_now.date().isoformat(), "zone": zone,
    }

    # Featured first in the order given, then everything else by most recent work.
    rank = {name: i for i, name in enumerate(FEATURED)}
    projects.sort(key=lambda p: (rank.get(p["repo"], len(rank)), -datetime.fromisoformat(p["commits"][0]["d"]).timestamp()))

    shots = []
    summaries = []
    for p in projects:
        shot = f"shots/{p['slug']}.jpg" if p["live"] else None
        if shot:
            shots.append({"slug": p["slug"], "url": p["live"]})
        per_day = Counter(c["d"][:10] for c in p["commits"])
        summary = {
            "slug": p["slug"], "repo": p["repo"], "name": p["name"], "tagline": p["tagline"],
            "stack": p["stack"], "live": p["live"], "fork": p["fork"], "parent": p["parent"],
            "featured": p["repo"] in rank, "shot": shot, "langs": p["langs"],
            "commits": len(p["commits"]), "added": sum(c["ad"] for c in p["commits"]),
            "removed": sum(c["de"] for c in p["commits"]),
            "first": min(per_day), "last": max(per_day), "days": dict(sorted(per_day.items())),
        }
        summaries.append(summary)

        project_data = {
            **stamp, "commits": p["commits"], "branches": p["branches"],
            "latest": p["branches"][0]["name"], "repo": f"{OWNER}/{p['repo']}", "default": p["default"],
            "project": summary, "owner": CONFIG["profile"]["name"],
        }
        url = f"{SITE}/projects/{p['slug']}/"
        description = p["tagline"] or f"{p['name']}, built by {CONFIG['profile']['name']}."
        (out / "projects" / p["slug"]).mkdir(parents=True)
        (out / "projects" / p["slug"] / "index.html").write_text(page(
            "project.html", f"{p['name']} · {CONFIG['profile']['name']}", description, project_data, url,
            f"{SITE}/{shot}" if shot else None, {"__README__": p["readme"]},
        ), encoding="utf-8")

    # A compact list of every commit, so the home page can show what happened on any day.
    feed = sorted(
        ([p["slug"], c["h"], c["H"], c["d"][:16], c["s"]] for p in projects for c in p["commits"]),
        key=lambda row: row[3], reverse=True,
    )
    home_data = {**stamp, "profile": CONFIG["profile"], "projects": summaries, "feed": feed,
                 "owner": OWNER}
    first_shot = next((s["slug"] for s in shots), None)
    (out / "index.html").write_text(page(
        "home.html", f"{CONFIG['profile']['name']} · Projects", DESCRIPTION, home_data, f"{SITE}/",
        f"{SITE}/shots/{first_shot}.jpg" if first_shot else None,
    ), encoding="utf-8")
    (out / "shots").mkdir()
    (out / "shots.json").write_text(json.dumps(shots, indent=2), encoding="utf-8")
    print(f"Wrote {out}: {len(projects)} projects, {len(all_commits)} commits, built {stamp['built']}.")


if __name__ == "__main__":
    main()
