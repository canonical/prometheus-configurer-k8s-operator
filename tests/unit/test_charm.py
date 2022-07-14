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


class TestPrometheusConfigurerOperatorCharm(unittest.TestCase):
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self):
        self.harness = testing.Harness(PrometheusConfigurerOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    @patch("charm.AlertRulesDirWatcher")
    @patch("charm.PrometheusConfigurerOperatorCharm.RULES_DIR", new_callable=PropertyMock)
    @patch("charm.DummyHTTPServer", Mock())
    def test_given_rules_directory_when_install_event_emitted_then_watchdog_starts_watching_given_rules_directory(  # noqa: E501
        self, patched_rules_dir, patched_alert_rules_dir_watcher
    ):
        test_rules_dir = "/test/rules/dir"
        patched_rules_dir.return_value = test_rules_dir
        self.harness.charm.on.install.emit()

        patched_alert_rules_dir_watcher.assert_called_with(self.harness.charm, test_rules_dir)

    @patch("charm.DummyHTTPServer")
    @patch("charm.PrometheusConfigurerOperatorCharm.DUMMY_SERVER_PORT", new_callable=PropertyMock)
    @patch("charm.AlertRulesDirWatcher", Mock())
    def test_given_prometheus_port_when_install_event_emitted_then_dummy_http_server_is_started_on_correct_port(  # noqa: E501
        self, patched_dummy_server_port, patched_dummy_http_server
    ):
        test_dummy_server_port = 1234
        patched_dummy_server_port.return_value = test_dummy_server_port
        self.harness.charm.on.install.emit()

        patched_dummy_http_server.assert_called_with(self.harness.charm, test_dummy_server_port)

    def test_given_prometheus_relation_not_created_when_pebble_ready_then_charm_goes_to_blocked_state(  # noqa: E501
        self,
    ):
        self.harness.container_pebble_ready("prometheus-configurer")

        assert self.harness.charm.unit.status == BlockedStatus(
            "Waiting for relation(s) to be created: prometheus"
        )

    @patch("charm.PrometheusConfigurerOperatorCharm._relations_created", new_callable=PropertyMock)
    def test_given_prometheus_relation_created_but_container_not_yet_ready_when_pebble_ready_then_charm_goes_to_waiting_state(  # noqa: E501
        self, patched_relations_created
    ):
        patched_relations_created.return_value = True
        testing.SIMULATE_CAN_CONNECT = False
        self.harness.container_pebble_ready("prometheus-configurer")

        assert self.harness.charm.unit.status == WaitingStatus(
            "Waiting for prometheus-configurer container to be ready"
        )

    @patch("charm.PrometheusConfigurerOperatorCharm._relations_created", new_callable=PropertyMock)
    def test_given_prometheus_relation_created_and_container_ready_when_pebble_ready_then_pebble_plan_is_updated_with_correct_pebble_layer(  # noqa: E501
        self, patched_relations_created
    ):
        patched_relations_created.return_value = True
        expected_plan = {
            "services": {
                "prometheus-configurer": {
                    "override": "replace",
                    "startup": "enabled",
                    "command": "prometheus_configurer "
                    "-port=9100 "
                    "-rules-dir=/etc/prometheus/rules/ "
                    "-prometheusURL=127.0.0.1:9090 "
                    "-multitenant-label=networkID "
                    "-restrict-queries",
                }
            }
        }
        self.harness.container_pebble_ready("prometheus-configurer")

        updated_plan = self.harness.get_container_pebble_plan("prometheus-configurer").to_dict()
        self.assertEqual(expected_plan, updated_plan)

    @patch("charm.PrometheusConfigurerOperatorCharm._relations_created", new_callable=PropertyMock)
    def test_given_prometheus_relation_created_and_container_ready_when_pebble_ready_then_charm_goes_to_active_state(  # noqa: E501
        self, patched_relations_created
    ):
        patched_relations_created.return_value = True

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
