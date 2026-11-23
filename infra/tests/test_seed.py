import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda" / "ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import seed


class FakeS3:
    def __init__(self, buckets):
        self.buckets = buckets  # {bucket: {key: (etag, size)}}
        self.copies = []

    def get_paginator(self, _name):
        outer = self

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k, "ETag": e, "Size": s}
                                    for k, (e, s) in sorted(outer.buckets[Bucket].items()) if k.startswith(Prefix)]}
        return P()

    def copy_object(self, Bucket, Key, CopySource):
        self.copies.append((Bucket, Key))
        self.buckets[Bucket][Key] = self.buckets[CopySource["Bucket"]][Key]


class CopyProd(unittest.TestCase):
    def run_copy(self, prod, gamma):
        s3 = FakeS3({seed.PROD_BUCKET: prod, "g": gamma})
        original = seed._read_index, seed.keep_gamma_players
        seed._read_index = lambda store: ([], None)
        seed.keep_gamma_players = lambda store, before: []
        try:
            seed.copy_prod(s3=s3, store=object(), gamma="g")
        finally:
            seed._read_index, seed.keep_gamma_players = original
        return s3

    def test_copies_only_missing_or_changed_and_never_deletes(self):
        s3 = self.run_copy(
            {"users/a": ("1", 1), "raw/b": ("2", 2), "users/c": ("9", 9), "_uploads/x": ("3", 3)},
            {"users/a": ("1", 1), "raw/b": ("old", 2), "users/gamma-only": ("7", 7)},
        )
        self.assertEqual(sorted(s3.copies), [("g", "raw/b"), ("g", "users/c")])
        self.assertIn("users/gamma-only", s3.buckets["g"])

    def test_refuses_to_copy_onto_prod(self):
        with self.assertRaises(RuntimeError):
            seed.copy_prod(s3=FakeS3({}), store=object(), gamma=seed.PROD_BUCKET)


if __name__ == "__main__":
    unittest.main()
