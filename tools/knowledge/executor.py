from __future__ import annotations

import importlib

from tools.knowledge.models import (
    CapabilityCandidate,
    EvidenceBundle,
    KnowledgeSearchRequest,
)


class CapabilityExecutor:
    def __init__(self):
        self._instances: dict[str, object] = {}

    def execute(
        self,
        candidate: CapabilityCandidate,
        request: KnowledgeSearchRequest,
    ) -> EvidenceBundle:
        capability = candidate.capability
        instance = self._get_instance(capability.handler)

        search = getattr(instance, "search", None)
        if search is None:
            return EvidenceBundle(
                capability_id=capability.id,
                source=capability.name,
                status="error",
                confidence=0.0,
                errors=[f"Capability handler has no search() method: {capability.handler}"],
            )

        return search(request)

    def diagnostics(self, candidate: CapabilityCandidate) -> dict[str, object]:
        instance = self._instances.get(candidate.capability.handler)
        if instance is None:
            return {}

        diagnostics = getattr(instance, "diagnostics", None)
        if diagnostics is None:
            return {}

        result = diagnostics()
        return result if isinstance(result, dict) else {}

    def _get_instance(self, handler_path: str) -> object:
        if handler_path in self._instances:
            return self._instances[handler_path]

        module_name, class_name = handler_path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)

        instance = cls()
        self._instances[handler_path] = instance
        return instance
