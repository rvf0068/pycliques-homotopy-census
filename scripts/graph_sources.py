"""Source-exact graph6 enumeration; zero-based original source indices.

Orders 1--5: NetworkX atlas in its published order (same as pycliques-census).
Orders 6--10: raw graph6 lines of Professor McKay's connected files as
bundled in pyg6data, precisely the lines used by graph_generator(..., connected=True).
Reading raw lines avoids constructing millions of NetworkX graphs when
resuming at order ten. No canonicalization or graph6 sorting occurs.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from importlib import resources

import networkx as nx

EXPECTED_COUNTS = {
    1: 1, 2: 1, 3: 2, 4: 6, 5: 21, 6: 112,
    7: 853, 8: 11117, 9: 261080, 10: 11716571,
}
CONNECTED_FILES = {n: f"graph{n}c.g6.gz" for n in range(6, 11)}


def data_path(n: int):
    """Return the bundled original connected graph6 file in pyg6data."""
    if n not in CONNECTED_FILES:
        raise ValueError(f"No pyg6data connected source for order {n}")
    return resources.files("pyg6data.data").joinpath(CONNECTED_FILES[n])


def graphs6(n: int) -> Iterator[str]:
    """Stream graph6 strings in their original source order (without sorting)."""
    if n not in EXPECTED_COUNTS:
        raise ValueError(f"Unsupported order: {n}")
    if n <= 5:
        for graph in nx.graph_atlas_g():
            if len(graph) == n and nx.is_connected(graph):
                yield nx.to_graph6_bytes(graph, header=False).decode("ascii").strip()
        return
    with data_path(n).open("rb") as stream:
        with gzip.open(stream, mode="rt", encoding="ascii") as data:
            for line in data:
                line = line.strip()
                if line:
                    yield line


def graph_from_string(graph6: str) -> nx.Graph:
    """Decode the original graph6 without changing its vertex ordering."""
    return nx.from_graph6_bytes(graph6.encode("ascii"))
