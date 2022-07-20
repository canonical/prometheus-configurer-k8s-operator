#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import time
from pathlib import Path

import pytest
import requests
import yaml
from prometheus import Prometheus
from pytest_operator.plugin import OpsTest  # type: ignore[import]  # noqa: F401

logger = logging.getLogger(__name__)
METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

PROMETHEUS_CONFIGURER_APP_NAME = METADATA["name"]
PROMETHEUS_APP_NAME = PROMETHEUS_CHARM_NAME = "prometheus-k8s"
WAIT_FOR_STATUS_TIMEOUT = 1 * 60
DUMMY_HTTP_SERVER_PORT = 80
TEST_TENANT = "test_tenant"
TEST_ALERT_NAME = "CPUOverUse"


class TestPrometheusConfigurerOperatorCharm:
    @pytest.fixture(scope="module")
    @pytest.mark.abort_on_fail
    async def setup(self, ops_test: OpsTest):
        await ops_test.model.set_config({"update-status-hook-interval": "2s"})
        await self._deploy_prometheus_k8s(ops_test)
        charm = await ops_test.build_charm(".")
        resources = {
            f"{PROMETHEUS_CONFIGURER_APP_NAME}-image": METADATA["resources"][
                f"{PROMETHEUS_CONFIGURER_APP_NAME}-image"
            ]["upstream-source"],
            "dummy-http-server-image": METADATA["resources"][
                "dummy-http-server-image"
            ]["upstream-source"],
        }
        await ops_test.model.deploy(
            charm, resources=resources, application_name=PROMETHEUS_CONFIGURER_APP_NAME, trust=True
        )

    @pytest.mark.abort_on_fail
    async def test_given_prometheus_configurer_charm_is_not_related_to_prometheus_when_charm_deployed_then_charm_goes_to_blocked_status(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        await ops_test.model.wait_for_idle(
            apps=[PROMETHEUS_CONFIGURER_APP_NAME],
            status="blocked",
            timeout=WAIT_FOR_STATUS_TIMEOUT,
        )

    @pytest.mark.abort_on_fail
    async def test_given_prometheus_configurer_charm_in_blocked_status_when_prometheus_relation_created_then_charm_goes_to_active_status(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        await ops_test.model.add_relation(
            relation1=f"{PROMETHEUS_CONFIGURER_APP_NAME}",
            relation2="prometheus-k8s:receive-remote-write",
        )
        await ops_test.model.wait_for_idle(
            apps=[PROMETHEUS_CONFIGURER_APP_NAME],
            status="active",
            timeout=WAIT_FOR_STATUS_TIMEOUT,
        )

    @pytest.mark.abort_on_fail
    async def test_given_prometheus_configurer_running_when_post_sent_to_the_dummy_http_server_called_then_server_responds_with_200(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        dummy_http_server_ip = await _unit_address(ops_test, PROMETHEUS_CONFIGURER_APP_NAME, 0)
        dummy_server_response = requests.post(
            f"http://{dummy_http_server_ip}:{DUMMY_HTTP_SERVER_PORT}"
        )
        assert dummy_server_response.status_code == 200

    @pytest.mark.abort_on_fail
    async def test_given_prometheus_server_in_initial_state_when_get_rules_then_prometheus_server_has_no_rules(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        initial_rules = await _get_prometheus_rules(ops_test, PROMETHEUS_APP_NAME, 0)
        assert initial_rules == []

    @pytest.mark.abort_on_fail
    async def test_given_prometheus_configurer_ready_when_new_alert_rule_created_then_prometheus_alert_rules_are_updated(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        prometheus_configurer_server_ip = await _unit_address(
            ops_test, PROMETHEUS_CONFIGURER_APP_NAME, 0
        )
        status = await ops_test.model.get_status()
        model_name = status["model"]["name"]
        model_uuid = ops_test.model.uuid
        test_rule_json = {
            "alert": f"{TEST_ALERT_NAME}",
            "expr": "process_cpu_seconds_total > 0.12",
            "for": "0m",
            "labels": {"severity": "Low"},
            "annotations": {"summary": "Rule summary.", "description": "Rule description."},
        }
        expected_prometheus_rules = {
            "alerts": [],
            "annotations": {"description": "Rule description.", "summary": "Rule summary."},
            "duration": 0,
            "evaluationTime": 0,
            "health": "unknown",
            "labels": {
                "juju_application": f"{PROMETHEUS_CONFIGURER_APP_NAME}",
                "juju_charm": f"{PROMETHEUS_CONFIGURER_APP_NAME}",
                "juju_model": f"{model_name}",
                "juju_model_uuid": f"{model_uuid}",
                "networkID": f"{TEST_TENANT}",
                "severity": "Low",
            },
            "lastEvaluation": "0001-01-01T00:00:00Z",
            "name": f"{TEST_ALERT_NAME}",
            "query": f'process_cpu_seconds_total{{juju_application="{PROMETHEUS_CONFIGURER_APP_NAME}",juju_charm="{PROMETHEUS_CONFIGURER_APP_NAME}",juju_model="{model_name}",juju_model_uuid="{model_uuid}",networkID="{TEST_TENANT}"}} '  # noqa: E501
            "> 0.12",
            "state": "inactive",
            "type": "alerting",
        }

        server_response = requests.post(
            f"http://{prometheus_configurer_server_ip}:9100/{TEST_TENANT}/alert",
            json=test_rule_json,
        )
        assert server_response.status_code == 200

        # Prometheus needs a couple of seconds to reload configuration
        time.sleep(5)
        prometheus_rules = await _get_prometheus_rules(ops_test, PROMETHEUS_APP_NAME, 0)

        assert len(prometheus_rules) == 1
        assert prometheus_rules[0]["rules"][0] == expected_prometheus_rules

    @pytest.mark.abort_on_fail
    async def test_given_prometheus_configurer_with_existing_rule_when_get_alert_rules_then_expected_alert_rules_are_returned(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        prometheus_configurer_server_ip = await _unit_address(
            ops_test, PROMETHEUS_CONFIGURER_APP_NAME, 0
        )
        expected_response = {
            "alert": f"{TEST_ALERT_NAME}",
            "expr": f'process_cpu_seconds_total{{networkID="{TEST_TENANT}"}} > 0.12',
            "for": "0s",
            "labels": {"networkID": f"{TEST_TENANT}", "severity": "Low"},
            "annotations": {"description": "Rule description.", "summary": "Rule summary."},
        }

        server_response = requests.get(
            f"http://{prometheus_configurer_server_ip}:9100/{TEST_TENANT}/alert"
        )
        assert server_response.status_code == 200

        assert server_response.json()[0] == expected_response

    @pytest.mark.abort_on_fail
    async def test_given_prometheus_configurer_with_existing_rule_when_delete_alert_rule_then_prometheus_configurer_has_no_rules(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        prometheus_configurer_server_ip = await _unit_address(
            ops_test, PROMETHEUS_CONFIGURER_APP_NAME, 0
        )
        server_response = requests.delete(
            f"http://{prometheus_configurer_server_ip}:9100/{TEST_TENANT}/alert?alert_name={TEST_ALERT_NAME}"  # noqa: E501, W505
        )
        assert server_response.status_code == 204
        # 5 seconds for the Prometheus Configurer to do what needs to process the request
        time.sleep(5)

        server_response = requests.get(
            f"http://{prometheus_configurer_server_ip}:9100/{TEST_TENANT}/alert"
        )
        assert server_response.status_code == 200

        assert server_response.json() == []

    @pytest.mark.abort_on_fail
    async def test_given_prometheus_configurer_with_deleted_rule_when_get_then_prometheus_has_no_rules(  # noqa: E501
        self, ops_test: OpsTest, setup
    ):
        prometheus_rules = await _get_prometheus_rules(ops_test, PROMETHEUS_APP_NAME, 0)
        assert prometheus_rules == []

    @staticmethod
    async def _deploy_prometheus_k8s(ops_test: OpsTest):
        await ops_test.model.deploy(
            PROMETHEUS_APP_NAME,
            application_name=PROMETHEUS_APP_NAME,
            channel="edge",
            trust=True,
        )


async def _unit_address(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Find unit address for any application.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application
        unit_num: integer number of a juju unit

    Returns:
        unit address as a string
    """
    status = await ops_test.model.get_status()
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


async def _get_prometheus_rules(ops_test: OpsTest, app_name: str, unit_num: int) -> list:
    """Fetch all Prometheus rules.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        a list of rule groups.
    """
    host = await _unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    rules = await prometheus.rules()
    return rules
