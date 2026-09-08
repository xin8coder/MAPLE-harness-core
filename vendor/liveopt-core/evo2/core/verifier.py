from __future__ import annotations


class Verifier:
    """Abstract verifier. Domain verifiers should be deterministic and final."""

    def verify(self, ir, solution, context=None) -> dict:
        raise NotImplementedError
