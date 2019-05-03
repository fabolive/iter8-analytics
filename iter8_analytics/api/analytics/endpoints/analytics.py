"""
REST resources related to canary analytics.
"""

import iter8_analytics.api.analytics.request_parameters as request_parameters
import iter8_analytics.api.analytics.responses as responses
from iter8_analytics.api.restplus import api
from iter8_analytics.metrics_backend.iter8metric import Iter8MetricFactory
from iter8_analytics.metrics_backend.successcriteria import DeltaCriterion, ThresholdCriterion
import iter8_analytics.constants as constants
import flask_restplus
from flask import request

from datetime import datetime, timezone

import json
import os
import logging

log = logging.getLogger(__name__)

metrics_config = {
  "iter8_latency": {
    "type": "histogram",
    "zero_value_on_null": True,
    "query_templates": {
      "sample_size": "sum(increase(istio_requests_total{reporter='source'}[$interval]$offset_str)) by ($entity_labels)",
      "min": "sum(increase(istio_request_duration_seconds_bucket{reporter='source'}[$interval]$offset_str)) by (le, $entity_labels)",
      "mean": "(sum(increase(istio_request_duration_seconds_sum{reporter='source'}[$interval]$offset_str)) by ($entity_labels)) / (sum(increase(istio_request_duration_seconds_count{reporter='source'}[$interval]$offset_str)) by ($entity_labels))",
      "max": "sum(increase(istio_request_duration_seconds_bucket{reporter='source'}[$interval]$offset_str)) by (le, $entity_labels)",
      "stddev": "sum(increase(istio_request_duration_seconds_bucket{reporter='source'}[$interval]$offset_str)) by (le, $entity_labels)",
      "first_quartile": "histogram_quantile(0.25, sum(rate(istio_request_duration_seconds_bucket{reporter='source'}[$interval]$offset_str)) by (le, $entity_labels))",
      "median": "histogram_quantile(0.5, sum(rate(istio_request_duration_seconds_bucket{reporter='source'}[$interval]$offset_str)) by (le, $entity_labels))",
      "third_quartile": "histogram_quantile(0.75, sum(rate(istio_request_duration_seconds_bucket{reporter='source'}[$interval]$offset_str)) by (le, $entity_labels))",
      "95th_percentile": "histogram_quantile(0.95, sum(rate(istio_request_duration_seconds_bucket{reporter='source'}[$interval]$offset_str)) by (le, $entity_labels))",
      "99th_percentile": "histogram_quantile(0.99, sum(rate(istio_request_duration_seconds_bucket{reporter='source'}[$interval]$offset_str)) by (le, $entity_labels))",
      "value": "(sum(increase(istio_request_duration_seconds_sum{reporter='source'}[$interval]$offset_str)) by ($entity_labels)) / (sum(increase(istio_request_duration_seconds_count{reporter='source'}[$interval]$offset_str)) by ($entity_labels))"
    }
  },
  "iter8_error_rate": {
    "type": "gauge",
    "zero_value_on_null": True,
    "query_templates": {
      "sample_size": "sum(increase(istio_requests_total{reporter='source'}[$interval]$offset_str)) by ($entity_labels)",
      "value": "sum(increase(istio_requests_total{response_code=~'5..',reporter='source'}[$interval]$offset_str)) by ($entity_labels) / sum(increase(istio_requests_total{reporter='source'}[$interval]$offset_str)) by ($entity_labels)"
    }
  },
  "iter8_error_count": {
    "type": "counter",
    "zero_value_on_null": True,
    "query_templates": {
      "sample_size": "sum(increase(istio_requests_total{reporter='source'}[$interval]$offset_str)) by ($entity_labels)",
      "value": "sum(increase(istio_requests_total{response_code=~'5..',reporter='source'}[$interval]$offset_str)) by ($entity_labels)) / (sum(increase(istio_requests_total{reporter='source'}[$interval]$offset_str)) by ($entity_labels))"
    }
  }
}

prom_url = os.getenv(constants.ITER8_ANALYTICS_METRICS_BACKEND_URL_ENV)

analytics_namespace = api.namespace(
    'analytics',
    description='Operations to support canary releases and A/B tests')

#################
# REST API
#################


@analytics_namespace.route('/canary/check_and_increment')
class CanaryCheckAndIncrement(flask_restplus.Resource):

    @api.expect(request_parameters.check_and_increment_parameters,
                validate=True)
    @api.marshal_with(responses.check_and_increment_response)
    def post(self):
        """Assess the canary version and recommend traffic-control actions."""
        log.info('Started processing request to assess the canary using the '
                 '"check_and_increment" strategy')

        self.metric_factory = Iter8MetricFactory(prom_url)

        payload = request.get_json()
        log.info("Extracted payload")
        self.experiment = self.fix_experiment_defaults(payload)
        log.info("Fixed experiment")
        self.create_response_object()
        log.info("Created response object")
        try:
            self.append_metrics_and_success_criteria()
        except ValueError as e:
            flask_restplus.errors.abort(code=400, message=str(e))
        log.info("Appended metrics and success criteria")
        self.append_assessment_summary()
        log.info("Append assessment summary")
        self.append_traffic_decision()
        log.info("Append traffic decision")
        return self.response

    def fix_experiment_defaults(self, payload):
        if not payload["_last_state"]:  # if it is empty
            last_state = {
                "baseline": {
                    "traffic_percentage": 100.0
                },
                "canary": {
                    "traffic_percentage": 0.0
                }
            }
            payload["_last_state"] = last_state
            payload["first_iteration"] = True
        else:
            payload["first_iteration"] = False

        if not "end_time" in payload["baseline"]:
            payload["baseline"]["end_time"] = str(datetime.now(timezone.utc))
        if not "end_time" in payload["canary"]:
            payload["canary"]["end_time"] = str(datetime.now(timezone.utc))

        for criterion in payload["traffic_control"]["success_criteria"]:
            if "sample_size" not in criterion:
                criterion["sample_size"] = 10

        if "step_size" not in payload["traffic_control"]:
            payload["traffic_control"]["step_size"] = 2.0
        if "max_traffic_percent" not in payload["traffic_control"]:
            payload["traffic_control"]["max_traffic_percent"] = 50

        return payload

    def create_response_object(self):
        """Create response object corresponding to payload. This has everything and more."""
        self.response = {
            "metric_backend_url": prom_url,
            "canary": {
                "metrics": [],
                "traffic_percentage": None
            },
            "baseline": {
                "metrics": [],
                "traffic_percentage": None
            },
            "assessment": {
                "summary": {},
                "success_criteria": []
            }
        }

    def append_metrics_and_success_criteria(self):
        for criterion in self.experiment["traffic_control"]["success_criteria"]:
            self.response["baseline"]["metrics"].append(self.get_results(
                criterion["metric_name"], self.experiment["baseline"]))
            self.response["canary"]["metrics"].append(self.get_results(
                criterion["metric_name"], self.experiment["canary"]))
            self.append_success_criteria(criterion)

    def get_results(self, metric_name, entity):
        metric_spec = self.metric_factory.create_metric_spec(
            metrics_config, metric_name, entity["tags"])
        metrics_object = self.metric_factory.get_iter8_metric(metric_spec)
        interval_str, offset_str = self.metric_factory.get_interval_and_offset_str(
            entity["start_time"], entity["end_time"])
        statistics = metrics_object.get_stats(interval_str, offset_str)
        return {
            "metric_name": metric_name,
            "metric_type": metrics_config[metric_name]["type"],
            "statistics": statistics
        }

    def append_success_criteria(self, criterion):
        if criterion["type"] == "delta":
            self.response["assessment"]["success_criteria"].append(DeltaCriterion(
                criterion, self.response["baseline"]["metrics"][-1], self.response["canary"]["metrics"][-1]).test())
        else:
            self.response["assessment"]["success_criteria"].append(
                ThresholdCriterion(criterion, self.response["canary"]["metrics"][-1]).test())
        # print(self.response["assessment"]["success_criteria"])

    def append_assessment_summary(self):
        self.response["assessment"]["summary"]["all_success_criteria_met"] = all(
            criterion["success_criterion_met"] for criterion in self.response["assessment"]["success_criteria"])
        self.response["assessment"]["summary"]["abort_experiment"] = any(
            criterion["abort_experiment"] for criterion in self.response["assessment"]["success_criteria"])
        self.response["assessment"]["summary"]["conclusions"] = ["All ok"]

    def append_traffic_decision(self):
        last_state = self.experiment["_last_state"]
        # Compute current decisions below based on increment or hold
        if self.experiment["first_iteration"] or self.response["assessment"]["summary"]["all_success_criteria_met"]:
            new_canary_traffic_percentage = min(
                last_state["canary"]["traffic_percentage"] +
                self.experiment["traffic_control"]["step_size"],
                self.experiment["traffic_control"]["max_traffic_percent"])
        else:
            new_canary_traffic_percentage = last_state["canary"]["traffic_percentage"]
        new_baseline_traffic_percentage = 100.0 - new_canary_traffic_percentage

        self.response["_last_state"] = {
            "baseline": {
                "traffic_percentage": new_baseline_traffic_percentage
            },
            "canary": {
                "traffic_percentage": new_canary_traffic_percentage
            }
        }
        self.response["baseline"]["traffic_percentage"] = new_baseline_traffic_percentage
        self.response["canary"]["traffic_percentage"] = new_canary_traffic_percentage