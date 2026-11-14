# Exact homotopy types for the 177 order-10 exceptions

The original order-10 census recorded 176 clique-graph types as `LIMITED` and one input-graph type as `BETTI_ONLY`. The table supplies both full homotopy types for each of these 177 rows. Together with the original rows, this gives exact types for both complexes of all **11,716,571** connected graphs of order 10. There are **10,959,509** homotopy-equivalent pairs and **757,062** distinct pairs. The earlier audit had already settled all 176 unresolved comparisons.

[Results with source indices and graph6](results.tsv) · [Summary](summary.json) · [Earlier comparison audit](../order10_phase2/README.md)

## Reading the table

Match the zero-based `index` and original `graph6` to the census. The columns `htype_g` and `htype_kg` give sparse vectors of sphere multiplicities. For example, `3:1;4:3` represents one 3-sphere wedged with three 4-spheres, and `0` denotes a contractible complex. `representative_index` points to the representative of the pared clique graph where appropriate. All types in this follow-up are exact. The historical batches retain the verdicts produced by their pinned algorithms.

## Certificates

* For 96 clique graphs, replaying ordinary folds and recognizing the complement factors gives the exact join type from Phase 1.
* The other 80 clique graphs have 60 nonisomorphic pared cores. The audit certifies each representative and checks every saved isomorphism on vertices and edges before transferring its type. The benchmark had 38 exact representatives, and two more were established in earlier follow-ups. Recursive vertex-star certificates give 18 of the final 20 types. Signed integral Morse boundaries give the other two.
* For `11661524`, the bipartite complement reduces the problem to a suspension. The smaller complex has a Morse model with one vertex, three 4-cells and one 5-cell. The boundary of the 5-cell is zero over the integers, giving three 5-spheres and a 6-sphere after suspension. For `11716425`, the clique graph itself has a Morse model with one vertex, one 3-cell and three 4-cells, again with zero integral boundary. For both models the lower positive dimension is at least two, so Hurewicz identifies the attaching classes with their degrees.
* The remaining input graph, index `7749135`, has nonadjacent vertices 8 and 9 adjacent to each of the other eight vertices. Those eight vertices induce two disjoint four-cycles. Consequently the flag complex is the unreduced suspension of two disjoint circles. Each circle contributes a 2-sphere, and the two components contribute one circle. Thus \(\Delta(G)\simeq S^1\vee S^2\vee S^2\). Its original clique-graph verdict was already exact.

[Twenty residual clique-graph types and their certificate methods](remaining_types.jsonl) · [Pinned pycliques-project revision](../../config/order10_exact_types_commit.txt)

## Replay

Run these commands from the root of `pycliques-homotopy-census`. The audit imports the algorithms from a separate checkout of `pycliques-project`. For the final 20 representatives it reconstructs the actual clique graph at each original McKay graph6 offset and calls `homotopy_type_with_verdict` with the benchmark limits of 64 vertices and 25,000 simplices. It checks the clique-graph order, exact sphere multiplicities, and certificate method against the JSONL table. It also replays the folds and isomorphisms for the full 177-row follow-up and compares all three output files byte for byte. The [CI regression tests](../../tests/order10_exact_types/test_replay.py) run this computation once and independently check the representative transfers, the two-square suspension, and the final totals.

```sh
git clone https://github.com/rvf0068/pycliques-project.git .deps/pycliques-order10-types
git -C .deps/pycliques-order10-types checkout --detach "$(cat config/order10_exact_types_commit.txt)"
uv sync --project .deps/pycliques-order10-types --frozen --no-dev --python 3.11
.deps/pycliques-order10-types/.venv/bin/python audits/order10_exact_types.py --check
```
