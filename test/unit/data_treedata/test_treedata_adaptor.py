import os
import shutil
import struct
import tempfile
import unittest

import networkx as nx
import numpy as np
import pandas as pd
import treedata as td

from server.common.config.app_config import AppConfig
from server.common.fbs.matrix import decode_matrix_fbs
from server.common.utils.data_locator import DataLocator
from server.data_treedata.treedata_adaptor import TreedataAdaptor

# A small synthetic .h5td built at test time (the real dev/example.h5td is a
# gitignored 97MB dataset not available in CI). It mirrors the properties the
# tests rely on: two non-overlapping leaf-aligned trees named "E7.5-R1-C1" /
# "E7.5-R1-C2", numeric "time"/"id" on every node, a "cell_type" categorical with
# two large categories (A, B) and two small ones (C, D < the min_size cutoff), a
# continuous "total_counts" column, and a UMAP embedding.
EXAMPLE = None
_TMPDIR = None


def _build_tree(tree_name, n_levels, leaf_start, uid):
    g = nx.DiGraph()
    root = f"{tree_name}_i{uid[0]}"
    uid[0] += 1
    g.add_node(root, time=0.0, id=float(uid[0]))
    frontier = [(root, 0)]
    while frontier:
        node, level = frontier.pop(0)
        if level == n_levels:
            continue
        for _ in range(2):
            uid[0] += 1
            name = f"{tree_name}_i{uid[0]}"
            g.add_node(name, time=float(level + 1), id=float(uid[0]))
            g.add_edge(node, name)
            frontier.append((name, level + 1))
    leaf_nodes = [n for n in nx.dfs_postorder_nodes(g, root) if g.out_degree(n) == 0]
    mapping = {ln: f"cell{leaf_start + i}" for i, ln in enumerate(leaf_nodes)}
    return nx.relabel_nodes(g, mapping), [f"cell{leaf_start + i}" for i in range(len(leaf_nodes))]


def setUpModule():
    global EXAMPLE, _TMPDIR
    _TMPDIR = tempfile.mkdtemp(prefix="cxl_treedata_test_")
    EXAMPLE = os.path.join(_TMPDIR, "example.h5td")
    uid = [0]
    g1, leaves1 = _build_tree("E7.5-R1-C1", 6, 0, uid)
    g2, leaves2 = _build_tree("E7.5-R1-C2", 6, len(leaves1), uid)
    all_leaves = leaves1 + leaves2
    n = len(all_leaves)
    cats = ["A"] * 50 + ["B"] * 50 + ["C"] * 15 + ["D"] * 13
    rng = np.random.RandomState(0)
    obs = pd.DataFrame(
        {"cell_type": pd.Categorical(cats), "total_counts": rng.rand(n).astype("float64")},
        index=pd.Index(all_leaves),
    )
    tdata = td.TreeData(
        X=rng.rand(n, 5).astype("float32"),
        obs=obs,
        var=pd.DataFrame(index=[f"g{i}" for i in range(5)]),
        obsm={"X_umap": rng.rand(n, 2).astype("float32")},
        obst={"E7.5-R1-C1": g1, "E7.5-R1-C2": g2},
        alignment="leaves",
    )
    tdata.write_h5td(EXAMPLE)


def tearDownModule():
    if _TMPDIR:
        shutil.rmtree(_TMPDIR, ignore_errors=True)


def unframe_matrices(fbs):
    """Inverse of TreedataAdaptor._frame_matrices: [count][len][bytes]..."""
    (count,) = struct.unpack_from("<I", fbs, 0)
    offset = 4
    out = []
    for _ in range(count):
        (length,) = struct.unpack_from("<I", fbs, offset)
        offset += 4
        out.append(decode_matrix_fbs(fbs[offset : offset + length]))
        offset += length
    return out


class TreedataAdaptorLineageTest(unittest.TestCase):
    def setUp(self):
        self.data_file = DataLocator(EXAMPLE)
        config = AppConfig()
        config.update_server_config(single_dataset__datapath=self.data_file.path)
        config.update_server_config(app__flask_secret_key="secret")
        config.complete_config()
        self.data = TreedataAdaptor(self.data_file, config)

    def test_lineage_names(self):
        self.assertEqual(self.data.get_lineage_names(), ["E7.5-R1-C1", "E7.5-R1-C2"])

    def test_lineage_meta(self):
        meta = self.data.get_lineage_meta()
        self.assertEqual(meta["names"], ["E7.5-R1-C1", "E7.5-R1-C2"])
        # 'depth' is always offered first (computed topologically when not
        # stored). 'time' and 'id' are numeric on every node. 'time' is
        # preferred as the default when available.
        self.assertEqual(meta["depthKeys"][0], "depth")
        self.assertIn("time", meta["depthKeys"])
        self.assertIn("id", meta["depthKeys"])
        self.assertEqual(meta["defaultDepthKey"], "time")
        self.assertEqual(meta["alignment"], "leaves")
        # Non-overlapping trees → both selected by default.
        self.assertEqual(meta["defaultTrees"], ["E7.5-R1-C1", "E7.5-R1-C2"])
        self.assertFalse(meta["hasOverlap"])

    def test_lineage_fbs_shapes(self):
        fbs = self.data.lineage_to_fbs_matrix(meta_trees(self.data), "depth")
        mats = unframe_matrices(fbs)
        # alignment == "leaves" → branches + leaves matrices only.
        self.assertEqual(len(mats), 2)
        branches, leaves = mats
        self.assertEqual(list(branches.columns), ["x0", "y0", "x1", "y1"])
        self.assertEqual(list(leaves.columns), ["y", "obs"])

        # Total leaves == sum of leaves across both trees; obs indices valid.
        n_leaves = sum(sum(1 for n in g.nodes if g.out_degree(n) == 0) for g in self.data.data.obst.values())
        self.assertEqual(len(leaves), n_leaves)
        self.assertTrue((leaves["obs"].to_numpy() >= 0).all())
        self.assertEqual(len(np.unique(leaves["obs"].to_numpy())), n_leaves)

        # Each edge → 2 segments.
        n_edges = sum(g.number_of_edges() for g in self.data.data.obst.values())
        self.assertEqual(len(branches), 2 * n_edges)

    def test_single_tree_selection(self):
        fbs = self.data.lineage_to_fbs_matrix(["E7.5-R1-C1"], "depth")
        _, leaves = unframe_matrices(fbs)
        tree = self.data.data.obst["E7.5-R1-C1"]
        n_leaves = sum(1 for n in tree.nodes if tree.out_degree(n) == 0)
        self.assertEqual(len(leaves), n_leaves)

    def test_subset_induced_subtree(self):
        # Simulate an active subset: keep three leaves of one tree and verify
        # the server returns just their induced subtree, with obs indices
        # remapped into the subset (view) coordinate space.
        tree_name = "E7.5-R1-C1"
        tree = self.data.data.obst[tree_name]
        obs_index = self.data.get_obs_index()
        leaf_names = [n for n in tree.nodes if tree.out_degree(n) == 0]
        keep_leaf_names = leaf_names[:3]
        keep_obs = sorted(int(p) for p in obs_index.get_indexer(keep_leaf_names))

        fbs = self.data.lineage_to_fbs_matrix([tree_name], "depth", keep_obs=keep_obs)
        branches, leaves = unframe_matrices(fbs)

        # Only the selected leaves survive.
        self.assertEqual(len(leaves), 3)
        # obs indices are positions within the subset, not the full obs index.
        self.assertEqual(sorted(leaves["obs"].to_numpy().tolist()), [0, 1, 2])

        # Branches match the induced subtree (selected leaves + their ancestors).
        pruned = self.data._prune_tree(tree, set(keep_leaf_names))
        self.assertEqual(len(branches), 2 * pruned.number_of_edges())

    def test_subset_empty_when_no_leaves_kept(self):
        # keep_obs that matches no leaves of the selected tree → empty layout.
        fbs = self.data.lineage_to_fbs_matrix(["E7.5-R1-C1"], "depth", keep_obs=[])
        branches, leaves = unframe_matrices(fbs)
        self.assertEqual(len(leaves), 0)
        self.assertEqual(len(branches), 0)

    def test_full_layout_is_cached(self):
        # Full-tree (no-subset) layouts are cached by (trees, depth_key) and the
        # cached bytes are byte-identical to a fresh computation.
        self.data._lineage_layout_cache.clear()
        first = self.data.lineage_to_fbs_matrix(["E7.5-R1-C1"], "depth")
        self.assertEqual(len(self.data._lineage_layout_cache), 1)
        second = self.data.lineage_to_fbs_matrix(["E7.5-R1-C1"], "depth")
        self.assertIs(first, second)  # served from cache, not recomputed
        self.assertEqual(first, second)
        # A different depth key is a distinct cache entry.
        self.data.lineage_to_fbs_matrix(["E7.5-R1-C1"], "time")
        self.assertEqual(len(self.data._lineage_layout_cache), 2)

    def test_subset_layout_is_not_cached(self):
        # Subset (keep_obs) results vary per selection and must not be cached.
        self.data._lineage_layout_cache.clear()
        self.data.lineage_to_fbs_matrix(["E7.5-R1-C1"], "depth", keep_obs=[0, 1, 2])
        self.assertEqual(len(self.data._lineage_layout_cache), 0)


class TreedataAdaptorAncestralLinkageTest(unittest.TestCase):
    def setUp(self):
        self.data_file = DataLocator(EXAMPLE)
        config = AppConfig()
        config.update_server_config(single_dataset__datapath=self.data_file.path)
        config.update_server_config(app__flask_secret_key="secret")
        config.complete_config()
        self.data = TreedataAdaptor(self.data_file, config)

    def _snapshot(self):
        return (list(self.data.data.obs.columns), sorted(self.data.data.uns.keys()))

    def test_selected_shape_and_no_mutation(self):
        before = self._snapshot()
        trees = meta_trees(self.data)
        selected = list(range(0, 80, 2))  # a proper subset of obs positions
        result = self.data.ancestral_linkage_selected(selected, trees, "time")

        values = result["values"]
        # One value per cell, in full obs order.
        self.assertEqual(len(values), self.data.get_obs_index().shape[0])
        # Some cells are leaves in a tree and get a finite score; NaN -> None.
        self.assertTrue(any(v is not None for v in values))
        self.assertTrue(all(v is None or isinstance(v, float) for v in values))
        # self.data is left untouched (no temp obs column or uns key leaks).
        self.assertEqual(self._snapshot(), before)

    def test_selected_target_cells_are_maximum(self):
        # Selected (target) cells are pinned to the maximum value so they read as
        # the hottest cells after negation.
        trees = meta_trees(self.data)
        selected = list(range(0, 80, 2))
        values = self.data.ancestral_linkage_selected(selected, trees, "time")["values"]
        finite = [v for v in values if v is not None]
        self.assertTrue(finite)
        mx = max(finite)
        sel_finite = [values[i] for i in selected if values[i] is not None]
        self.assertTrue(sel_finite)
        self.assertTrue(all(abs(v - mx) < 1e-6 for v in sel_finite))

    def test_selected_requires_selection(self):
        with self.assertRaises(Exception):
            self.data.ancestral_linkage_selected([], meta_trees(self.data), "time")

    def test_selected_subset_prunes_to_view(self):
        # Under an active subset (keep_obs = one tree's cells), the trees are pruned
        # to that view: cells outside it are null, and the kept cells' scores match
        # the full computation (target linkage is within-tree).
        trees = meta_trees(self.data)
        obs_index = self.data.get_obs_index()
        tree = self.data.data.obst["E7.5-R1-C1"]
        t1_names = [n for n in tree.nodes if tree.out_degree(n) == 0]
        t1_pos = sorted(int(obs_index.get_loc(n)) for n in t1_names)
        target = t1_pos[:20]

        np.random.seed(3)
        full = self.data.ancestral_linkage_selected(target, trees, "time")["values"]
        np.random.seed(3)
        sub = self.data.ancestral_linkage_selected(target, trees, "time", keep_obs=t1_pos)["values"]

        t1_set = set(t1_pos)
        # cells outside the kept tree are null in the subset result
        self.assertTrue(all(sub[p] is None for p in range(len(obs_index)) if p not in t1_set))
        # kept cells' scores match the full computation
        for p in t1_pos:
            if full[p] is None:
                self.assertIsNone(sub[p])
            else:
                self.assertAlmostEqual(full[p], sub[p], places=6)

    def test_pairwise_matrix_square_and_no_mutation(self):
        before = self._snapshot()
        trees = meta_trees(self.data)
        result = self.data.ancestral_linkage_pairwise("cell_type", None, trees, "time")

        labels = result["labels"]
        matrix = result["matrix"]
        self.assertGreaterEqual(len(labels), 2)
        self.assertEqual(len(matrix), len(labels))
        self.assertTrue(all(len(row) == len(labels) for row in matrix))
        # Diverging scale is symmetric about 0.
        self.assertAlmostEqual(result["vmin"], -result["vmax"])
        self.assertEqual(self._snapshot(), before)

    def test_pairwise_min_size_drops_small_categories(self):
        # cell_type has small categories (C=15, D=13, both < the min_size cutoff)
        # that must be excluded, leaving the two large ones (A, B).
        trees = meta_trees(self.data)
        result = self.data.ancestral_linkage_pairwise("cell_type", None, trees, "time")
        labels = set(result["labels"])
        self.assertFalse({"C", "D"} & labels)
        self.assertEqual(labels, {"A", "B"})

    def test_pairwise_subset_restricts_categories(self):
        trees = meta_trees(self.data)
        selected = list(range(0, self.data.get_obs_index().shape[0]))
        result = self.data.ancestral_linkage_pairwise("cell_type", selected, trees, "time")
        self.assertGreaterEqual(len(result["labels"]), 2)

    def test_pairwise_rejects_non_categorical(self):
        # total_counts is a continuous (float) obs column.
        with self.assertRaises(Exception):
            self.data.ancestral_linkage_pairwise("total_counts", None, meta_trees(self.data), "time")


def meta_trees(adaptor):
    return adaptor.get_lineage_default_trees()


if __name__ == "__main__":
    unittest.main()
