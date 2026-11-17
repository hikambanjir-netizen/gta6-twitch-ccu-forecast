# gta6-twitch-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/hikambanjir-netizen/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/hikambanjir-netizen/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

An hour-by-hour forecast of how many people watch Grand Theft Auto VI live on Twitch across its release day, 19 November 2026 (UTC), as five quantiles an hour — built from the first hour's print and the shapes of past big launches.

## The model

A launch day's audience curve has a shape that repeats across big game launches: a first-hour spike at the midnight-local unlock, a dip while most of the world sleeps, a jump when the US east coast unlocks, a midday trough, then a long climb into the evening peak. The level is anchored by the case's own hour-1 print; the shape is learned at run time from the case's own `comparables` — the hourly curves of past big launches shipped inside every case — so nothing about any one launch is baked in.

The key regularity the model exploits is that **big launches and small launches do not share one shape**. A launch whose first hour is small surges far more into the evening than one whose first hour is already huge: the two biggest comparables (ELDEN RING, Cyberpunk 2077, ~850k in hour 1) end their day near flat, while small ones climb several-fold. So for each hour the program regresses the log ratio `ln(viewers_h / viewers_1)` on the log of the launch's hour-1 size across the comparables, and reads the fit off at this case's hour-1 size. The residuals of that fit set the predictive spread, which widens over the horizon. Both curves are lightly smoothed across neighbouring hours.

Comparables are filtered first: hour-1 print of at least 10,000 viewers (below that the ratios are driven by a near-zero denominator) and no early-access-contaminated, weak, or target-history tier. The slope is clamped to [-1.5, 0.5], the evaluated size to the sizes actually seen, and the fitted median to the observed ratio range for the hour — so a record-breaking GTA VI hour 1 behaves like the biggest launch on record instead of extrapolating off a cliff. With too few usable comparables it falls back to the median ratio, and with none at all to persistence. It never crashes on a malformed case: any failure degrades to the persistence forecast, because an invalid case costs far more than a mediocre one.

## Validation

Scored with the contest's own pinball loss on the log scale, against ground truth rebuilt from the public source the kit names (SullyGnome hourly averages; the hour-1 prints match the kit's cases exactly on all four practice launches):

| Evaluation | This entry | House flat baseline |
|---|---|---|
| 4 practice launches (held out) | **0.167** | 0.387 |
| Leave-one-out over 18 comparable launches | **0.282** | 0.392 |
| Big launches only (hour-1 ≥ 300k), leave-one-out | **0.133** | 0.352 |

On the practice cases the typical miss is 19–40% per launch against the house's 42–189%, with 90% coverage of 0.78–0.96 (nominal 0.9). Outputs are byte-identical across runs; ~0.05 s per case, far inside the 8 s cap.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, no network. Reads every `*.in` in the input directory and writes one `<id>.out` per case: `{"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]}` for hours 2–24.

---

<sub>Entered on [make.fun](https://make.fun/?ref=dfkzjsa3&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
