import base64
import re
import threading
from collections import OrderedDict
from hashlib import blake2b

import pandas as pd
from flask import session

from server.app.session import get_user_id
from server.common.annotations.annotations import Annotations
from server.common.errors import ObsoleteRequest


class AnnotationsInMemory(Annotations):
    """Ephemeral, per-session annotations for multi-user hosting.

    Cell labels and gene sets are held in process memory, keyed by the Flask
    session user id (``server.app.session.get_user_id``). Nothing is written to
    disk, there is no collection/filename concept (so the client never shows the
    "User Generated Data Directory" prompt — see ``update_parameters``), and the
    store is dropped when the process exits. Combined with rotating the session
    id on each page (re)load (``server.app.session.reset_user_session``), this
    makes annotations reset on reload and stay isolated between concurrent users.

    The per-session buckets are kept in an LRU-bounded dict so sessions left
    behind by reloads/departures don't accumulate without limit.
    """

    # Maximum number of distinct sessions kept in memory (LRU-evicted). Well
    # above the small concurrent-user counts this hosting mode targets.
    _MAX_SESSIONS = 128

    def __init__(self, config={}):
        super().__init__(config)
        # user id -> {"labels": DataFrame, "genesets": dict, "geneset_tid": int}
        self._store = OrderedDict()
        self._lock = threading.RLock()

    def is_safe_collection_name(self, name):
        """The client never sends a collection name in this mode (the prompt is
        suppressed), but validate defensively if one ever arrives."""
        if name is None:
            return False
        return re.match(r"^[\w\-]+$", name) is not None

    def set_collection(self, name):
        # No collections in ephemeral mode: a single bucket per session.
        pass

    def _bucket(self, create=False):
        """Return this session's storage bucket, keyed by the session user id.

        With ``create=False`` a missing bucket yields ``None`` (read path);
        with ``create=True`` an empty bucket is created and marked most-recently
        used, evicting the oldest session past ``_MAX_SESSIONS``.
        """
        uid = get_user_id(session)
        with self._lock:
            bucket = self._store.get(uid)
            if bucket is None:
                if not create:
                    return None
                bucket = {"labels": pd.DataFrame(), "genesets": {}, "geneset_tid": 0}
                self._store[uid] = bucket
            self._store.move_to_end(uid)
            while len(self._store) > self._MAX_SESSIONS:
                self._store.popitem(last=False)
            return bucket

    def read_labels(self, data_adaptor):
        self.check_user_annotations_enabled()  # raises
        bucket = self._bucket(create=False)
        if bucket is None:
            return pd.DataFrame()
        with self._lock:
            return bucket["labels"]

    def write_labels(self, df, data_adaptor):
        self.check_user_annotations_enabled()  # raises
        bucket = self._bucket(create=True)
        with self._lock:
            bucket["labels"] = df

    def read_gene_sets(self, data_adaptor, context=None):
        bucket = self._bucket(create=False)
        if bucket is None:
            return ({}, 0)
        with self._lock:
            return (bucket["genesets"], bucket["geneset_tid"])

    def write_gene_sets(self, gene_sets, tid, data_adaptor):
        self.check_gene_sets_save_enabled()  # raises

        if type(tid) is not int or tid < 0:
            raise ValueError("tid must be a positive integer")

        # may raise
        gene_sets = data_adaptor.check_new_gene_sets(gene_sets)

        bucket = self._bucket(create=True)
        with self._lock:
            # skip if the request is stale (mirrors AnnotationsLocalFile)
            if tid is not None:
                if tid <= bucket["geneset_tid"]:
                    raise ObsoleteRequest("TID is stale.")
                bucket["geneset_tid"] = tid
            if isinstance(gene_sets, dict):
                bucket["genesets"] = gene_sets
            else:
                bucket["genesets"] = {g["geneset_name"]: g for g in gene_sets}

    def _get_userdata_idhash(self, data_adaptor):
        """Short, weak per-user+dataset id (used only for a stable client-side
        display value; no files are named with it in this mode)."""
        uid = get_user_id(session)
        ident = (uid + data_adaptor.get_location()).encode()
        return base64.b32encode(blake2b(ident, digest_size=5).digest()).decode("utf-8")

    def update_parameters(self, parameters, data_adaptor):
        params = {}
        params["annotations"] = self.user_annotations_enabled()
        params["annotations_genesets_readonly"] = not self.gene_sets_save_enabled()
        # Ephemeral mode has no user-named collection/file, so the client must not
        # prompt for a data-directory name and must treat the collection as fixed
        # and read-only (see client/src/components/autosave/filenameDialog.js).
        params["annotations_genesets_name_is_read_only"] = True
        params["user_annotation_collection_name_enabled"] = False
        params["annotations-data-collection-is-read-only"] = True
        params["annotations-data-collection-name"] = "ephemeral"
        params["annotations-user-data-idhash"] = self._get_userdata_idhash(data_adaptor)
        parameters.update(params)
