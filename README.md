# Harsh Kumar

I build the tools I actually use.

**See it:** https://harsh-0024.github.io/

This repository builds that site. Every night a GitHub Action lists my public
repositories, reads their full history, takes screenshots of the live apps, and
publishes a home page plus one page per project. A new public repo shows up on
its own the next morning.

## Changing what's shown

Edit [`portfolio.toml`](portfolio.toml) and push. The site rebuilds in a couple of minutes.

- **Hide a repo:** add its name to `hide`.
- **Feature a repo:** add it to `featured`; the first one gets the large card.
- **Rename or describe it:** add a `[projects.<repo-name>]` section with `name`, `tagline`, `live` or `stack`.

To rebuild right away without changing anything, open **Actions** → **Build Portfolio** → **Run workflow**.

## What's in here

- `templates/home.html` is the home page; `templates/project.html` is the page for each project.
- `build/build_site.py` reads GitHub and the repositories and fills in the templates.
- `build/screenshots.py` takes the screenshots of live apps.
- `.github/workflows/build.yml` runs both every night and publishes the result.

## Building it on your own machine

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 build/build_site.py _site
python3 build/screenshots.py _site
python3 -m http.server -d _site 8000
```

Then open http://localhost:8000.
