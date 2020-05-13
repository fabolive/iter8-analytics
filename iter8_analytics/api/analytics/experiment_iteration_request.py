"""
Pydantic data model for iter8 experiment iteration request
"""
# Core python stuff
from datetime import datetime
from enum import Enum
from uuid import UUID
from typing import Tuple, Union, Sequence, Dict, Any

# Module dependencies
from pydantic import BaseModel, Field

# iter8 stuff
from iter8_analytics.api.analytics.experiment_iteration_response import Iter8AssessmentAndRecommendation

# type alias
iter8id = Union[int, str, UUID]

class Version(BaseModel):
    id: iter8id = Field(..., description="ID of the version")
    version_labels: dict = Field(..., description="Key-value pairs used in prometheus queries to achieve version level grouping")

class DirectionEnum(str, Enum): # directions for metric values
    lower = "lower"
    higher = "higher"

class MetricSpec(BaseModel):
    id: iter8id = Field(..., alias = "name", description="ID of the metric")
    preferred_direction: DirectionEnum = Field(None, description="Indicates preference for metric values -- lower, higher, or None (default)")
    # this will be used in KUI / Kiali / controller status fields
    descriptive_short_name: str = Field(None, description = "Descriptive short name")

    class Config:
        allow_population_by_field_name = True

# counter metric defined in iter8 configmaps
class CounterMetricSpec(MetricSpec):
    query_template: str = Field(...,
                                     description="Prometheus query template")

class RatioMetricSpec(MetricSpec):  # ratio metric = numerator counter / denominator counter
    numerator: str = Field(
        ..., description="ID of the counter metric used in numerator")
    denominator: str = Field(
        ..., description="ID of the counter metric used in denominator")
    zero_to_one: bool = Field(
        False, description="Boolean flag indicating if the value of this metric is always in the range 0 to 1")

class MetricSpecs(BaseModel):
    counter_metrics: Sequence[CounterMetricSpec] = Field(..., description = "All counter metric specs")
    ratio_metrics: Sequence[RatioMetricSpec] = Field(..., description = "All ratio metric specs")

class ThresholdEnum(str, Enum):
    absolute = "absolute"  # this threshold represents an absolute limit
    relative = "relative"  # this threshold represents a limit relative to baseline

class Threshold(BaseModel):
    threshold_type: ThresholdEnum = Field(..., alias = "type", description="Type of threshold")
    value: float = Field(..., description="Value of threshold")

    class Config:
        allow_population_by_field_name = True

class Criterion(BaseModel):
    id: iter8id = Field(..., description = "ID of the criterion")
    metric_id: iter8id = Field(
        ..., description="ID of the metric. This matches the unique ID of the metric in the metric spec")
    is_reward: bool = Field(
        False, description="Boolean flag indicating if this metric will be used as reward to be optimized in an A/B test. Only ratio metrics can be used as a reward. At most one metric can be used as reward")
    threshold: Threshold = Field(None, description="Threshold value for this metric if any")

# class Duration(BaseModel):
#     max_iterations: int = Field(..., description = "Maximum number of iterations in the experiment")

class TrafficSplitStrategy(str, Enum):
    progressive = "progressive" # PBR
    top_2 = "top_2" # top 2 PBR
    uniform = "uniform" # Uniform split

class TrafficControl(BaseModel): # parameters pertaining to traffic control
    max_increment: float = Field(
        2.0, description="Maximum possible increment in a candidate's traffic during the initial phase of the experiment", ge=0.0, le=100.0)
    strategy: TrafficSplitStrategy = Field(TrafficSplitStrategy.progressive, description = "Traffic split algorithm to use during the experiment")

# parameters for current iteration of experiment
class ExperimentIterationParameters(BaseModel):
    start_time: datetime = Field(...,
                                 description="Start time of the experiment")
    iteration_number: int = Field(None, description = "Iteration number, ranging from 1 to maximum number of iterations (advanced_parameters.max_iterations). This is mandatory for controller interactions. Optional for human-in-the-loop interactions", ge = 1)
    service_name: str = Field(..., description = "Name of the service in this experiment")
    baseline: Version = Field(..., description="The baseline version")
    candidates: Sequence[Version] = Field(...,
                                          description="The set of candidates")
    metric_specs: MetricSpecs = Field(
        ..., description="All metric specification")
    criteria: Sequence[Criterion] = Field(
        ..., description="Criteria to be assessed for each version in this experiment")
    traffic_control: TrafficControl = Field(TrafficControl(
        max_increment = 2.0, strategy = TrafficSplitStrategy.progressive
    ), description = "Advanced parameters") # default traffic control
    last_state: Any = Field(
        None, description="Last recorded state from analytics service")
