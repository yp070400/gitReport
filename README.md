# AI Engineering Impact Analyzer

Analyze developer contributions across GitHub and Bitbucket repositories using Google Vertex AI Gemini. The tool fetches commits, classifies them heuristically, and uses Gemini to generate natural-language impact summaries and scores for every contributor.

---

## Prerequisites

| Requirement | Minimum Version | Notes |
|-------------|----------------|-------|
| Python | 3.10+ | Uses `match`-free dataclasses and `|` union syntax |
| pip | 23+ | For dependency resolution |
| Google Cloud Project | — | Vertex AI API must be enabled |
| `gcloud` CLI | Latest | For ADC authentication |

---

## Installation

```bash
# 1. Clone or download the project
cd /path/to/gitReport

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows PowerShell

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Authentication Setup

### Google Cloud (Vertex AI)

The tool uses **Application Default Credentials (ADC)**. The simplest setup for local development:

```bash
gcloud auth application-default login
```

Or set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to point to a service account JSON key file that has the **Vertex AI User** role.

### GitHub Token

1. Go to **GitHub → Settings → Developer Settings → Personal Access Tokens → Fine-grained tokens**.
2. Create a token with **Contents: Read** permission on the target repository.
3. Export it:

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

### Bitbucket Token

1. Go to **Bitbucket → Personal settings → App passwords**.
2. Create an App Password with **Repositories: Read** permission.
3. Export it:

```bash
export BITBUCKET_TOKEN=your_app_password
```

### Environment File (Recommended)

Copy `.env.example` to `.env`, fill in the values, and source it before running:

```bash
cp .env.example .env
# Edit .env with your values
source .env         # macOS / Linux
# or use: set -a; source .env; set +a
```

---

## Running the Analyzer

### Analyze a GitHub repository (last 3 months)

```bash
python main.py \
  --source=github \
  --github-repo=octocat/Hello-World \
  --months=3
```

### Analyze a Bitbucket repository (last 6 months)

```bash
python main.py \
  --source=bitbucket \
  --bitbucket-repo=my-workspace/my-service \
  --months=6
```

### Analyze both GitHub and Bitbucket simultaneously

```bash
python main.py \
  --source=both \
  --github-repo=my-org/backend \
  --bitbucket-repo=my-org/frontend \
  --months=3 \
  --output=impact-report.md
```

### Skip AI analysis (heuristic scores only, no GCP required)

```bash
python main.py \
  --source=github \
  --github-repo=my-org/repo \
  --no-ai \
  --output=heuristic-report.md
```

### All available options

```
usage: main.py [-h] --source {github,bitbucket,both}
               [--github-repo OWNER/REPO]
               [--bitbucket-repo WORKSPACE/REPO]
               [--months N]
               [--output FILE]
               [--no-ai]

Options:
  --source          Required. Data source: github, bitbucket, or both.
  --github-repo     GitHub repository in owner/repo format.
  --bitbucket-repo  Bitbucket repository in workspace/repo_slug format.
  --months          Months to look back (default: 3, max: 24).
  --output          Markdown report output path (default: report.md).
  --no-ai           Use heuristic scoring only; skip Vertex AI.
```

---

## Output

Running the tool produces two outputs:

### 1. Console Report

A formatted, color-coded summary printed to stdout:

```
================================================================================
  AI ENGINEERING IMPACT ANALYZER
================================================================================
  Source      : GITHUB
  Repositories: octocat/Hello-World
  Period      : 2025-12-19 → 2026-03-19
  Developers  : 4
================================================================================
  TOP CONTRIBUTOR: Alice  (score 8.7/10)
================================================================================

  #1  Alice  *** HIGH IMPACT ***
      Score : 8.7/10  [★★★ EXCELLENT]
      Commits: 42
      Categories: feature=18, bugfix=12, refactor=8, infra=4

      Alice consistently delivers high-impact features and resolves critical
      bugs. Her contributions span the full stack with a strong focus on
      reliability and performance.

      Key Contributions:
        • Implemented OAuth2 login flow reducing auth latency by 40%
        • Resolved critical data race in concurrent request handler
        • Introduced Terraform modules for reproducible deployments

      Themes: backend reliability, infrastructure automation
```

### 2. Markdown Report (`report.md` by default)

A structured Markdown file with:
- Metadata table (source, repos, period, generation timestamp)
- Developer rankings table with scores and dominant categories
- Per-developer detailed sections: categories, AI summary, key contributions, themes, and score reasoning

---

## Project Structure

```
gitReport/
├── main.py                       # CLI entry point
├── requirements.txt
├── .env.example
├── README.md
└── app/
    ├── models/
    │   └── commit.py             # Commit & DeveloperSummary dataclasses
    ├── utils/
    │   ├── logger.py             # Colored logging setup
    │   └── config.py             # Environment variable config loader
    ├── github/
    │   └── client.py             # GitHub REST API v3 client
    ├── bitbucket/
    │   └── client.py             # Bitbucket Cloud API 2.0 client
    ├── analyzer/
    │   ├── normalizer.py         # Author normalization & deduplication
    │   └── heuristic.py          # Rule-based commit classifier & scorer
    ├── ai/
    │   └── vertex.py             # Vertex AI Gemini integration
    └── report/
        └── generator.py          # Console & Markdown report generation
```

---

## Heuristic Scoring

When `--no-ai` is used (or when Vertex AI is unavailable), a weighted score is calculated:

| Category | Weight | Keywords (examples) |
|----------|--------|---------------------|
| infra    | 1.5x   | deploy, docker, terraform, helm, pipeline |
| feature  | 1.3x   | feat, add, implement, introduce |
| bugfix   | 1.2x   | fix, bug, patch, hotfix, resolve |
| refactor | 1.0x   | refactor, clean, simplify, optimize |
| test     | 0.8x   | test, spec, coverage, pytest, jest |
| docs     | 0.5x   | doc, readme, changelog, comment |

The final score is a logarithmically dampened weighted sum mapped to the 1–10 range, with a small diversity bonus for contributors who touch multiple categories.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `ValueError: Missing required environment variable: GOOGLE_CLOUD_PROJECT` | Env var not set | `export GOOGLE_CLOUD_PROJECT=my-project` |
| `GitHubAuthError: GitHub API returned 401` | Invalid/expired token | Regenerate GITHUB_TOKEN |
| `GitHubNotFoundError: Repository not found` | Wrong repo format or no access | Check `owner/repo` and token scopes |
| `BitbucketAuthError: 403 Forbidden` | Token lacks read scope | Recreate App Password with `Repositories: Read` |
| `ImportError: The 'vertexai' package is required` | Package not installed | `pip install google-cloud-aiplatform` |
| AI analysis produces fallback results | Gemini API failure | Check GCP quotas and ADC credentials |

---

## License

MIT
