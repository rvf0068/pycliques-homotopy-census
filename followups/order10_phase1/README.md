# Order-10 structural follow-up — Phase 1

**Baseline (immutable):** `runs/order10/summary.json`, 118 original completed
batches, 11,716,571 connected graphs; commit `8e768705fd8b41c5ca2cfea1ed9eedf633f5a43d`.
This folder is a **separate derived overlay**, not a replacement for the original
census reports or rows. No old classifications are modified.

Phase 1 reconstructs each of the **176** originally unresolved `K(G)` from the
original graph6 string. It records and replays a complete sequence of fold
witnesses `N[v] ⊆ N[u]`, reducing the clique graph to a strong core. On the
complement of this core, it tests connected components for `K1`, `K2`, `C6`,
and `C10`; these give exact joins of independence complexes:

- `K1` yields a cone (contractible).
- `Ind(K2) ≃ S⁰`, `Ind(C6) ≃ S¹ ∨ S¹`, `Ind(C10) ≃ S²`.
- Their simplicial join has an exact sphere-wedge type, so comparison with the
  original **EXACT** `G` certificate is decisive. Betti equality alone would
  **not** suffice without both exact wedge certificates.

Results: **11 equivalent**, **85 distinct**, **80 unclassified**. The 80
unclassified graphs have **60 pairwise nonisomorphic pared clique graphs**.
The 60 classes are established using exact NetworkX graph isomorphism, with
WL hashing and degree sequences used *only* as necessary filters. Each member's
explicit vertex mapping into its representative is included in the generated
certificate file.

## Regenerate and verify

From the root of `pycliques-homotopy-census`, with the pinned original `.venv`:

```bash
.venv/bin/python audits/order10_phase1.py
.venv/bin/python audits/order10_phase1.py --check
.venv/bin/python -m pytest tests/test_order10_phase1.py -q
```

The audit reads and checks the original `runs/order10/summary.json` and
`runs/order10/unresolved_order10.tsv.gz`. It produces deterministic:

- `summary.json`: counts, source hashes, methods, original commit pin.
- `results.tsv`: all 176 rows and the newly certified comparisons.
- `representatives.tsv`: exactly 60 original indices, the pared core graph6,
  and all corresponding source indices.
- `certificates.json`: fold witnesses, complementary components and types,
  and explicit isomorphism maps for repeated cores.

The script's `--check` mode **only compares** regenerated output bytes against
saved files; it does not rewrite them. Changes in NetworkX graph6 labeling
may require explicit review and an updated overlay, never a change to the
original census.

## Next phase

Benchmark `pycombtop` improvements on the 60 representative cores first.
Full vertex/edge s-collapses and recognition of complementary joins should
run before the simplex-budget rejection where appropriate; preserve the
original `K(G)` clique-Helly flags. A future Dong-matching optimization should
use both a local seeded generator and a stable ordering of candidate simplices
before shuffling, so results do not depend on process hash order.