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

## Order-9 performance and optional per-graph time budget

The census uses a pinned `pycombtop` revision which first checks cheap exact
cone and join certificates before enumerating simplices. If **G itself is
Helly** and the homotopy type of G is certified exactly, Prisner's theorem
transfers the result to K(G), saving the second homotopy calculation. The
independent K(G) Helly test is retained. If only **K(G) is Helly**, the
homotopy type is still computed independently: the conjecture under
investigation is never assumed.

To bound a potentially expensive homotopy classification during the much
larger order-9 run, supply a **per-classification soft wall-time limit**
(seconds), for example:

```bash
bash scripts/run.sh 9 --max-homotopy-seconds 120
.venv/bin/python scripts/validate.py --stage 9
.venv/bin/python reports/non_helly.py --stage 9
```

The default `--max-homotopy-seconds 0` disables this timeout.
The timer runs separately for each invocation of the homotopy classifier
(G and/or K(G)), not for all stages and not for clique-graph construction.
It uses POSIX timers, supported in Linux Codespaces. A timed-out
classification is stored as `LIMITED` with unknown homotopy type and Betti
numbers; **it is not declared contractible**. The limit is part of the
stage's immutable provenance manifest, so choose it *before* starting order 9
and keep it fixed for every resume. If you prefer unrestricted classifications,
run `bash scripts/run.sh 9` without any extra options.

The CI workflow recomputes all 12,113 connected graphs through order 8 in
a separate temporary results directory and checks the index, graph6, Helly
flags, type exactness, reduced Betti numbers, and comparisons against the
historically committed results. Changes to explanatory theorem strings are
allowed.

## Updating `pycliques-project` between completed runs

From the root of the Codespace, run:

```bash
bash scripts/update_pycliques.sh
```

This fetches the latest `main` commit of `pycliques-project`, updates
`config/pycliques_commit.txt`, and runs `scripts/bootstrap.sh` to install
the newly pinned `pycliques`, `pycombtop`, and `pyg6data`. **It does not
change any census results**, nor does it automatically commit the new pin.
After a successful update, record it before starting the next order:

```bash
git add config/pycliques_commit.txt
git commit -m "Update pycliques-project pin"
git push
```

**Safety condition.** The update command checks *every* started order:
all expected batches must be complete and their SHA-256 markers valid,
the run must have a matching validation `summary.json`, and its original
census scripts and pin must be recoverable from committed Git history.
An incomplete order, a partial checkpoint, an unvalidated stage, or a
stopped counterexample blocks the update. Finish and validate the order
before changing the dependency, even if the next completed batch has not
started. Never update halfway through order 9 or 10.

**Historical validation.** After an update, the standard validator
intentionally refuses to reinterpret an old run using newer code. To
validate an earlier stage using its *original* census scripts and
`pycliques-project` dependencies, run:

```bash
bash scripts/validate_historical.sh through6
bash scripts/validate_historical.sh 7
# Similarly for 8, 9, or 10
```

The command looks up the recorded runner SHA-256 in Git history,
checks out that exact census version in an isolated Git worktree,
checks out the original upstream SHA in another worktree when needed,
and uses its frozen `uv.lock` to restore the dependency environment.
Only the specified run's results directory is linked into the historical
workspace. It does **not** switch the current code, pin, or active Python
environment. Historical worktrees and their virtual environments are
ignored by Git and may occupy additional disk space.

For this reconstruction to work, commit the runner code and updated pin
**before** starting each new order. If the Codespace has a shallow Git
checkout and the old revision cannot be found, fetch full history with
`git fetch --unshallow` (when applicable).

## Readable non-Helly graph reports

The census retains detailed, lossless records in its compressed result
batches. For a **human-readable Markdown file at the repository root**,
listing only those graphs for which **G is not Helly**, run:

```bash
git pull --ff-only
.venv/bin/python reports/non_helly.py --stage through6
```

This creates `non_helly_through6.md` **without rerunning any graph
classification**. The report includes the order, original zero-based index,
original graph6 string, the certified clique-complex homotopy types of both
G and K(G), and the Helly status of K(G). For example, it prints inline
LaTeX math such as `\(S^{1}\)`, `\(S^{1}\vee S^{2}\)`, or
`Contractible`. If a homotopy type was not certified, the table says
`Undetermined` rather than inferring contractibility from Betti numbers.
Graph6 special characters are escaped safely for Markdown tables.

For a **single command that runs, validates, and produces the report**, use:

```bash
bash run_with_report.sh through6
bash run_with_report.sh 7
```

The same wrapper accepts `8`, `9`, and `10`, producing
`non_helly_order8.md`, etc. Alternatively you may keep using
`scripts/run.sh` and generate the report separately once the stage is
complete. A report is written atomically only after all expected batches
are present, their checkpoint hashes match, and their indices are
consecutive. It reads recorded data and does **not** alter run manifests,
partial journals, or completed result files.

**Earlier completed runs need not be discarded.** The report generator
is deliberately kept outside the provenance-hashed `scripts/`
directory, and the original runner and validator are unchanged. Very large
orders may create correspondingly large Markdown files; commit those only
after inspecting their size.

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

The consistency checks use two established results: if `G` is Helly,
then `G` and `K(G)` are homotopy equivalent (Prisner), and `K(G)`
is also Helly (Escalante). Thus any apparent violation of either known
implication is a data or implementation fault to investigate, not a
counterexample to the conjecture being tested.

Both `G` and `K(G)` homotopy classifiers are taken from the pinned `pycombtop` package, including the verified link-attachment, join, s-collapse, and discrete Morse techniques. There are **no extra classification stages**. Changing resource limits requires a new named run rather than mixing old output with new.

## Summaries and audits

The validator re-reads the original graph6 source and checks every source index, input string, row status, comparison, batch row count and compressed file hash. On success it writes a `summary.json` and deterministic `unresolved_order<n>.tsv.gz` files. The unresolved list includes cases where identical Betti numbers do not certify equivalence. The run's `manifest.json` includes hashes of the original graph6 datasets (for orders 6–10), the runner, the upstream lockfile and the exact upstream Git SHA.

## Literature

- E. Prisner, *Convergence of iterated clique graphs*, Discrete
  Mathematics **103** (1992), 199–207,
  [doi:10.1016/0012-365X(92)90270-P](https://doi.org/10.1016/0012-365X(92)90270-P).
- F. Escalante, *Über iterierte Clique-Graphen*, Abhandlungen aus dem
  Mathematischen Seminar der Universität Hamburg **39** (1973), 59–68.
- Brendan D. McKay, [*Graph data*](https://users.cecs.anu.edu.au/~bdm/data/graphs.html), original connected unlabeled graph6 datasets.
- M. C. Lin and J. L. Szwarcfiter, *Faster recognition of clique-Helly and hereditary clique-Helly graphs*, Information Processing Letters **103** (2007), 40–43. This is the implementation referenced in `pycliques.helly`.
- R. Forman, *Morse theory for cell complexes*, Advances in Mathematics **134** (1998), 90–145.
- X. Dong, *Topology of bounded-degree graph complexes*, Journal of Algebra **262** (2003), 287–312.
- A. Björner and M. L. Wachs, *Shellable nonpure complexes and posets. I*, Transactions of the AMS **348** (1996), 1299–1327.
- R. Boulet, É. Fieux and B. Jouve, *Simplicial simple-homotopy of flag complexes in terms of graphs*, European Journal of Combinatorics **31** (2010), 161–176.

The reasons stored in each row refer to the actual hypotheses and methods implemented in the pinned versions of `pycliques` and `pycombtop`; they do not quote ChatGPT-generated research reports.