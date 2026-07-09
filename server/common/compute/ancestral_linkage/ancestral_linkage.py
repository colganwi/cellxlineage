from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable

import networkx as nx
import numpy as np
import pandas as pd

from .utils import check_tree_has_key, get_leaves, get_topological_order


def _set_random_state(random_state: int | None) -> None:
    """Seed the RNGs used by the permutation for reproducibility (no-op if None)."""
    if random_state is not None:
        random.seed(random_state)
        np.random.seed(random_state)


# ── internal helpers ──────────────────────────────────────────────────────────


def _dijkstra_min_scores(
    tree: nx.DiGraph,
    source_leaves: list,
    target_cats: list,
    cat_to_leaves_in_tree: dict,
    depth_key: str,
) -> dict:
    r"""Per-leaf minimum path distance to each target category via multi-source Dijkstra.

    Uses ``|depth[u] - depth[v]|`` as edge weights, which sums along any root-to-leaf
    path to the correct tree path distance :math:`d_i + d_j - 2\\,d_{LCA(i,j)}` on any
    tree (ultrametric or not).  Self-distances are zero, so a source leaf in the target
    category scores 0 (its own closest target is itself).
    """
    G = nx.Graph(tree)

    def _weight(u, v, _):
        return abs(G.nodes[u][depth_key] - G.nodes[v][depth_key])

    scores: dict = {leaf: {} for leaf in source_leaves}

    for cat in target_cats:
        target_leaves = cat_to_leaves_in_tree.get(cat, [])
        if not target_leaves:
            continue

        dists = nx.multi_source_dijkstra_path_length(G, target_leaves, weight=_weight)
        for leaf in source_leaves:
            if leaf in dists:
                scores[leaf][cat] = dists[leaf]

    return scores


def _max_lca_depth_scores(
    tree: nx.DiGraph,
    source_leaves: list,
    target_cats: list,
    cat_to_leaves_in_tree: dict,
    depth_key: str,
) -> dict:
    r"""Per-leaf maximum LCA depth to each target category (exact for any tree).

    This is the shared "closest relative" primitive for both closest-target aggregates:
    ``lca`` + ``max`` uses it directly, and on an ultrametric tree ``path`` + ``min`` is
    the affine transform ``2D - 2 * score`` of it (see :func:`_compute_scores`).

    For a source leaf ``i``, the deepest (most recent) common ancestor it shares with
    *any* leaf ``j`` of category ``c`` is the deepest ancestor of ``i`` whose subtree
    still contains a ``c`` leaf.  Its depth is therefore :math:`\\max_j d_{LCA(i, j)}`.
    Unlike the path-distance Dijkstra shortcut, this holds regardless of whether the
    tree is ultrametric, so it is exact on non-ultrametric trees too.

    The subtree category membership is built with a single bottom-up pass (reversed
    topological order visits every child before its parent); each source leaf then
    walks up its ancestor chain, recording the first — hence deepest — ancestor that
    covers each still-unresolved category.  A leaf is its own subtree, so a source leaf
    belonging to ``c`` scores its own depth (the maximal possible LCA depth).
    """
    # Read adjacency / node attributes straight from the raw dicts (succ = children,
    # pred = parents, node = attrs) instead of the networkx accessor methods, which
    # add per-call overhead that dominates on large trees. Results are identical.
    succ = tree._succ
    pred = tree._pred
    node_attrs = tree._node

    # Map each target leaf to its category (only target categories are relevant).
    leaf_cat: dict = {}
    for cat in target_cats:
        for leaf in cat_to_leaves_in_tree.get(cat, []):
            leaf_cat[leaf] = cat

    # Bottom-up: set of target categories present in each node's subtree.
    subtree_cats: dict = {}
    for node in reversed(get_topological_order(tree)):
        cats: set = set()
        for child in succ[node]:
            cats |= subtree_cats[child]
        own = leaf_cat.get(node)
        if own is not None:
            cats.add(own)
        subtree_cats[node] = cats

    # Walk up from each source leaf; the first ancestor whose subtree contains a
    # category (deepest, since we ascend) gives the maximum LCA depth to that category.
    scores: dict = {leaf: {} for leaf in source_leaves}
    for leaf in source_leaves:
        remaining = set(target_cats)
        node = leaf
        while node is not None and remaining:
            present = subtree_cats[node] & remaining
            if present:
                depth = node_attrs[node][depth_key]
                for cat in present:
                    scores[leaf][cat] = depth
                remaining -= present
            parents = pred[node]
            node = next(iter(parents)) if parents else None

    return scores


def _compute_scores(
    trees: dict,
    leaf_to_cat: dict,
    target_cats: list,
    aggregate: str | Callable,
    metric: str,
    depth_key: str,
) -> dict:
    """Route to the appropriate per-leaf scoring method and return leaf → {cat → score}.

    Only the exact "closest target" aggregates cellxlineage uses are supported:
    ``min`` + ``path`` (walk-up on ultrametric trees, else Dijkstra) and
    ``max`` + ``lca`` (subtree walk-up). Other aggregates required an all-pairs
    distance matrix over a TreeData and are not supported in this trees-only build.
    """
    # Build per-tree leaf / category maps
    source_leaves_by_tree: dict = {}
    cat_to_leaves_by_tree: dict = {}
    for tree_key, t in trees.items():
        t_leaves = [l for l in get_leaves(t) if l in leaf_to_cat]
        source_leaves_by_tree[tree_key] = t_leaves
        cat_to_leaves_by_tree[tree_key] = defaultdict(list)
        for l in t_leaves:
            cat_to_leaves_by_tree[tree_key][leaf_to_cat[l]].append(l)

    # Choose strategy for the "closest target" aggregates, computed exactly and without an
    # all-pairs distance matrix:
    #   - max+lca  : deepest ancestor whose subtree covers each category (subtree walk-up).
    #     Exact on any tree and faster than Dijkstra (one bottom-up pass regardless of the
    #     category count), so it is used for all trees.
    #   - min+path : on an ultrametric tree (leaf depth D) path = 2D - 2*lca, so min path =
    #     2D - 2*(max lca): reuse the fast walk-up and apply the affine transform.  On a
    #     non-ultrametric tree leaves differ in depth and this identity fails, so fall back
    #     to multi-source Dijkstra on |Δdepth| edge weights.
    is_named = isinstance(aggregate, str)
    use_path_min = is_named and aggregate == "min" and metric == "path"
    use_lca_max = is_named and aggregate == "max" and metric == "lca"

    if use_path_min or use_lca_max:
        all_scores: dict = {}
        for tree_key, t in trees.items():
            t_leaves = source_leaves_by_tree[tree_key]
            ctl = cat_to_leaves_by_tree[tree_key]
            depths = [t.nodes[l][depth_key] for l in t_leaves]
            ultrametric = (not depths) or np.allclose(depths, depths[0])
            if use_lca_max:
                tree_scores = _max_lca_depth_scores(t, t_leaves, target_cats, ctl, depth_key)
            elif ultrametric:
                # min path = 2D - 2*(max lca); reuse the walk-up and transform.
                D = depths[0]
                lca_scores = _max_lca_depth_scores(t, t_leaves, target_cats, ctl, depth_key)
                tree_scores = {leaf: {c: 2 * D - 2 * v for c, v in s.items()} for leaf, s in lca_scores.items()}
            else:
                tree_scores = _dijkstra_min_scores(t, t_leaves, target_cats, ctl, depth_key)
            all_scores.update(tree_scores)
        return all_scores

    raise ValueError(
        f"Unsupported aggregate/metric combination ({aggregate!r}, {metric!r}); "
        "this trees-only build supports 'min'+'path' and 'max'+'lca'."
    )


def _scores_to_linkage_matrix(
    all_scores: dict,
    all_cats: list,
    cat_to_leaves: dict,
) -> pd.DataFrame:
    """Aggregate per-leaf scores to a (source category × target category) DataFrame."""
    matrix: dict = {}
    for src_cat in all_cats:
        row: dict = {}
        src_leaves = [l for l in cat_to_leaves.get(src_cat, []) if l in all_scores]
        for tgt_cat in all_cats:
            values = [all_scores[l][tgt_cat] for l in src_leaves if tgt_cat in all_scores.get(l, {})]
            row[tgt_cat] = float(np.mean(values)) if values else np.nan
        matrix[src_cat] = row
    return pd.DataFrame(matrix, dtype=float).T  # index=src, columns=tgt


def _symmetrize_matrix(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Symmetrize a square DataFrame in-place."""
    arr = df.values.astype(float)
    arr_T = arr.T
    if mode == "mean":
        sym = (arr + arr_T) / 2
    elif mode == "max":
        sym = np.maximum(arr, arr_T)
    elif mode == "min":
        sym = np.minimum(arr, arr_T)
    else:
        raise ValueError(f"symmetrize must be 'mean', 'max', 'min', or None; got '{mode}'.")
    return pd.DataFrame(sym, index=df.index, columns=df.columns)


# ── permutation workers (non-target null) ──────────────────────────────────────
# A worker runs one label permutation, reading its shared inputs from the module
# global set just before it is called. (Upstream pycea dispatches these across a
# fork pool; cellxlineage runs a single permutation serially — see _run_parallel.)

_PERM_NON_TARGET_PAIRWISE_DATA: dict = {}
_PERM_SINGLE_NON_TARGET_DATA: dict = {}


def _perm_pairwise_non_target_worker(seed: int) -> np.ndarray:
    """Non-target pairwise permutation using precomputed fixed scores.

    Target leaves never move, so scores to each target set are constant across
    permutations.  Each permutation only shuffles the non-target source labels and
    re-averages the precomputed per-leaf scores — no tree computation required.

    The per-category means are computed with :func:`numpy.bincount` (group-sum and
    group-count over integer category codes) instead of Python loops.  Shuffling the
    integer code array with the same per-column RNG (``default_rng([seed, j])``) yields
    the identical label assignment as shuffling the category labels, so the result is
    unchanged.  Returns a float array of shape ``(n_src, n_tgt)`` aligned to
    ``d["index"] × d["columns"]``.
    """
    d = _PERM_NON_TARGET_PAIRWISE_DATA
    n_src = d["n_src"]
    nt_codes = d["nt_codes"]
    nt_scores = d["nt_scores"]
    nt_finite = d["nt_finite"]
    tgt_code = d["tgt_code"]
    tgt_diag = d["tgt_diag"]
    result = np.full((n_src, len(nt_codes)), np.nan)
    for j in range(len(nt_codes)):
        rng = np.random.default_rng([seed, j])
        perm_codes = rng.permutation(nt_codes[j])
        finite = nt_finite[j]
        codes = perm_codes[finite]
        sums = np.bincount(codes, weights=nt_scores[j][finite], minlength=n_src)
        counts = np.bincount(codes, minlength=n_src)
        with np.errstate(invalid="ignore", divide="ignore"):
            means = np.where(counts > 0, sums / counts, np.nan)
        means[tgt_code[j]] = tgt_diag[j]  # target leaves are fixed → constant diagonal
        result[:, j] = means
    return result


def _perm_single_non_target_worker(seed: int) -> dict:
    """Non-target single-target permutation using precomputed fixed scores.

    Target leaves never move, so their distances to the target set are constant.
    Each permutation only shuffles non-target source labels and re-averages.
    """
    d = _PERM_SINGLE_NON_TARGET_DATA
    rng = np.random.default_rng(seed)
    perm_cats = rng.permutation(d["nt_cats"])
    perm_cat_to_leaves: dict = defaultdict(list)
    for l in d["target_leaves"]:
        perm_cat_to_leaves[d["target"]].append(l)
    for l, c in zip(d["nt_leaves"], perm_cats, strict=True):
        perm_cat_to_leaves[c].append(l)
    score_map = d["fixed_scores"]
    result: dict = {}
    for cat in d["all_cats"]:
        vals = [score_map[l] for l in perm_cat_to_leaves.get(cat, []) if l in score_map and not np.isnan(score_map[l])]
        result[cat] = float(np.mean(vals)) if vals else np.nan
    return result


def _run_parallel(worker_fn: Callable, seeds: np.ndarray, n_threads: int | None = None) -> list:
    """Run *worker_fn(seed)* for each seed, serially.

    cellxlineage always runs a single normalization permutation (``test=None``), so
    upstream pycea's fork-based parallel path and tqdm progress bar provide no
    benefit here and are omitted; ``n_threads`` is accepted but ignored.
    """
    return [worker_fn(seed) for seed in seeds]


def _compute_p_values(
    null_array: np.ndarray,
    obs_values: np.ndarray,
    null_mean: np.ndarray,
    metric: str,
    alternative: str,
) -> np.ndarray:
    """Compute permutation p-values given the null distribution and observed values."""
    if alternative == "two-sided":
        deviation = np.abs(null_array - null_mean[np.newaxis])
        obs_deviation = np.abs(obs_values - null_mean)
        return np.nanmean(deviation >= obs_deviation[np.newaxis], axis=0)
    # One-tailed in the "more related" direction
    if metric == "lca":
        return np.nanmean(null_array >= obs_values[np.newaxis], axis=0)
    else:
        return np.nanmean(null_array <= obs_values[np.newaxis], axis=0)


def _run_permutation_test_non_target(
    trees: dict,
    leaf_to_cat: dict,
    all_cats: list,
    observed_df: pd.DataFrame,
    aggregate: str | Callable,
    metric: str,
    depth_key: str,
    n_permutations: int,
    n_threads: int | None,
    alternative: str,
    precomputed_scores: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Non-target permutation test: single batch of ``n_permutations`` workers.

    Scores to each fixed target set are precomputed once (same total Dijkstra work
    as the ``all`` mode).  Each permutation then only shuffles source-category labels
    and re-averages precomputed scores — no tree computation inside the permutation loop.

    ``precomputed_scores`` (optional): the ``leaf → {cat → score}`` map already
    computed for the observed matrix. Per-target scores are read from it instead of
    recomputing ``_compute_scores`` once per column — identical values, but avoids
    ``len(cols)`` redundant full-tree passes.
    """
    cat_to_leaves: dict = defaultdict(list)
    for l, c in leaf_to_cat.items():
        cat_to_leaves[c].append(l)
    all_leaves = list(leaf_to_cat.keys())
    cols = observed_df.columns.tolist()
    idx = observed_df.index.tolist()
    code_of = {cat: i for i, cat in enumerate(idx)}  # source category → row index

    # Precompute, once per fixed target column: the non-target leaves' category codes and
    # scores (arrays), a finite-score mask, and the constant target-category diagonal.
    # Each permutation then only shuffles the codes and re-averages via bincount.
    nt_codes: list = []
    nt_scores: list = []
    nt_finite: list = []
    tgt_code: list = []
    tgt_diag: list = []
    for target_cat in cols:
        t_leaves = cat_to_leaves.get(target_cat, [])
        scores = (
            precomputed_scores
            if precomputed_scores is not None
            else _compute_scores(trees, leaf_to_cat, [target_cat], aggregate, metric, depth_key)
        )
        score_map = {leaf: s.get(target_cat, np.nan) for leaf, s in scores.items()}
        t_set = set(t_leaves)
        nt = [l for l in all_leaves if l not in t_set]
        nt_codes.append(np.array([code_of[leaf_to_cat[l]] for l in nt], dtype=np.intp))
        s = np.array([score_map.get(l, np.nan) for l in nt], dtype=float)
        nt_scores.append(s)
        nt_finite.append(np.isfinite(s))
        tgt_code.append(code_of[target_cat])
        t_vals = [score_map[l] for l in t_leaves if l in score_map and not np.isnan(score_map[l])]
        tgt_diag.append(float(np.mean(t_vals)) if t_vals else np.nan)

    _PERM_NON_TARGET_PAIRWISE_DATA.clear()
    _PERM_NON_TARGET_PAIRWISE_DATA.update(
        {
            "nt_codes": nt_codes,
            "nt_scores": nt_scores,
            "nt_finite": nt_finite,
            "tgt_code": tgt_code,
            "tgt_diag": tgt_diag,
            "n_src": len(idx),
        }
    )

    perm_seeds = np.random.randint(0, 2**31, size=n_permutations)
    null_matrices = _run_parallel(_perm_pairwise_non_target_worker, perm_seeds, n_threads)

    null_array = np.array(null_matrices)  # (n_permutations, n_src, n_tgt)
    null_mean = np.nanmean(null_array, axis=0)
    null_std = np.nanstd(null_array, axis=0)
    obs_values = observed_df.values.astype(float)

    sign = 1.0 if metric == "lca" else -1.0
    z_scores = sign * (obs_values - null_mean) / (null_std + 1e-10)
    p_values = _compute_p_values(null_array, obs_values, null_mean, metric, alternative)

    return (
        pd.DataFrame(z_scores, index=observed_df.index, columns=observed_df.columns),
        pd.DataFrame(p_values, index=observed_df.index, columns=observed_df.columns),
        pd.DataFrame(null_mean, index=observed_df.index, columns=observed_df.columns),
    )


# ── public entry points ─────────────────────────────────────────────────────────
# cellxlineage drives ancestral linkage directly from the networkx trees plus a
# leaf-name → category mapping, so it never constructs a TreeData (avoids copying
# the trees and the counts matrix). These reproduce pycea.tl.ancestral_linkage's
# metric="path", normalize=True, non_target path exactly. Subsetting is done by the
# caller as the induced subtree of the selected leaves.


def _build_leaf_to_cat(trees: dict, name_to_cat: dict) -> dict:
    """leaf name → str(category) for every leaf present (non-null) in name_to_cat."""
    leaf_to_cat: dict = {}
    for t in trees.values():
        for leaf in get_leaves(t):
            if leaf in name_to_cat:
                cat = name_to_cat[leaf]
                if pd.notna(cat):
                    leaf_to_cat[leaf] = str(cat)
    return leaf_to_cat


def _single_target_null_mean(
    leaf_to_cat: dict, cat_to_leaves: dict, all_cats: list, target: str, score_map: dict, n_perms: int = 1
) -> dict:
    """Per-category permuted mean for single-target normalization (non_target mode);
    the module-level equivalent of ancestral_linkage's internal _run_single_perm."""
    all_leaves = list(leaf_to_cat.keys())
    perm_seeds = np.random.randint(0, 2**31, size=n_perms)
    t_lv = cat_to_leaves[target]
    t_set = set(t_lv)
    nt_lv = [l for l in all_leaves if l not in t_set]
    _PERM_SINGLE_NON_TARGET_DATA.clear()
    _PERM_SINGLE_NON_TARGET_DATA.update(
        {
            "fixed_scores": score_map,
            "target_leaves": list(t_lv),
            "nt_leaves": nt_lv,
            "nt_cats": [leaf_to_cat[l] for l in nt_lv],
            "target": target,
            "all_cats": all_cats,
        }
    )
    null_results = _run_parallel(_perm_single_non_target_worker, perm_seeds, None)
    null_cat: dict = defaultdict(list)
    for perm_result in null_results:
        for cat in all_cats:
            null_cat[cat].append(perm_result[cat])
    cat_null_mean: dict = {}
    for cat in all_cats:
        vals = np.array([v for v in null_cat[cat] if not np.isnan(v)], dtype=float)
        cat_null_mean[cat] = float(np.mean(vals)) if len(vals) > 0 else np.nan
    return cat_null_mean


def linkage_selected_scores(
    trees: dict,
    name_to_cat: dict,
    target: str,
    depth_key: str,
    metric: str = "path",
    random_state: int | None = None,
) -> dict:
    """Target-mode ancestral linkage on networkx trees (no TreeData).

    Returns ``{leaf_name: score}`` — the per-cell tree distance to the nearest cell
    of ``target``, normalized by the permuted per-category mean (may be NaN for
    leaves without a category). Equivalent to
    ``pycea.tl.ancestral_linkage(target=..., metric="path", normalize=True)``.
    """
    _set_random_state(random_state)
    for t in trees.values():
        check_tree_has_key(t, depth_key)
    leaf_to_cat = _build_leaf_to_cat(trees, name_to_cat)
    all_cats = sorted(set(leaf_to_cat.values()))
    if target not in all_cats:
        raise ValueError(f"target {target!r} is not present among the tree leaves.")
    cat_to_leaves: dict = defaultdict(list)
    for l, c in leaf_to_cat.items():
        cat_to_leaves[c].append(l)

    single_agg = "max" if metric == "lca" else "min"
    all_scores = _compute_scores(trees, leaf_to_cat, [target], single_agg, metric, depth_key)
    score_map = {leaf: scores.get(target, np.nan) for leaf, scores in all_scores.items()}
    cat_null_mean = _single_target_null_mean(leaf_to_cat, cat_to_leaves, all_cats, target, score_map)
    return {
        leaf: (score - cat_null_mean.get(leaf_to_cat.get(leaf), np.nan)) if not np.isnan(score) else np.nan
        for leaf, score in score_map.items()
    }


def linkage_pairwise_matrix(
    trees: dict,
    name_to_cat: dict,
    depth_key: str,
    metric: str = "path",
    aggregate: str | None = None,
    symmetrize: str = "mean",
    min_size: int = 1,
    random_state: int | None = None,
) -> pd.DataFrame:
    """Pairwise ancestral linkage on networkx trees (no TreeData).

    Returns the normalized, symmetrized category × category matrix
    (``observed - permuted_mean``). Equivalent to
    ``pycea.tl.ancestral_linkage(metric="path", normalize=True, symmetrize=...)``.
    Categories with fewer than ``min_size`` leaves are dropped.
    """
    _set_random_state(random_state)
    if aggregate is None:
        aggregate = "max" if metric == "lca" else "min"
    for t in trees.values():
        check_tree_has_key(t, depth_key)
    leaf_to_cat = _build_leaf_to_cat(trees, name_to_cat)
    all_cats = sorted(set(leaf_to_cat.values()))
    cat_to_leaves: dict = defaultdict(list)
    for l, c in leaf_to_cat.items():
        cat_to_leaves[c].append(l)

    if min_size > 1:
        kept = {c for c in all_cats if len(cat_to_leaves[c]) >= min_size}
        leaf_to_cat = {l: c for l, c in leaf_to_cat.items() if c in kept}
        all_cats = sorted(kept)
        cat_to_leaves = defaultdict(list)
        for l, c in leaf_to_cat.items():
            cat_to_leaves[c].append(l)

    if len(all_cats) < 1:
        return pd.DataFrame()

    all_scores = _compute_scores(trees, leaf_to_cat, all_cats, aggregate, metric, depth_key)
    linkage_df = _scores_to_linkage_matrix(all_scores, all_cats, cat_to_leaves)
    _z, _p, null_mean_df = _run_permutation_test_non_target(
        trees,
        leaf_to_cat,
        all_cats,
        linkage_df,
        aggregate,
        metric,
        depth_key,
        1,
        None,
        "one-sided",
        precomputed_scores=all_scores,
    )
    output_df = linkage_df - null_mean_df
    if symmetrize:
        output_df = _symmetrize_matrix(output_df, symmetrize)
    return output_df
