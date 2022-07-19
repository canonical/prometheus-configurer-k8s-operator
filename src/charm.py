#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging

from charms.observability_libs.v0.juju_topology import JujuTopology
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
    ServicePort,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import AlertRules
from ops.charm import CharmBase, PebbleReadyEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Layer

from rules_dir_watcher import AlertRulesChangedCharmEvents, AlertRulesDirWatcher

logger = logging.getLogger(__name__)


class PrometheusConfigurerOperatorCharm(CharmBase):
    RULES_DIR = "/etc/prometheus/rules"
    DUMMY_HTTP_SERVER_HOST = "localhost"
    DUMMY_HTTP_SERVER_PORT = 8080
    PROMETHEUS_CONFIGURER_PORT = 9100

    on = AlertRulesChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self._container_name = self._layer_name = self._service_name = "prometheus-configurer"
        self._dummy_http_server_container_name = (
            self._dummy_http_server_layer_name
        ) = self._dummy_http_server_service_name = "dummy-http-server"
        self._container = self.unit.get_container(self._container_name)
        self._dummy_http_server_container = self.unit.get_container(
            self._dummy_http_server_container_name
        )

        self.service_patch = KubernetesServicePatch(
            charm=self,
            ports=[
                ServicePort(name="prom-configmanager", port=self.PROMETHEUS_CONFIGURER_PORT),
                ServicePort(name="dummy-http-server", port=self.DUMMY_HTTP_SERVER_PORT),
            ],
        )

        self.framework.observe(
            self.on.prometheus_configurer_pebble_ready,
            self._on_prometheus_configurer_pebble_ready,
        )
        self.framework.observe(
            self.on.dummy_http_server_pebble_ready, self._on_dummy_http_server_pebble_ready
        )
        self.framework.observe(self.on.alert_rules_changed, self._push_alert_rules)

    def _on_prometheus_configurer_pebble_ready(self, event: PebbleReadyEvent):
        """Checks whether all conditions to start Prometheus Configurer are met and, if yes,
        triggers start of the prometheus-configurer service.
        """
        watchdog = AlertRulesDirWatcher(self, self.RULES_DIR)
        watchdog.start_watchdog()
        if not self.model.get_relation("prometheus"):
            self.unit.status = BlockedStatus("Waiting for prometheus relation to be created")
            event.defer()
            return
        if self._container.can_connect():
            self._start_prometheus_configurer()
            self.unit.status = ActiveStatus()
        else:
            self.unit.status = WaitingStatus(
                f"Waiting for {self._container_name} container to be ready"
            )
            event.defer()

    def _on_dummy_http_server_pebble_ready(self, event: PebbleReadyEvent):
        if self._dummy_http_server_container.can_connect():
            self._start_dummy_http_server()
        else:
            self.unit.status = WaitingStatus(
                f"Waiting for {self._dummy_http_server_container_name} container to be ready"
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

    def _start_dummy_http_server(self):
        """Starts Prometheus Configurer service."""
        plan = self._dummy_http_server_container.get_plan()
        layer = self._dummy_http_server_layer
        if plan.services != layer.services:
            self.unit.status = MaintenanceStatus(
                f"Configuring pebble layer for {self._dummy_http_server_service_name}"
            )
            self._dummy_http_server_container.add_layer(
                self._dummy_http_server_container_name, layer, combine=True
            )
            self._dummy_http_server_container.restart(self._dummy_http_server_service_name)
            logger.info(f"Restarted container {self._dummy_http_server_service_name}")

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
        """Constructs the pebble layer for Prometheus configurer.

        Returns:
            a Pebble layer specification for the Prometheus configurer workload container.
        """
        return Layer(
            {
                "summary": "Prometheus Configurer pebble layer",
                "description": "Pebble layer configuration for Prometheus Configurer",
                "services": {
                    self._service_name: {
                        "override": "replace",
                        "startup": "enabled",
                        "command": "prometheus_configurer "
                        f"-port={str(self.PROMETHEUS_CONFIGURER_PORT)} "
                        f"-rules-dir={self.RULES_DIR}/ "
                        "-prometheusURL="
                        f"{self._prometheus_server_host}:{self._prometheus_server_port} "
                        f'-multitenant-label={self.model.config.get("multitenant_label")} '
                        "-restrict-queries",
                    }
                },
            }
        )

    @property
    def _dummy_http_server_layer(self) -> Layer:
        """Constructs the pebble layer for the dummy HTTP server.

        Returns:
            a Pebble layer specification for the dummy HTTP server workload container.
        """
        return Layer(
            {
                "summary": "Dummy HTTP server pebble layer",
                "description": "Pebble layer configuration for the dummy HTTP server",
                "services": {
                    self._dummy_http_server_service_name: {
                        "override": "replace",
                        "startup": "enabled",
                        "command": "nginx",
                    }
                },
            }
        )

    @property
    def _prometheus_server_host(self) -> str:
        """Returns Prometheus Server's hostname. If none was set in the charm's config,
        built-in dummy HTTP server will be used.
        """
        return self.model.config.get("prometheus_server_host") or self.DUMMY_HTTP_SERVER_HOST

    @property
    def _prometheus_server_port(self) -> int:
        """Returns Prometheus Server's port. If none was set in the charm's config,
        built-in dummy HTTP server will be used.
        """
        return int(self.model.config.get("prometheus_server_port")) or self.DUMMY_HTTP_SERVER_PORT  # type: ignore[arg-type]  # noqa: E501


if __name__ == "__main__":
    main(PrometheusConfigurerOperatorCharm)
