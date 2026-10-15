# Candidate ranker model card

## What was trained

Artifact: `src/agv/models/candidate-ranker.json`; schema: `agv-candidate-ranker-v1`. The model is an eight-feature linear ridge regressor, trained with deterministic full-batch gradient descent using the Python standard library. It ranks which **vehicle-pair suffix repairs** to try under a six-candidate budget. Whole-fleet fallback remains available and does not depend on the learned ranking.

The model does not predict or control robot motion. It cannot waive collision checks, change task ownership, interrupt service or commit an infeasible route. The existing feasible plan is retained whenever a candidate fails or does not improve the actual lexicographic objective.

## Public data and splits

Source: [MovingAI MAPF benchmark collection](https://movingai.com/benchmarks/mapf.html), map `warehouse-10-20-10-2-1.map`, ODC-By v1.0. Attribution and SHA256 are retained in `data/`. No private dataset or undisclosed internal model is used.

Each scene is a derived online pickup/delivery simulation: a 32×24 rectangle of the original map, its largest connected floor component, four appended parking pockets, 16 generated shelf orders in batches of four every20 steps, and random1–3 step load/unload durations. These are not official MAPF tasks or benchmark scores.

| Partition | Original map crop (x,y,width,height) | Order seeds | Independent scenes | Candidate rows |
|---|---|---|---:|---:|
| Training | (32,1,32,24) | 0–7 | 8 | 3,828 |
| Validation | (64,1,32,24) | 100–102 | 3 | 1,542 |
| Test | (96,34,32,24) | 200–205 | 6 | Full heldout simulation evaluation |

The regions do not overlap and seeds do not overlap. Normalization means/scales, weights and intercept use training rows only. Validation chooses regularization from `{0.01,0.1,1.0}`. Test scenes are not used to fit, normalize or choose regularization. All regions come from one repetitive warehouse layout, so they support a within-source spatial/order holdout, not unseen-warehouse generalization.

Candidate rows from one scene are correlated. 3,828 rows must not be presented as 3,828 independent warehouse experiments; the training sample consists of eight independent generated order streams on one training crop.

## Features and target

Features, in artifact order:

1. Number of selected vehicles.
2. Total stationary steps in their known remaining plans.
3. Maximum stationary steps of one selected vehicle.
4. Total shared spatial cells among selected paths.
5. Sum of remaining path lengths.
6. First planned vehicle's stationary steps.
7. First planned vehicle's remaining path length.
8. Number currently loading or unloading.

Stationary steps include service. Shared spatial cells ignore time. They are low-cost proxies, not actual causal traffic delay or collision counts. They use only currently visible assigned-task plans; no unreleased order fields enter the feature vector.

The label is the reduction in the primary remaining-flow objective after attempting this candidate relative to the incumbent at that point in the search. A previous candidate may already have improved that incumbent, so the label depends on search order. Infeasible repairs receive `-1`, labels are clipped to `[-5,10]`, and secondary-objective-only improvement has label0. Predictions are a ranking score, not calibrated seconds, feasibility probabilities or an intrinsic order-independent value.

## Training result and interpretation

Selected regularization: `1.0`. Validation mean squared error: `0.563146`; constant training-mean prediction: `0.577677`, a reduction of approximately2.52%. The same validation partition selected regularization; this is a selection statistic, not an unbiased test result or proof of better full scheduling.

The relevant test is full heldout scheduling compared with `sipp_budget`, which uses the same six-candidate budget and hand-designed ordering. `sipp_conflict` uses a larger budget and answers a separate quality/compute tradeoff question. Detailed positive and negative full-run results are reported in `results/v2/` and `docs/v2-results.md`.

## Reproduction

```bash
agv train --map data/maps/warehouse-10-20-10-2-1.map --output runs/my-training
agv benchmark --seeds 10 --map data/maps/warehouse-10-20-10-2-1.map --output runs/my-evaluation
```

Training writes the learned artifact into the chosen output directory. It does **not** replace the shipped model automatically. To evaluate newly fitted parameters, explicitly replace the packaged model in a development checkout, rerun the checks, then use a fresh output directory; source hashes record the model actually tested. A production default should not be changed solely because validation MSE fell.
