# Provenance

The domain model, original time-expanded A*, greedy dispatcher, simulation rules, metrics, independent validator and original viewer behavior are derived from the teammate-provided `agv_modeling_shelf` project supplied by the repository owner. The original source directory on the owner's Desktop was preserved. We have not assigned a new license to that third-party contribution.

The package layout, interval planner, reservation index, conflict-based candidate selection, learned candidate ranker, training pipeline, CLI and hardening changes are project-specific adaptations. SIPP, RHCR and MAPF-LNS are prior research; exact papers and inspected open-source repositories are cited in `docs/research/`. External project implementations were inspected as engineering references; they were not vendored into this repository.

Public map data has its own ODC-By attribution notice at `data/NOTICE.md`. Training uses that public source and generated task labels, with no private or undisclosed dataset. Historical v1 measurements remain labeled as historical in `results/v1/`.
