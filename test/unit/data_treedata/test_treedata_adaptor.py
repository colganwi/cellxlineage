import struct
import unittest

import numpy as np

from server.common.config.app_config import AppConfig
from server.common.fbs.matrix import decode_matrix_fbs
from server.common.utils.data_locator import DataLocator
from server.data_treedata.treedata_adaptor import TreedataAdaptor
from test import PROJECT_ROOT

EXAMPLE = f"{PROJECT_ROOT}/dev/example.h5td"


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
        n_leaves = sum(
            sum(1 for n in g.nodes if g.out_degree(n) == 0) for g in self.data.data.obst.values()
        )
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


def meta_trees(adaptor):
    return adaptor.get_lineage_default_trees()


if __name__ == "__main__":
    unittest.main()
