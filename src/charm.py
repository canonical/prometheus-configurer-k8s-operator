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
from ops.charm import CharmBase, PebbleReadyEvent, RelationJoinedEvent
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    ModelError,
    WaitingStatus,
)
from ops.pebble import Layer

from rules_dir_watcher import AlertRulesChangedCharmEvents, AlertRulesDirWatcher

logger = logging.getLogger(__name__)


class PrometheusConfigurerOperatorCharm(CharmBase):
    RULES_DIR = "/etc/prometheus/rules"
    DUMMY_HTTP_SERVER_HOST = "localhost"
    DUMMY_HTTP_SERVER_SERVICE_NAME = "dummy-http-server"
    DUMMY_HTTP_SERVER_PORT = 80
    PROMETHEUS_CONFIGURER_SERVICE_NAME = "prometheus-configurer"
    PROMETHEUS_CONFIGURER_PORT = 9100

    on = AlertRulesChangedCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self._prometheus_configurer_container_name = (
            self._prometheus_configurer_layer_name
        ) = self._prometheus_configurer_service_name = self.PROMETHEUS_CONFIGURER_SERVICE_NAME
        self._dummy_http_server_container_name = (
            self._dummy_http_server_layer_name
        ) = self._dummy_http_server_service_name = self.DUMMY_HTTP_SERVER_SERVICE_NAME
        self._prometheus_configurer_container = self.unit.get_container(
            self._prometheus_configurer_container_name
        )
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

        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(
            self.on.prometheus_configurer_pebble_ready,
            self._on_prometheus_configurer_pebble_ready,
        )
        self.framework.observe(
            self.on.dummy_http_server_pebble_ready, self._on_dummy_http_server_pebble_ready
        )
        self.framework.observe(self.on.alert_rules_changed, self._on_alert_rules_changed)
        self.framework.observe(
            self.on.prometheus_configurer_relation_joined,
            self._on_prometheus_configurer_relation_joined,
        )

    def _on_start(self, _) -> None:
        """Starts AlertRulesDirWatcher upon unit start."""
        watchdog = AlertRulesDirWatcher(self, self.RULES_DIR)
        watchdog.start_watchdog()

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
        if not self._prometheus_configurer_container.can_connect():
            self.unit.status = WaitingStatus(
                f"Waiting for {self._prometheus_configurer_container_name} container to be ready"
            )
            event.defer()
            return
        if not self._dummy_http_server_running:
            self.unit.status = WaitingStatus("Waiting for the dummy HTTP server to be ready")
            event.defer()
            return
        self._start_prometheus_configurer()
        self.unit.status = ActiveStatus()

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
        plan = self._prometheus_configurer_container.get_plan()
        layer = self._prometheus_configurer_layer
        if plan.services != layer.services:
            self.unit.status = MaintenanceStatus(
                f"Configuring pebble layer for {self._prometheus_configurer_service_name}"
            )
            self._prometheus_configurer_container.add_layer(
                self._prometheus_configurer_container_name, layer, combine=True
            )
            self._prometheus_configurer_container.restart(self._prometheus_configurer_service_name)
            logger.info(f"Restarted container {self._prometheus_configurer_service_name}")

    def _start_dummy_http_server(self):
        """Starts dummy HTTP server service."""
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

    def _on_alert_rules_changed(self, _):
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

    def _on_prometheus_configurer_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handles actions taken when Prometheus Configurer relation joins.

        Returns:
            None
        """
        self._add_service_info_to_relation_data_bag(event)

    def _add_service_info_to_relation_data_bag(self, event: RelationJoinedEvent) -> None:
        """Adds information about Prometheus Configurer service name and port to relation data bag.

        Returns:
            None
        """
        prometheus_configurer_relation = event.relation
        prometheus_configurer_relation.data[self.app][
            "service_name"
        ] = self.PROMETHEUS_CONFIGURER_SERVICE_NAME
        prometheus_configurer_relation.data[self.app]["port"] = str(
            self.PROMETHEUS_CONFIGURER_PORT
        )

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
                    self._prometheus_configurer_service_name: {
                        "override": "replace",
                        "startup": "enabled",
                        "command": "prometheus_configurer "
                        f"-port={str(self.PROMETHEUS_CONFIGURER_PORT)} "
                        f"-rules-dir={self.RULES_DIR}/ "
                        "-prometheusURL="
                        f"{self.DUMMY_HTTP_SERVER_HOST}:{self.DUMMY_HTTP_SERVER_PORT} "
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
    def _dummy_http_server_running(self) -> bool:
        try:
            self._dummy_http_server_container.get_service(self._dummy_http_server_service_name)
            return True
        except ModelError:
            return False


if __name__ == "__main__":
    main(PrometheusConfigurerOperatorCharm)
