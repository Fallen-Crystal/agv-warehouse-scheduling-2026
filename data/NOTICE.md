# Public dataset notice

The file `maps/warehouse-10-20-10-2-1.map` was obtained from the Moving AI Lab MAPF benchmark collection:

- Collection and attribution: https://movingai.com/benchmarks/mapf.html
- Original archive: https://movingai.com/benchmarks/mapf/warehouse-10-20-10-2-1.map.zip
- Dataset license: Open Data Commons Attribution License (ODC-By) v1.0, https://opendatacommons.org/licenses/by/1-0/
- The source URL and SHA256 are retained alongside the map in `.source.json`.

Contains information from the Moving AI Lab benchmark collection, made available here under the Open Data Commons Attribution License (ODC-By).

Derived scenarios use non-overlapping rectangular regions of that map, retain the largest connected floor component, attach four dedicated parking pockets, and generate online shelf pickup/delivery orders with 1–3 step services. Crop bounding boxes and training/validation/test seed lists are recorded in `results/training/training-report.json`. They are **derived MAPD simulation data**, not the official MAPF scenario workload or leaderboard scores. A single warehouse's repeated shelf pattern limits generalization even across disjoint regions.

Training uses the train region/seeds only. Validation chooses ridge regularization; neither test regions nor test seeds are used to fit or select the model. No private dataset is used. The dataset notice is separate from code provenance and does not change rights to the teammate's original code.
