# Order-10 Phase 2: independent homotopy comparison audit

**Scope:** The original order-10 census has **176** \(\Delta(G)\) versus
\(\Delta(K(G))\) comparisons left for follow-up. Phase 1 certified 85
DISTINCT, 11 EQUIVALENT, and grouped the remaining 80 original graphs
into 60 isomorphism classes of pared clique graphs. Phase 2 settles all
**80** remaining comparisons as DISTINCT, independently of the Phase-2
benchmark's full homotopy-type labels.

| Comparison | Count | Method |
|---|---:|---|
| DISTINCT (Phase 1) | 85 | Fold witnesses, exact join decompositions |
| EQUIVALENT (Phase 1) | 11 | Exact wedge-of-spheres certificates |
| DISTINCT (Phase 2) | 68 | Different reduced Euler characteristic |
| DISTINCT (Phase 2) | 12 | Different mod-2 Betti number |
| **Unresolved comparisons** | **0** | |

This **does not** mean that the full homotopy types of all 176 clique
graphs are known. The benchmark contains 38 EXACT, 17 TIMEOUT, and
5 LIMITED representative-core outcomes; those statuses have **not**
been rewritten. The independent audit requires no discrete Morse
matching, no vertex-decomposability search, and no assumption that
matching Euler characteristics imply homotopy equivalence.

## Mathematical proof methods

A *complete* is a nonempty pairwise-adjacent vertex set; a *clique* is
an inclusion-maximal complete. \(K(G)\) has the maximal completes of
\(G\) as its vertices and intersects-to-adjacency. The audited complex
is \(\Delta(G)\), the flag (clique) complex.

For a finite graph \(H\), a complete set in \(H\) is an independent
set in its complement. Its reduced Euler characteristic therefore is

\[
  \widetilde{\chi}(\Delta(H))=-I_{\overline H}(-1),
  \qquad
  I_F(t)=I_{F-v}(t)+tI_{F-N[v]}(t).
\]

The code evaluates this recurrence exactly using memoized integer
bitmasks, without enumerating every simplex. It reconstructs the
*original* \(K(G)\) from each ten-vertex graph6 and checks its
characteristic against the stored pared core independently. In
**68 of the 80 Phase-2 original graphs**, this invariant differs from
the independently computed \(\widetilde\chi(\Delta(G))\).

For the remaining **12 graphs** (represented by nine cores),
equal Euler characteristics are inconclusive. The audit enumerates
the complete subsets of each original \(G\) and reconstructed \(K(G)\)
through dimension \(d+1\), computes the ranks of the simplicial
boundary operators over \(\mathbb F_2\) by exact bitset Gaussian
elimination, and checks

\[
  \beta_d=\dim C_d-\operatorname{rank}\partial_d
         -\operatorname{rank}\partial_{d+1}.
\]

All twelve have different Betti numbers, so all are DISTINCT.
The nine representative indices and dimensions used (as search
hints, **not** assumed Betti values) are:

| Representative | Degree |
|---|---:|
| 7923665 | 3 |
| 11537978 | 3 |
| 11650233 | 3 |
| 11656524 | 3 |
| 11661308 | 2 |
| 11661348 | 3 |
| 11661524 | 3 |
| 11715924 | 3 |
| 11716425 | 2 |

For the last two especially difficult examples, the independent ranks
of \(K(G)\) are:

- 11661524: \((\dim C_3,\operatorname{rank}\partial_3,
  \operatorname{rank}\partial_4)=(10545,2214,8331)\), hence
  \(\beta_3(K(G))=0\), whereas \(\beta_3(G)=2\).
- 11716425: \((\dim C_2,\operatorname{rank}\partial_2,
  \operatorname{rank}\partial_3)=(658,148,510)\), hence
  \(\beta_2(K(G))=0\), whereas \(\beta_2(G)=2\).

## Replay and provenance

From the root of pycliques-homotopy-census, with a compatible
NetworkX environment:

    .venv/bin/python audits/order10_phase1.py --check
    .venv/bin/python audits/order10_phase2.py --check
    .venv/bin/python -m unittest discover -s tests -p 'test_order10_phase2.py' -v

If deliberately regenerating the *derived* Phase-2 output:

    .venv/bin/python audits/order10_phase2.py

The --check mode recomputes the outputs and compares **every byte** with
the committed copy. The script checks the Git blob identities of all
four input files, the benchmark's metadata, the exact 60 representative
indices, source graph6 strings, 80-member coverage, and 38/17/5
benchmark statuses. A changed input fails closed rather than silently
mixing revisions.

Generated files in this directory:

- summary.json: original and final classification totals; source blobs;
- results.tsv: all 80 newly certified original graphs, including the
  method and discriminating invariant;
- homology_witnesses.tsv: the twelve explicit chain-group sizes,
  boundary ranks, and Betti values for both \(G\) and reconstructed
  \(K(G)\).

These outputs are a **derived overlay**. Nothing in runs/order10/,
the historical summary and indices, original clique-Helly flags, or
Phase-1 certificates is modified.

**Limits of the certificate:** Exact boundary ranks and Euler
characteristics prove DISTINCT; they do not specify the full
homotopy type of \(K(G)\). The eleven EQUIVALENT verdicts still rely
on the independently replayable Phase-1 fold/join certificates, not
on the Phase-2 invariants.
