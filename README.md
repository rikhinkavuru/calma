# Calma

Independent verification for quant research. Calma re-runs a systematic strategy's
backtest against ground truth and proves it, or breaks it, before capital is committed.
It ships first as an open-source skill you run yourself, on your own machine, on a path
to a CLI and a managed verification layer.

This repository is the marketing / pitch site.

## Stack

- **Next.js 14** (App Router) + **TypeScript**
- **Framer Motion** for scroll reveals, the hero parallax, and hover/press micro-interactions
- Plain global CSS with an OKLCH design-token system (warm "paper / ink", one ochre accent)
- Funnel Display / Funnel Sans / IBM Plex Mono / Newsreader via Google Fonts

## Run

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # production build + typecheck + lint
```

## Structure

```
app/            layout, page, globals.css (all styles + design tokens)
components/     Hero, HeroConsole (interactive verifier), Problem, HowItWorks,
                Roadmap (open-source -> CLI -> managed timeline), Independence,
                Closing, RequestDialog, TweaksPanel, viz (SVG diagrams), primitives
```

## Notes

- The figures in the hero console and diagrams (Sharpe ratios, filenames, verdict IDs)
  are **illustrative**, not real results.
- The roadmap uses relative phase labels (now / next / then / later / horizon); swap in
  real target dates when they exist.
- The image band uses an Unsplash photograph as a placeholder editorial plate — replace
  with an owned screenshot when available.
- A floating "tweaks" panel (bottom-right) lets you switch theme / accent / headline live
  for demos.
