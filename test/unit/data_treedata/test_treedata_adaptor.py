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
        # 'depth' is always offered (computed topologically when not stored) and
        # is the default. 'time' and 'id' are numeric on every node.
        self.assertEqual(meta["depthKeys"][0], "depth")
        self.assertIn("time", meta["depthKeys"])
        self.assertIn("id", meta["depthKeys"])
        self.assertEqual(meta["defaultDepthKey"], "depth")
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


def meta_trees(adaptor):
    return adaptor.get_lineage_default_trees()


if __name__ == "__main__":
    unittest.main()
