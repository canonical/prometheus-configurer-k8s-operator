#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging

from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_remote_write import AlertRules, JujuTopology
from ops.charm import CharmBase, PebbleReadyEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer

from dummy_http_server import DummyHTTPServer
from rules_dir_watcher import AlertRulesChangedCharmEvents, AlertRulesDirWatcher

logger = logging.getLogger(__name__)


class PrometheusConfigurerOperatorCharm(CharmBase):
    RULES_DIR = "/etc/prometheus/rules"
    DUMMY_SERVER_PORT = 9090
    REQUIRED_RELATIONS = ["prometheus"]

    on = AlertRulesChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self._container_name = self._layer_name = self._service_name = "prometheus-configurer"
        self._container = self.unit.get_container(self._container_name)
        self._prometheus_configurer_port = 9100

        self.service_patch = KubernetesServicePatch(
            self, [("prom-configmanager", self._prometheus_configurer_port)]
        )

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.prometheus_configurer_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.alert_rules_changed, self._push_alert_rules)

    def _on_install(self, _):
        """Starts watchdog and dummy HTTP server."""
        watchdog = AlertRulesDirWatcher(self, self.RULES_DIR)
        watchdog.start_watchdog()
        dummy_http_server = DummyHTTPServer(self, self.DUMMY_SERVER_PORT)
        dummy_http_server.start_server()

    def _on_pebble_ready(self, event: PebbleReadyEvent):
        """Checks whether all conditions to start Prometheus Configurer are met and, if yes,
        triggers start of the prometheus-configurer service.
        """
        if not self.model.get_relation("prometheus"):
            self.unit.status = BlockedStatus("Waiting for prometheus relation to be created")
            event.defer()
            return
        if self._container.can_connect():
            self._start_prometheus_configurer()
        else:
            self.unit.status = WaitingStatus(
                f"Waiting for {self._container_name} container to be ready"
            )
            event.defer()

    def _start_prometheus_configurer(self):
        """Starts Prometheus Configurer service."""
        plan = self._container.get_plan()
        layer = self._prometheus_configurer_layer
        if plan.services != layer.services:
            self.unit.status = MaintenanceStatus(
                f"Configuring pebble layer for {self._service_name}"
            )
            self._container.add_layer(self._container_name, layer, combine=True)
            self._container.restart(self._service_name)
            logger.info(f"Restarted container {self._service_name}")
            self.unit.status = ActiveStatus()

    def _push_alert_rules(self, _):
        """Pushes alert rules to Prometheus through the relation data bag."""
        topology = JujuTopology.from_charm(self)
        alert_rules = AlertRules(topology=topology)
        alert_rules.add_path(self.RULES_DIR, recursive=True)
        alert_rules_as_dict = alert_rules.as_dict()
        alert_rules_content = (
            alert_rules_as_dict if alert_rules_as_dict["groups"][0]["rules"] else []
        )
        if alert_rules_as_dict:
            prometheus_relation = self.model.get_relation("prometheus")
            prometheus_relation.data[self.app]["alert_rules"] = json.dumps(alert_rules_content)  # type: ignore[union-attr]  # noqa: E501

    @property
    def _prometheus_configurer_layer(self) -> Layer:
        """Construct the pebble layer for Prometheus configurer.

        Returns:
            a Pebble layer specification for the Prometheus configurer workload container.
        """
        return Layer(
            {
                "summary": "Prometheus Configurer layer",
                "description": "Pebble layer configuration for Prometheus Configurer",
                "services": {
                    self._service_name: {
                        "override": "replace",
                        "startup": "enabled",
                        "command": "prometheus_configurer "
                        f"-port={str(self._prometheus_configurer_port)} "
                        f"-rules-dir={self.RULES_DIR}/ "
                        f"-prometheusURL=127.0.0.1:{self.DUMMY_SERVER_PORT} "
                        f'-multitenant-label={self.model.config.get("multitenant_label")} '
                        "-restrict-queries",
                    }
                },
            }
        )


if __name__ == "__main__":
    main(PrometheusConfigurerOperatorCharm)
