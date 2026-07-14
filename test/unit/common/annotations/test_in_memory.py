import unittest

import pandas as pd
from flask import Flask, session

from server.app.session import CXGUID, reset_user_session
from server.common.annotations.in_memory import AnnotationsInMemory
from server.common.errors import ObsoleteRequest


class _FakeAdaptor:
    """Minimal stand-in: AnnotationsInMemory only needs get_location (for the
    display idhash) and check_new_gene_sets (a validation pass-through)."""

    def get_location(self):
        return "mem://test.h5td"

    def check_new_gene_sets(self, gene_sets, context=None):
        return gene_sets


def _cat(values):
    return pd.DataFrame({"cat": pd.Series(values, dtype="category")})


class InMemoryAnnotationsTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SECRET_KEY"] = "test"
        self.adaptor = _FakeAdaptor()
        self.anno = AnnotationsInMemory({"user-annotations": True, "genesets-save": True})

    @staticmethod
    def _set_user(uid):
        session[CXGUID] = uid

    def test_labels_roundtrip_within_session(self):
        with self.app.test_request_context():
            self._set_user("userA")
            self.assertTrue(self.anno.read_labels(self.adaptor).empty)
            self.anno.write_labels(_cat(["a", "b"]), self.adaptor)
            got = self.anno.read_labels(self.adaptor)
            self.assertEqual(list(got.columns), ["cat"])
            self.assertEqual(len(got), 2)

    def test_sessions_are_isolated(self):
        with self.app.test_request_context():
            self._set_user("userA")
            self.anno.write_labels(_cat(["a"]), self.adaptor)
            # a different user sees nothing
            self._set_user("userB")
            self.assertTrue(self.anno.read_labels(self.adaptor).empty)
            # userA still has its own labels
            self._set_user("userA")
            self.assertFalse(self.anno.read_labels(self.adaptor).empty)

    def test_get_schema_reflects_written_columns(self):
        with self.app.test_request_context():
            self._set_user("userA")
            self.assertEqual(self.anno.get_schema(self.adaptor), [])
            self.anno.write_labels(_cat(["a", "b"]), self.adaptor)
            schema = self.anno.get_schema(self.adaptor)
            self.assertEqual({c["name"] for c in schema}, {"cat"})
            self.assertTrue(all(c["writable"] for c in schema))

    def test_genesets_roundtrip_and_stale_tid(self):
        with self.app.test_request_context():
            self._set_user("userA")
            gs, tid = self.anno.read_gene_sets(self.adaptor)
            self.assertEqual((gs, tid), ({}, 0))
            genesets = {"g1": {"geneset_name": "g1", "genes": []}}
            self.anno.write_gene_sets(genesets, 1, self.adaptor)
            gs, tid = self.anno.read_gene_sets(self.adaptor)
            self.assertIn("g1", gs)
            self.assertEqual(tid, 1)
            # a stale/equal tid is rejected
            with self.assertRaises(ObsoleteRequest):
                self.anno.write_gene_sets(genesets, 1, self.adaptor)

    def test_lru_evicts_oldest_session(self):
        anno = AnnotationsInMemory({"user-annotations": True, "genesets-save": True})
        anno._MAX_SESSIONS = 2
        with self.app.test_request_context():
            for uid in ["u1", "u2", "u3"]:
                self._set_user(uid)
                anno.write_labels(_cat(["x"]), self.adaptor)
            self.assertNotIn("u1", anno._store)
            self.assertEqual(set(anno._store), {"u2", "u3"})

    def test_update_parameters_suppresses_prompt(self):
        with self.app.test_request_context():
            self._set_user("userA")
            params = {}
            self.anno.update_parameters(params, self.adaptor)
            self.assertFalse(params["user_annotation_collection_name_enabled"])
            self.assertTrue(params["annotations-data-collection-is-read-only"])
            self.assertEqual(params["annotations-data-collection-name"], "ephemeral")
            self.assertTrue(params["annotations"])

    def test_reset_user_session_clears_annotations(self):
        with self.app.test_request_context():
            self._set_user("userA")
            self.anno.write_labels(_cat(["x"]), self.adaptor)
            reset_user_session(session)
            self.assertNotIn(CXGUID, session)
            # a fresh id is minted on the next access; it has no stored labels
            self.assertTrue(self.anno.read_labels(self.adaptor).empty)


if __name__ == "__main__":
    unittest.main()
