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

## Separate order-9 Morse follow-up (six timed-out cases)

The original completed 261,080-graph order-9 census is immutable historical
evidence: do **not** rerun stage 9 with a changed dependency, overwrite its
26 compressed batches, edit its manifest, or revise its original summary.

After merging the facet-greedy Morse certificate implementation into
pycliques-project, **do not update the existing census dependency pin to
recompute these old records**. The normal update script correctly refuses to
change dependencies if any census stage (such as `through6`) is not yet
validated, or a later stage remains unfinished.

Instead, run the six-record audit in a separate checkout and virtual
environment, leaving the census pin, original `.venv`, and all 261,080
historical records untouched:

~~~bash
git pull --ff-only
bash audits/run_order9_morse_followup.sh
git add followups/order9_morse/ order9_morse_followup.md
git commit -m "Resolve six order-9 timeouts with verified discrete Morse certificates"
git push
~~~

The helper fetches the current `pycliques-project` main revision, checks that
it includes the Morse module, creates a detached checkout under the ignored
`.deps/` directory, installs its *own* frozen environment, verifies the
installed source paths, and runs the audit with that environment. The audit
records the exact new upstream commit in its separate output summary. It
does **not** require `config/pycliques_commit.txt` to change.

To update the dependency for a **new full census order**, continue using
`scripts/update_pycliques.sh` once all previously started stages are fully
validated. For example, a missing `runs/through6/summary.json` may be
generated by validating that original stage with its original pinned code:
`.venv/bin/python scripts/validate.py --stage through6`.
This is independent of the six-graph follow-up.

The follow-up reads and verifies the six original, checksummed rows and
their graph6 indices. It constructs their clique graphs and records only
exact results backed by checked acyclic matchings and, where necessary,
exact rational top homology and Hurewicz. It aborts without publishing an
incomplete overlay if any of the six certificates fails.

Outputs:

- followups/order9_morse/resolved_rows.tsv: six replacement records,
  using the same columns as the original census;
- followups/order9_morse/summary.json: original and new upstream Git
  revisions, original manifest/summary hashes, and revised aggregate counts;
- order9_morse_followup.md: readable LaTeX-format six-graph results.

The original non_helly_order9.md and order-9 batch files stay unchanged.
Historical validation continues using
bash scripts/validate_historical.sh 9. Future readers should apply the
six-row overlay to obtain the revised order-9 classification, without
misrepresenting it as a result obtained with the old pinned version.


## Order-10 census: budgeted, resumable sessions and split reports

Order 10 contains 11,716,571 connected graphs, indexed in the original McKay
order. The authoritative lossless result remains the **same** 100,000-graph,
checksummed gzip batches and resumable per-graph journals. The additional
tools below do not alter the historical order-9 census or the six-row Morse
follow-up.

### Prepare and pin before the first order-10 run

The original `through6` stage used a different historical runner and
dependency revision. If `runs/through6/summary.json` is absent, validate it
with the historical validator **first**, commit its summary, and only then
change the pinned dependency:

~~~bash
git pull --ff-only
bash scripts/validate_historical.sh through6
git add runs/through6/summary.json
git commit -m "Validate historical through6 census"
bash scripts/update_pycliques.sh
git add config/pycliques_commit.txt
git commit -m "Pin Morse-enabled pycliques for order 10"
git push
.venv/bin/python -c 'from pycombtop import graph_morse_certificate; print("Morse ready")'
~~~

Do not bypass the updater's provenance guard, change the pin during a
started run, or use the separate follow-up virtualenv as the main
census environment.

### A small pilot before the full run

~~~bash
.venv/bin/python audits/benchmark_order10.py \
  --samples 120 --max-graph-seconds 120 --max-run-hours 1
~~~

This selects 120 approximately evenly spaced original graph indices across
all 11,716,571 connected graphs. Classification uses the actual pinned
census implementation. Results go to `benchmarks/order10_pilot.tsv`,
with companion `.meta.json` and `.summary.json` files. The script
periodically flushes records and resumes using the same sample count and
code revision; a change of revision requires a new output path. The summary
reports the sample mean, median, p90, p99, timeout and unresolved counts,
and a *rough* projected single-worker duration. The projection is
uncertain because sparse samples may miss expensive cases.

A pilot run creates **no** `runs/order10/` manifest, and it does not
consume or modify the full census's checkpoint stream.

### Full run: 2 minutes per whole graph, a session cutoff

~~~bash
bash run_with_report.sh 10 --max-graph-seconds 120 --max-run-hours 16
~~~

The new `--max-graph-seconds 120` timer applies to the whole graph:
decoding, Helly tests, G and K(G) construction, and both homotopy
calculations. It is a **soft** wall-clock limit: long native calls can
delay Python signal delivery. If the graph times out, the index is
still recorded; previously completed exact subresults and Helly flags
are kept, and unknown data are explicitly marked `UNKNOWN` and
`LIMITED`. A bounded graph is never falsely recorded as contractible.
The existing `--max-homotopy-seconds` option retains its different,
per-homotopy semantics; do not combine the two timers.

`--max-run-hours 16` ends the current Codespaces session at a
**graph boundary**, flushes and fsyncs the current journal, and returns
without incorrectly claiming that the whole order is complete.
The cutoff can overshoot by a single graph and by the time taken to
write reports; it is **not** a GitHub spending limit. This particular
session-hours setting is intentionally *not* part of the immutable
manifest, so it can vary on subsequent resumes. All classification
settings (including `--max-graph-seconds 120`) **must remain identical**
for the whole order.

To resume, repeat exactly the same command (with a different session
cutoff if desired). The wrapper creates an incremental report from
completed batches and prints read-only progress. Full validation is
performed only after the final batch has completed. If a potential
counterexample is found, the normal stop-and-independent-verification
logic takes priority.

For a quick check without running classification:

~~~bash
.venv/bin/python reports/order10_progress.py
.venv/bin/python reports/order10_split.py --max-part-kib 768
.venv/bin/python reports/order10_exceptions.py
~~~

The root report `non_helly_order10_index.md` lists completed batch ranges,
counts, and links to detailed parts in `reports/order10_parts/`.
Each part has a target maximum of 768 KiB. Complete batches are verified
against their SHA-256 markers, report parts are generated incrementally,
and per-batch metadata avoids regenerating previous parts. The report
excludes uncommitted partial journals until they become completed batches.
No single enormous Markdown file is created. Generated detailed reports
may collectively be hundreds of MB; check their size and GitHub repository
storage before deciding how much to commit. The compressed census
batches remain the authoritative scientific record.

### Monthly Codespaces allowances and commits

The free included allowance is **core-hours**, not clock hours. A 2-core
Codespace consumes two core-hours for every clock hour it runs; opening
an idle Codespace can also consume compute allowance. The 16-hour
example deliberately leaves room for other work, but check the
current GitHub billing meter before and after each session.
After any session, commit *completed* compressed census
batches and SHA-256 markers, the small report indexes, and the **compressed,
checksummed checkpoint**. Do **not** commit the raw partial TSV: it can
exceed GitHub's ordinary file-size limit. Avoid running concurrent writers
to the same `runs/order10/` directory.

#### Converting the first session's large committed journal

The first session committed a nearly 100 MB journal at
`runs/order10/order10/partial/00600000-00699999.partial.tsv`. After
merging the checkpoint PR, **before resuming**, run:

~~~bash
git pull --ff-only
.venv/bin/python audits/order10_checkpoints.py snapshot
git status --short
git commit -m "Store order-10 partial census as a compressed checkpoint"
git push
~~~

The snapshot command round-trip verifies the gzip bytes, records the original
manifest SHA-256 and complete sequential row count, stages the compressed
`checkpoints/order10/*.partial.tsv.gz` and `*.snapshot.json` files,
and untracks the old raw TSV using `git rm --cached` **only after**
verification succeeds. The raw TSV remains on your Codespace disk. The
command stages only these checkpoint-specific changes; if you have other
uncommitted changes, examine `git status` and stage them separately. The
historical commit containing the large blob is left untouched; we do not
rewrite Git history.

For subsequent sessions, the wrapper runs `restore` before computation and
`snapshot` after a normal pause or completion. A newly created Codespace
will restore the exact original TSV from a matching gzip snapshot if the
local TSV is absent. Existing local TSV data are never overwritten. The
original 100,000-graph batch, source graph indices, 120-second per-graph
limit, and dependency pin remain unchanged. If a batch is completed, its
verified authoritative gzip chunk supersedes the partial snapshot and
the snapshot is pruned/staged for deletion. The helper never modifies
`scripts/` or the order-10 manifest.

After a session, check and commit the results:

~~~bash
.venv/bin/python reports/order10_progress.py
.venv/bin/python audits/order10_checkpoints.py status
git add runs/order10/order10/chunks/ runs/order10/order10/completed/ \
  reports/order10_parts/ reports/order10_exceptions/ \
  non_helly_order10_index.md order10_exceptions_index.md
git status --short
git commit -m "Order-10 census session results and compressed checkpoint"
git push
~~~

The raw partial TSV is ignored by Git even if a `git add -A` is used,
provided the initial `snapshot` migration has untracked the previously
committed raw file. Do not use `git add -f` to override the ignore rule.
In an emergency after an abnormal stop, run the standalone `snapshot`
command once the census process has exited; if the last line is torn,
first let the existing census runner perform its journal recovery.

When the stage is fully complete, run:

~~~bash
.venv/bin/python scripts/validate.py --stage 10
.venv/bin/python reports/order10_split.py
git status --short
~~~

Keep the graph budget and upstream pin fixed from the first classified
graph through the final row. The second-stage follow-up of limited or
Betti-only cases, if needed, should be done in a **separate overlay**,
not by overwriting a completed order-10 batch.

The companion `order10_exceptions_index.md` lists per-batch compressed
`reports/order10_exceptions/*_nonexact.tsv.gz` records. They contain all
`LIMITED` and `BETTI_ONLY` classifications from completed batches,
retaining graph6 indices, available Betti numbers and explanations for
later targeted follow-up work. This is a separate index, not a replacement
for the original full census results.
