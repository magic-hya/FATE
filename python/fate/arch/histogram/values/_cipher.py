import logging
import typing
from typing import List, Tuple

from ._encoded import HistogramEncodedValues
from ._value import HistogramValues
from ..indexer import Shuffler

logger = logging.getLogger(__name__)


class HistogramEncryptedValues(HistogramValues):
    def __init__(self, pk, evaluator, data, coder, stride=1):
        if stride > 1:
            raise NotImplementedError
        self.stride = stride
        self.data = data
        self.pk = pk
        self.coder = coder
        self.evaluator = evaluator

    @classmethod
    def zeros(cls, pk, evaluator, coder, size: int, stride: int = 1):
        return cls(pk, evaluator, evaluator.zeros(size * stride), coder, stride)

    def i_update(self, value, positions):
        from fate.arch.tensor.phe import PHETensor

        if isinstance(value, PHETensor):
            value = value.data

        if hasattr(self.evaluator, "i_update"):
            return self.evaluator.i_update(self.pk, self.data, value, positions, self.stride)
        else:
            for i, feature_positions in enumerate(positions):
                for pos in feature_positions:
                    self.evaluator.i_add(self.pk, self.data, value, pos * self.stride, i * self.stride, self.stride)

    def iadd(self, other):
        self.evaluator.i_add(self.pk, self.data, other.data)
        return self

    def slice(self, start, end):
        return HistogramEncryptedValues(
            self.pk,
            self.evaluator,
            self.evaluator.slice(self.data, start * self.stride, (end - start) * self.stride),
            self.coder,
            self.stride,
        )

    def intervals_slice(self, intervals: typing.List[typing.Tuple[int, int]]) -> "HistogramEncryptedValues":
        intervals = [(start * self.stride, end * self.stride) for start, end in intervals]
        data = self.evaluator.intervals_slice(self.data, intervals)
        return HistogramEncryptedValues(self.pk, self.evaluator, data, self.coder, self.stride)

    def i_shuffle(self, shuffler: "Shuffler", reverse=False):
        indices = shuffler.get_shuffle_index(step=self.stride, reverse=reverse)
        self.evaluator.i_shuffle(self.pk, self.data, indices)
        return self

    def chunking_sum(self, intervals: typing.List[typing.Tuple[int, int]]):
        """
        sum bins in the given logical intervals
        """
        intervals = [(start * self.stride, end * self.stride) for start, end in intervals]
        data = self.evaluator.intervals_sum_with_step(self.pk, self.data, intervals, self.stride)
        return HistogramEncryptedValues(self.pk, self.evaluator, data, self.coder, self.stride)

    def compute_child(
        self,
        weak_child: "HistogramEncryptedValues",
        positions: List[Tuple[int, int, int, int, int, int, int, int]],
        size: int,
    ):
        data = self.evaluator.zeros(size * self.stride)
        for (
            target_weak_child_start,
            target_weak_child_end,
            target_strong_child_start,
            target_strong_child_end,
            parent_data_start,
            parent_data_end,
            weak_child_data_start,
            weak_child_data_end,
        ) in positions:
            s = (parent_data_end - parent_data_start) * self.stride
            self.evaluator.i_add(self.pk, data, weak_child.data, target_weak_child_start, weak_child_data_start, s)
            self.evaluator.i_add(self.pk, data, self.data, target_strong_child_start, parent_data_start, s)
            self.evaluator.i_sub(self.pk, data, weak_child.data, target_strong_child_start, weak_child_data_start, s)

        return HistogramEncryptedValues(self.pk, self.evaluator, data, self.coder, self.stride)

    def decrypt(self, sk):
        data = sk.decrypt_to_encoded(self.data)
        return HistogramEncodedValues(data, self.stride)

    def squeeze(self, pack_num, offset_bit):
        data = self.evaluator.pack_squeeze(self.data, pack_num, offset_bit, self.pk)
        return HistogramEncryptedValues(self.pk, self.evaluator, data, self.coder, self.stride)

    def i_chunking_cumsum(self, chunk_sizes: typing.List[int]):
        chunk_sizes = [num * self.stride for num in chunk_sizes]
        self.evaluator.chunking_cumsum_with_step(self.pk, self.data, chunk_sizes, self.stride)
        return self

    def __str__(self):
        return f"<HistogramEncryptedValues stride={self.stride}, data={self.data}>"

    def extract_node_data(self, node_data_size, node_size):
        raise NotImplementedError
