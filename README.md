# feedback-scout

A local, prompt-scoped agent that gathers public customer feedback about any
company or product, sorts it by theme, and writes a cited evidence report.

You describe what you want to learn ("what do data engineers say about
Snowflake query cost and data quality?"), optionally list options to compare,
and feedback-scout:

1. **Plans** search queries in the language customers actually use (Claude).
2. **Collects** feedback from every source you've configured (see below).
3. **Labels** each item: relevant or not, which theme, the pain in one line,
   severity, and whether it's about the company itself or the category (Claude).
4. **Writes** a Markdown report where every claim cites its source, plus a CSV
   of the evidence for your own analysis.

Everything runs on your machine with your own API keys. Nothing is sent
anywhere except the APIs listed below.

## Sources

| Source | Access | Key needed | Notes |
| --- | --- | --- | --- |
| Hacker News | [Official Algolia search API](https://hn.algolia.com/api) | No | Developer-heavy audience. |
| Reddit | [Official Data API](https://www.reddit.com/dev/api) | Yes: your own Reddit app | Free tier is for personal, non-commercial use; Reddit reviews API access requests; the terms forbid using the data to train AI models. feedback-scout only reads and summarises. |
| Stack Overflow | [Official Stack Exchange API](https://api.stackexchange.com/docs) | Optional | **Off by default.** Stack Exchange's terms require express prior written consent for automated collection used in generative-AI work. Enable it only if your use is permitted. |
| GitHub issues | [Official REST API](https://docs.github.com/en/rest/search/search) | Optional token | Searches the company's public repos/orgs only. |
| Discourse forums | Public `search.json` on any Discourse forum | No | Many vendor communities run Discourse. Pass the forum URL with `--discourse`. |
| General web | [Claude API web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool) | Your Anthropic key | Blogs, write-ups, public pages. Billed by Anthropic per search. Only URLs actually returned by a search are kept. |
| G2, Capterra, Gartner Peer Insights, TrustRadius, PeerSpot | **Your imports** | n/a | These sites have no public API for readers and their terms restrict automated collection, so feedback-scout does not scrape them. Copy or export reviews you read into `imports/` (format below) and they're analysed with everything else. |

Run `feedback-scout sources` to see which are configured.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/abhilashaagarwala/feedback-agent.git
cd feedback-agent
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env    # then add your keys
feedback-scout sources
```

### Keys

Only `ANTHROPIC_API_KEY` is required. Everything else turns on more sources.

| Variable | Where to get it |
| --- | --- |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | Create a "script" app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps). Follow Reddit's Developer Terms and Data API Terms. |
| `GITHUB_TOKEN` | A fine-grained token with no extra permissions (public repos only) raises the search limit. |
| `STACKEXCHANGE_KEY` | [stackapps.com](https://stackapps.com/apps/oauth/register). Read the terms first (see above). |
| `FEEDBACK_SCOUT_MODEL` | Optional model ID; default `claude-sonnet-5-5`. |

## Use

### Explore an open question

```bash
feedback-scout run \
  --company "Snowflake" \
  --scope "What frustrates data engineers about Snowflake costs and performance?" \
  --audience "data engineers and analytics engineers"
```

### Compare options (e.g. ideas for a prototype)

```bash
feedback-scout run \
  --company "Snowflake" \
  --scope "Customer pain behind three AI agent ideas for Snowflake users" \
  --option "Data quality monitoring and issue resolution" \
  --option "Understanding, optimizing and documenting SQL queries" \
  --option "Getting decisions and action items out of recorded meetings" \
  --context-file brief.pdf \
  --subreddit snowflake --subreddit dataengineering \
  --github-org snowflakedb \
  --rank
```

`--rank` adds a comparison table and a ranking. Without it, the report just
presents the evidence per theme.

### Review the plan before spending on collection

```bash
feedback-scout plan --company "Snowflake" --scope "..." --out plan.json
# edit plan.json: queries, subreddits, repos
feedback-scout run --company "Snowflake" --scope "..." --plan-file plan.json
```

### Useful flags

| Flag | Default | What it does |
| --- | --- | --- |
| `--sources` | all except `stackoverflow` | Comma-separated list: `hackernews,reddit,stackoverflow,github,discourse,web,imports` |
| `--since` | 3 years ago | Only feedback on or after this date |
| `--per-query` | 25 | Results per query per source |
| `--max-items` | 400 | Cap on items sent to Claude for labelling (cost control) |
| `--web-searches` | 5 | Web searches per theme |
| `--imports-dir` | `imports` | Folder of reviews you exported or copied |
| `--context-file` | none | PDF or text with background, used for planning |

Rewrite a report from a saved run (e.g. with `--rank`) without collecting again:

```bash
feedback-scout report runs/20261126-101500-snowflake --rank
```

## Output

Each run writes a folder under `runs/`:

| File | Contents |
| --- | --- |
| `report.md` | The cited report, with a coverage table showing what each source returned |
| `evidence.csv` | Every relevant item: theme, source, date, severity, one-line pain, URL |
| `plan.json` | The themes and queries used (reusable with `--plan-file`) |
| `items.jsonl`, `labels.jsonl`, `coverage.json` | Raw collected items and labels |

## Imports format (G2, Gartner, TrustRadius, PeerSpot, Capterra…)

Put files in `imports/`. The part of the file name before the first `_` or `-`
becomes the source label: `g2_snowflake.csv` shows up as `g2`.

**CSV / JSON / JSONL**: one review per row/object. Recognised columns:
`text` (or `review`, `body`, `content`, `comment`), `likes`, `dislikes`,
`pros`, `cons`, `title`, `url`, `date`, `author`, `rating`.

**Markdown / text**: reviews separated by a line containing only `---`.
Optional header lines at the top of each review:

```text
url: https://www.g2.com/products/snowflake/reviews/...
date: 2026-06-01
title: Great engine, opaque costs
Data Engineer, enterprise. Love the performance but we can't see cost per query...
---
next review...
```

See `examples/imports/` for samples.

## Cost

Cost is driven by labelling (about one Claude call per 20 items) and web
searches. The defaults cap labelling at 400 items. Use `feedback-scout plan`
and a smaller `--max-items` or `--per-query` for a cheap first pass.

## Responsible use

- Use official APIs and follow each platform's terms. Don't add scrapers for
  sites that prohibit them.
- Reports paraphrase; keep quotes short and link to the original.
- Public posts show the direction of feedback, not how common it is.
- Don't use collected data to train models; Reddit and Stack Exchange terms
  restrict that.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Add a source by subclassing `feedback_scout.sources.base.Source`, implementing
`search()` (or `collect()` for non-query sources), and registering it in
`feedback_scout/sources/__init__.py`.

## License

MIT
