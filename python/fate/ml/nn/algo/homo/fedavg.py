import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, Union

from fate.arch import Context
from fate.ml.aggregator import (
    AggregatorType,
    PlainTextAggregatorClient,
    PlainTextAggregatorServer,
    SecureAggregatorClient,
    SecureAggregatorServer,
    aggregator_map,
)
from fate.ml.nn.trainer.trainer_base import (
    FedArguments,
    FedTrainerClient,
    FedTrainerServer,
    TrainingArguments,
)
from torch import nn
from torch.nn import Module
from torch.optim import Optimizer
from torch.optim.lr_scheduler import _LRScheduler
from torch.utils.data import DataLoader, Dataset
from transformers import PreTrainedTokenizer, TrainerControl, TrainerState
from transformers.trainer_callback import TrainerCallback
from transformers.training_args import TrainingArguments

logger = logging.getLogger(__name__)


@dataclass
class FedAVGArguments(FedArguments):

    """
    The arguemnt for FedAVG algorithm, used in FedAVGClient and FedAVGServer.

    Attributes:
        weighted_aggregate: bool
            Whether to use weighted aggregation or not.
        secure_aggregate: bool
            Whether to use secure aggregation or not.
    """

    weighted_aggregate: bool = field(default=True)
    secure_aggregate: bool = field(default=False)


class FedAVGCLient(FedTrainerClient):
    def __init__(
        self,
        ctx: Context,
        model: Module,
        training_args: TrainingArguments,
        fed_args: FedArguments,
        train_set: Dataset,
        val_set: Dataset = None,
        loss_fn: Module = None,
        optimizer: Optimizer = None,
        scheduler: _LRScheduler = None,
        callbacks: List[TrainerCallback] = [],
        data_collator: Callable = None,
        tokenizer: Optional[PreTrainedTokenizer] = None,
        use_hf_default_behavior: bool = False,
        compute_metrics: Callable = None,
        local_mode: bool = False,
    ):

        super().__init__(
            ctx,
            model,
            training_args,
            fed_args,
            train_set,
            val_set,
            loss_fn,
            optimizer,
            data_collator,
            scheduler,
            tokenizer,
            callbacks,
            use_hf_default_behavior,
            compute_metrics=compute_metrics,
            local_mode=local_mode,
        )

    def init_aggregator(self, ctx: Context, fed_args: FedArguments):

        aggregate_type = "weighted_mean"
        aggregator_name = "fedavg"
        aggregator = fed_args.aggregator
        assert aggregator in {
            item.value for item in AggregatorType
        }, f"aggregator should be one of {{item.value for item in AggregatorType}}, but got {aggregator}"
        client_class = aggregator_map[aggregator][0]
        logger.info(f"Using {aggregator} aggregator")
        sample_num = len(self.train_dataset)
        ctx.arbiter.put("agg_type", aggregator)
        aggregator = client_class(
            ctx, aggregate_type=aggregate_type, aggregator_name=aggregator_name, sample_num=sample_num
        )

        return aggregator

    def on_federation(
        self,
        ctx: Context,
        aggregator: Union[PlainTextAggregatorClient, SecureAggregatorClient],
        fed_args: FedArguments,
        args: TrainingArguments,
        model: Optional[nn.Module] = None,
        optimizer: Optional[Optimizer] = None,
        scheduler: Optional[_LRScheduler] = None,
        dataloader: Optional[Tuple[DataLoader]] = None,
        control: Optional[TrainerControl] = None,
        state: Optional[TrainerState] = None,
        **kwargs,
    ):

        aggregator.model_aggregation(ctx, model)


class FedAVGServer(FedTrainerServer):
    def __init__(self, ctx: Context, local_mode: bool = False) -> None:

        super().__init__(ctx, local_mode)

    def init_aggregator(self, ctx):

        aggregator = [ctx.guest.get("agg_type")]
        aggregator.extend(ctx.hosts.get("agg_type"))
        aggregator = set(aggregator)
        if len(aggregator) > 1:
            raise ValueError("Aggregator type should be the same between clients, but got {}".format(aggregator))
        aggregator = aggregator.pop()
        aggregator_name = "fedavg"
        aggregator_server = aggregator_map[aggregator][1]
        logger.info(f"Using {aggregator} aggregator")
        aggregator = aggregator_server(ctx, aggregator_name=aggregator_name)
        return aggregator

    def on_federation(self, ctx: Context, aggregator: Union[SecureAggregatorServer, PlainTextAggregatorServer]):

        aggregator.model_aggregation(ctx)


class FedAVG(object):

    client = FedAVGCLient
    server = FedAVGServer
