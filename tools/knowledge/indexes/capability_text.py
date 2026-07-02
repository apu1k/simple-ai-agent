from __future__ import annotations

from tools.knowledge.models import CapabilityDefinition


def capability_embedding_text(capability: CapabilityDefinition) -> str:
    """Return deterministic text that can be embedded for capability retrieval."""
    lines = [
        f"Capability: {capability.name}",
        f"ID: {capability.id}",
        f"Type: {capability.capability_type}",
        f"Description: {capability.description}",
    ]

    if capability.tags:
        lines.append(f"Tags: {', '.join(capability.tags)}")

    if capability.examples:
        lines.append("Examples:")
        lines.extend(f"- {example}" for example in capability.examples)

    if capability.required_permissions:
        lines.append(f"Required permissions: {', '.join(capability.required_permissions)}")

    lines.append(f"Sensitivity: {capability.sensitivity}")
    lines.append(f"Network access: {'yes' if capability.allow_network else 'no'}")

    return "\n".join(lines)
