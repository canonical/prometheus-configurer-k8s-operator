#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import Mock, PropertyMock, patch

from charms.prometheus_k8s.v0.prometheus_remote_write import AlertRules, JujuTopology
from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

from charm import PrometheusConfigurerOperatorCharm

testing.SIMULATE_CAN_CONNECT = True
TEST_MULTITENANT_LABEL = "some_test_label"
TEST_CONFIG = f"""options:
  multitenant_label:
    type: string
    description: |
      Prometheus Configurer has been designed to support multiple tenants. This label can be used
      to restrict the alerting rules in Prometheus, so that each rule can only be triggered by
      metrics with matching label.
    default: {TEST_MULTITENANT_LABEL}
"""


class TestPrometheusConfigurerOperatorCharm(unittest.TestCase):
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self):
        self.harness = testing.Harness(PrometheusConfigurerOperatorCharm, config=TEST_CONFIG)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    @patch("charm.AlertRulesDirWatcher")
    @patch("charm.PrometheusConfigurerOperatorCharm.RULES_DIR", new_callable=PropertyMock)
    def test_given_rules_directory_when_pebble_ready_then_watchdog_starts_watching_given_rules_directory(  # noqa: E501
        self, patched_rules_dir, patched_alert_rules_dir_watcher
    ):
        test_rules_dir = "/test/rules/dir"
        patched_rules_dir.return_value = test_rules_dir
        self.harness.container_pebble_ready("prometheus-configurer")

        patched_alert_rules_dir_watcher.assert_called_with(self.harness.charm, test_rules_dir)

    @patch("charm.AlertRulesDirWatcher", Mock())
    def test_given_prometheus_relation_not_created_when_pebble_ready_then_charm_goes_to_blocked_state(  # noqa: E501
        self,
    ):
        self.harness.container_pebble_ready("prometheus-configurer")

        assert self.harness.charm.unit.status == BlockedStatus(
            "Waiting for prometheus relation to be created"
        )

    @patch("charm.AlertRulesDirWatcher", Mock())
    def test_given_prometheus_relation_created_but_prometheus_configurer_container_not_yet_ready_when_pebble_ready_then_charm_goes_to_waiting_state(  # noqa: E501
        self,
    ):
        self.harness.add_relation("prometheus", "prometheus-k8s")
        testing.SIMULATE_CAN_CONNECT = False
        self.harness.container_pebble_ready("prometheus-configurer")

        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for prometheus-configurer container to be ready"
        )

    @patch("charm.AlertRulesDirWatcher", Mock())
    def test_given_prometheus_relation_created_and_prometheus_configurer_container_ready_but_dummy_http_server_not_yet_ready_when_pebble_ready_then_charm_goes_to_waiting_state(  # noqa: E501
        self,
    ):
        self.harness.add_relation("prometheus", "prometheus-k8s")
        self.harness.set_can_connect("dummy-http-server", True)
        self.harness.container_pebble_ready("prometheus-configurer")

        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for the dummy HTTP server to be ready"
        )

    @patch("charm.PrometheusConfigurerOperatorCharm.RULES_DIR", new_callable=PropertyMock)
    @patch(
        "charm.PrometheusConfigurerOperatorCharm.PROMETHEUS_CONFIGURER_PORT",
        new_callable=PropertyMock,
    )
    @patch(
        "charm.PrometheusConfigurerOperatorCharm.DUMMY_HTTP_SERVER_HOST",
        new_callable=PropertyMock,
    )
    @patch(
        "charm.PrometheusConfigurerOperatorCharm.DUMMY_HTTP_SERVER_PORT",
        new_callable=PropertyMock,
    )
    @patch("charm.AlertRulesDirWatcher", Mock())
    def test_given_prometheus_relation_created_and_prometheus_configurer_container_ready_when_pebble_ready_then_pebble_plan_is_updated_with_correct_pebble_layer(  # noqa: E501
        self,
        patched_dummy_http_server_port,
        patched_dummy_http_server_host,
        patched_prometheus_configurer_port,
        patched_rules_dir,
    ):
        test_dummy_http_server_port = 4321
        test_dummy_http_server_host = "testhost"
        test_prometheus_configurer_port = 1234
        test_rules_dir = "/test/rules/dir"
        patched_dummy_http_server_port.return_value = test_dummy_http_server_port
        patched_dummy_http_server_host.return_value = test_dummy_http_server_host
        patched_prometheus_configurer_port.return_value = test_prometheus_configurer_port
        patched_rules_dir.return_value = test_rules_dir
        self.harness.add_relation("prometheus", "prometheus-k8s")
        self.harness.set_can_connect("dummy-http-server", True)
        self.harness.container_pebble_ready("dummy-http-server")
        expected_plan = {
            "services": {
                "prometheus-configurer": {
                    "override": "replace",
                    "startup": "enabled",
                    "command": "prometheus_configurer "
                    f"-port={test_prometheus_configurer_port} "
                    f"-rules-dir={test_rules_dir}/ "
                    f"-prometheusURL={test_dummy_http_server_host}:{test_dummy_http_server_port} "
                    f"-multitenant-label={TEST_MULTITENANT_LABEL} "
                    "-restrict-queries",
                }
            }
        }

        self.harness.container_pebble_ready("prometheus-configurer")

        updated_plan = self.harness.get_container_pebble_plan("prometheus-configurer").to_dict()
        self.assertEqual(expected_plan, updated_plan)

    def test_given_dummy_http_server_container_ready_when_pebble_ready_then_pebble_plan_is_updated_with_correct_pebble_layer(  # noqa: E501
        self,
    ):
        expected_plan = {
            "services": {
                "dummy-http-server": {
                    "override": "replace",
                    "startup": "enabled",
                    "command": "nginx",
                }
            }
        }
        self.harness.container_pebble_ready("dummy-http-server")

        updated_plan = self.harness.get_container_pebble_plan("dummy-http-server").to_dict()
        self.assertEqual(expected_plan, updated_plan)

    @patch("charm.AlertRulesDirWatcher", Mock())
    def test_given_prometheus_relation_created_and_prometheus_configurer_container_ready_when_pebble_ready_then_charm_goes_to_active_state(  # noqa: E501
        self,
    ):
        self.harness.add_relation("prometheus", "prometheus-k8s")
        self.harness.set_can_connect("dummy-http-server", True)
        self.harness.container_pebble_ready("dummy-http-server")

        self.harness.container_pebble_ready("prometheus-configurer")

        assert self.harness.charm.unit.status == ActiveStatus()

    @patch("charm.PrometheusConfigurerOperatorCharm.RULES_DIR", new_callable=PropertyMock)
    def test_given_valid_rules_file_in_rules_directory_when_alert_rules_changed_then_data_bag_is_updated_with_rule_from_the_directory(  # noqa: E501
        self, patched_rules_dir
    ):
        test_rules_dir = "./tests/unit/test_rules"
        patched_rules_dir.return_value = test_rules_dir
        relation_id = self.harness.add_relation("prometheus", "prometheus-k8s")
        topology = JujuTopology.from_charm(self.harness.charm)
        alert_rules = AlertRules(topology=topology)
        alert_rules.add_path(test_rules_dir, recursive=True)
        alert_rules_as_dict = alert_rules.as_dict()
        self.harness.add_relation_unit(relation_id, "prometheus-k8s/0")

        self.harness.charm.on.alert_rules_changed.emit()

        self.assertEqual(
            self.harness.get_relation_data(relation_id, "prometheus-configurer-k8s")[
                "alert_rules"
            ],
            json.dumps(alert_rules_as_dict),
        )

    @patch(
        "charm.PrometheusConfigurerOperatorCharm.PROMETHEUS_CONFIGURER_SERVICE_NAME",
        new_callable=PropertyMock,
    )
    @patch(
        "charm.PrometheusConfigurerOperatorCharm.PROMETHEUS_CONFIGURER_PORT",
        new_callable=PropertyMock,
    )
    def test_given_prometheus_configurer_service_when_prometheus_configurer_relation_joined_then_prometheus_configurer_service_name_and_port_are_pushed_to_the_relation_data_bag(  # noqa: E501
        self, patched_prometheus_configurer_port, patched_prometheus_configurer_service_name
    ):
        test_prometheus_configurer_service_name = "whatever"
        test_prometheus_configurer_port = 1234
        patched_prometheus_configurer_service_name.return_value = (
            test_prometheus_configurer_service_name
        )
        patched_prometheus_configurer_port.return_value = test_prometheus_configurer_port
        relation_id = self.harness.add_relation(
            "prometheus-configurer", self.harness.charm.app.name
        )
        self.harness.add_relation_unit(relation_id, f"{self.harness.charm.app.name}/0")

        self.assertEqual(
            self.harness.get_relation_data(relation_id, f"{self.harness.charm.app.name}"),
            {
                "service_name": test_prometheus_configurer_service_name,
                "port": str(test_prometheus_configurer_port),
            },
        )
