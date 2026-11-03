# Connected graph and clique-graph homotopy census

A reproducible census of the homotopy types of the **clique complexes** of all connected, unlabeled, finite simple graphs of orders 1–10 and of their clique graphs. The computation records whether each of `G` and `K(G)` is clique-Helly (abbreviated **Helly** throughout).

## Graph sources and original indices

**Orders 6–10:** the original *connected* Brendan McKay graph6 files bundled in Rafael Villarroel's `pyg6data` package, exactly those read by `pyg6data.lists.graph_generator(n, connected=True)`. The implementation streams raw file lines for efficiency, especially when skipping completed order-10 batches. It **does not reorder, sort, relabel, or canonicalize** these strings. The original **zero-based source index** is recorded and agrees with `pycliques-census`.

**Orders 1–5:** NetworkX `graph_atlas_g()` filtered to connected graphs, as in the earlier `pycliques-census`. `pyg6data` has no separate connected files for these orders. The McKay data are from [Brendan McKay's graph data](https://users.cecs.anu.edu.au/~bdm/data/graphs.html).

| Order | Connected graph count | Logical stage | Batch size |
|--:|--:|:--|--:|
| 1–6 | 143 | `through6` | 10,000 |
| 7 | 853 | `7` | 10,000 |
| 8 | 11,117 | `8` | 10,000 |
| 9 | 261,080 | `9` | 10,000 |
| 10 | 11,716,571 | `10` | 100,000 |

The expected counts are those of OEIS A001349. A **stage** is one run per order, with a combined initial stage for orders 1–6; batch boundaries are *internal checkpoints*, not additional mathematical stages.

## Codespaces

Open this repository in GitHub Codespaces. The devcontainer automatically runs `scripts/bootstrap.sh`, using a **pinned** commit of [`pycliques-project`](https://github.com/rvf0068/pycliques-project) and its frozen `uv.lock`. Run:

```bash
bash scripts/run.sh through6
.venv/bin/python scripts/validate.py --stage through6
bash scripts/run.sh 7
.venv/bin/python scripts/validate.py --stage 7
bash scripts/run.sh 8
.venv/bin/python scripts/validate.py --stage 8
bash scripts/run.sh 9
.venv/bin/python scripts/validate.py --stage 9
bash scripts/run.sh 10
.venv/bin/python scripts/validate.py --stage 10
```

Each command can be restarted with the **same pinned code and parameters** after a Codespaces disconnect. Completed batches have deterministic gzip files and SHA-256 `.done.json` markers. An unfinished batch has a durable per-graph partial journal (**also committable to Git**); on resumption, completed graph records in that journal are checked against the original graph6 lines and skipped. The manifest prevents silently continuing with another upstream version, dataset, Python version, runner version, or resource configuration. Checkpoint writes use atomic renames. No files are auto-committed or pushed to GitHub.

The initial run and tests also run on push through GitHub Actions. **Do not run the 9- and 10-vertex stages on GitHub Actions:** they are potentially resource-intensive; use Codespaces and commit results deliberately.

## Main table and meaning of verdicts

Each completed batch contains one TSV row per original connected graph, with fields:

`order`, `index`, `graph6`, `helly_g`, `helly_kg`, `k_order`, `status_g`, `htype_g`, `betti_g`, `reason_g`, `status_kg`, `htype_kg`, `betti_kg`, `reason_kg`, `comparison`.

- Helly fields: `TRUE`, `FALSE`, or `UNKNOWN` (only if constructing the clique graph exceeded a limit).
- `EXACT`: the upstream homotopy algorithm certified a wedge-of-spheres type. `htype_*` is the **sparse sphere-multiplicity vector**, for example `1:3;2:1` represents three circles wedged with a 2-sphere; `0` represents a contractible complex.
- `BETTI_ONLY`: the upstream code computed reduced Betti numbers without establishing a homotopy equivalence to a wedge of spheres. `htype_*` is therefore `UNKNOWN` even when the Betti vector is all zero.
- `LIMITED`: no sufficient result within configured resource limits; `htype_*` and `betti_*` are `UNKNOWN`.
- `comparison`: `EQUIVALENT` when both types are certified wedges with matching multiplicities; `DISTINCT` when their reduced Betti vectors differ (an obstruction to equivalence); otherwise `UNRESOLVED`.

A row may report `DISTINCT` when the **Helly hypothesis is false**, e.g. for the octahedral graph. The purpose is to test the conjecture `K(G)` Helly implies `Delta(G) ~= Delta(K(G))`, not to assert equivalence for all graphs.

### Counterexample stopping rule

When `helly_kg=TRUE` and `comparison=DISTINCT`, the runner reconstructs the graph from its recorded graph6 string, recomputes the verdicts, recomputes clique-Helly status and independently invokes the rational homology routine. If the reduced Betti vectors still differ, it writes `runs/<stage>/STOP_COUNTEREXAMPLE.json` and **exits with code 42** before processing the next graph. A subsequent invocation refuses to restart while the witness exists. A discrepancy should be checked independently before publication. The runner also aborts for invariants contradicting the known Helly-graph result.

Both `G` and `K(G)` homotopy classifiers are taken from the pinned `pycombtop` package, including the verified link-attachment, join, s-collapse, and discrete Morse techniques. There are **no extra classification stages**. Changing resource limits requires a new named run rather than mixing old output with new.

## Summaries and audits

The validator re-reads the original graph6 source and checks every source index, input string, row status, comparison, batch row count and compressed file hash. On success it writes a `summary.json` and deterministic `unresolved_order<n>.tsv.gz` files. The unresolved list includes cases where identical Betti numbers do not certify equivalence. The run's `manifest.json` includes hashes of the original graph6 datasets (for orders 6–10), the runner, the upstream lockfile and the exact upstream Git SHA.

## Literature

- Brendan D. McKay, [*Graph data*](https://users.cecs.anu.edu.au/~bdm/data/graphs.html), original connected unlabeled graph6 datasets.
- M. C. Lin and J. L. Szwarcfiter, *Faster recognition of clique-Helly and hereditary clique-Helly graphs*, Information Processing Letters **103** (2007), 40–43. This is the implementation referenced in `pycliques.helly`.
- R. Forman, *Morse theory for cell complexes*, Advances in Mathematics **134** (1998), 90–145.
- X. Dong, *Topology of bounded-degree graph complexes*, Journal of Algebra **262** (2003), 287–312.
- A. Björner and M. L. Wachs, *Shellable nonpure complexes and posets. I*, Transactions of the AMS **348** (1996), 1299–1327.
- R. Boulet, É. Fieux and B. Jouve, *Simplicial simple-homotopy of flag complexes in terms of graphs*, European Journal of Combinatorics **31** (2010), 161–176.

The reasons stored in each row refer to the actual hypotheses and methods implemented in the pinned versions of `pycliques` and `pycombtop`; they do not quote ChatGPT-generated research reports.