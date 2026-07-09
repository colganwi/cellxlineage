"""Trees-only ancestral-linkage compute, derived from pycea.tl.ancestral_linkage.

The public entry points — :func:`linkage_pairwise_matrix` and
:func:`linkage_selected_scores` — operate directly on a ``{name: networkx.DiGraph}``
dict plus a ``leaf name → category`` mapping and return plain results. There is no
TreeData: cellxlineage passes its trees by reference (no copy, no counts matrix) and
does subsetting as the induced subtree of the selected leaves (see
``TreedataAdaptor._linkage_trees`` / ``treedata.subset_tree``).

Only the ``metric="path"``, ``aggregate="min"``, ``normalize=True``,
``permutation_mode="non_target"`` path that cellxlineage uses is kept; results are
identical to pycea's ``ancestral_linkage`` for that configuration. Dropped from the
vendored copy vs. upstream: the TreeData-coupled public ``ancestral_linkage`` and its
``by_tree`` / ``test`` / ``permutation_mode='all'`` branches; the all-pairs distance
path (``tree_distance``, scikit-learn); category helpers pulling natsort; and the
tqdm/multiprocessing progress+parallel machinery (a single permutation is run). Needs
only networkx / numpy / pandas / scipy.

Sync source: ``/lab/solexa_weissman/wcolgan/pycea/src/pycea/tl/ancestral_linkage.py``
(+ ``utils.py`` helpers).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from .ancestral_linkage import (
    linkage_pairwise_matrix,
    linkage_selected_scores,
)

__all__ = [
    "linkage_pairwise_matrix",
    "linkage_selected_scores",
    "cluster_order",
]


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
