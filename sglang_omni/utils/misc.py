# SPDX-License-Identifier: Apache-2.0
"""Import helpers for config-driven wiring."""

from __future__ import annotations

import pickle
import random
import re
from typing import Any

import numpy as np
import torch
import torch.distributed as dist
from transformers import PretrainedConfig


def get_layer_id(weight_name: str) -> int | None:
    """Extract the layer index from a model weight name like layers.10.self_attn.

    Returns None when the name does not follow the layers.<N>. convention.
    """
    match = re.search(r"layers\.(\d+)\.", weight_name)
    if match:
        return int(match.group(1))
    return None


def add_prefix(name: str, prefix: str) -> str:
    """Add a weight path prefix to a module name."""
    return name if not prefix else f"{prefix}.{name}"


def set_random_seed(seed: int) -> None:
    """Set the random seed for all libraries."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def avail_gpu_mem(gpu_id: int) -> float | None:
    """Return currently free GPU memory in GiB, or None when unavailable."""
    try:
        if not torch.cuda.is_available():
            return None
        free_bytes, _ = torch.cuda.mem_get_info(gpu_id)
        return free_bytes / (1024**3)
    except Exception:
        return None


def broadcast_pyobj(
    data: list[Any],
    rank: int,
    dist_group: torch.distributed.ProcessGroup | None = None,
    src: int = 0,
    force_cpu_device: bool = True,
) -> list[Any]:
    """Broadcast a Python object from rank 0 to all other ranks via torch.dist."""
    device = torch.device(
        "cuda" if torch.cuda.is_available() and not force_cpu_device else "cpu"
    )
    if rank == src:
        if len(data) == 0:
            tensor_size = torch.tensor([0], dtype=torch.long, device=device)
            dist.broadcast(tensor_size, src=0, group=dist_group)
        else:
            serialized_data = pickle.dumps(data)
            size = len(serialized_data)

            tensor_data = torch.ByteTensor(
                np.frombuffer(serialized_data, dtype=np.uint8)
            ).to(device)
            tensor_size = torch.tensor([size], dtype=torch.long, device=device)

            dist.broadcast(tensor_size, src=0, group=dist_group)
            dist.broadcast(tensor_data, src=0, group=dist_group)
        return data
    else:
        tensor_size = torch.tensor([0], dtype=torch.long, device=device)
        dist.broadcast(tensor_size, src=0, group=dist_group)
        size = tensor_size.item()

        if size == 0:
            return []

        tensor_data = torch.empty(size, dtype=torch.uint8, device=device)
        dist.broadcast(tensor_data, src=0, group=dist_group)

        serialized_data = bytes(tensor_data.cpu().numpy())
        data = pickle.loads(serialized_data)
        return data


def normalize_quantization(value: object) -> str | None:
    """Normalize a quantization method name to lowercase."""
    if value is None:
        return None
    return str(value).lower()


def model_config_has_moe(model_config: PretrainedConfig) -> bool:
    """Check whether a model config describes a MoE architecture."""
    return hasattr(model_config.hf_text_config, "num_experts_per_tok")


__all__ = [
    "get_layer_id",
    "add_prefix",
    "set_random_seed",
    "avail_gpu_mem",
    "broadcast_pyobj",
    "normalize_quantization",
    "model_config_has_moe",
]
