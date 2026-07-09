"""Vendored copy of pycea's ancestral-linkage compute.

Only the compute chain of ``pycea.tl.ancestral_linkage`` is vendored (the module and its
five helper modules), with intra-package imports rewritten to relative imports. This
avoids depending on ``pycea`` as a whole, whose top-level ``__init__`` eagerly imports the
plotting submodule and therefore pulls in matplotlib and scanpy. The compute itself needs
only networkx / numpy / pandas / scipy / scikit-learn / natsort / treedata / tqdm.

Keep these files in sync with upstream pycea when the linkage algorithm changes:
``/lab/solexa_weissman/wcolgan/pycea/src/pycea/{tl/ancestral_linkage.py,tl/tree_distance.py,
tl/_metrics.py,tl/_aggregators.py,tl/_utils.py,utils.py}``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from .ancestral_linkage import ancestral_linkage

__all__ = ["ancestral_linkage", "cluster_order"]


def cluster_order(matrix: pd.DataFrame, method: str = "average", negate: bool = False) -> list[int]:
    """Optimal leaf order for a square matrix via SciPy hierarchical clustering.

    Reimplements ``pycea.pl.plot_ancestral_linkage._cluster_order`` (scipy only, no
    matplotlib). Clustering needs a distance (larger = less related). When ``negate`` is
    True the matrix holds similarities, so it is negated via ``max - value``; otherwise it
    already holds dissimilarities and is shifted to be non-negative. The result is
    symmetrized, condensed with :func:`scipy.spatial.distance.squareform`, then clustered
    and reordered with :func:`scipy.cluster.hierarchy.optimal_leaf_ordering`.
    """
    arr = matrix.fillna(0).to_numpy(dtype=float)
    if arr.shape[0] < 3:
        return list(range(arr.shape[0]))
    dist = (float(np.nanmax(arr)) - arr) if negate else (arr - float(np.nanmin(arr)))
    dist = (dist + dist.T) / 2  # enforce exact symmetry required by squareform
    np.fill_diagonal(dist, 0.0)
    condensed = ssd.squareform(dist, checks=False)
    linkage = sch.linkage(condensed, method=method)
    linkage = sch.optimal_leaf_ordering(linkage, condensed)
    return list(sch.leaves_list(linkage))
