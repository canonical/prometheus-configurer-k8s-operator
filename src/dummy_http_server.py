#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This dummy HTTP server has been implemented to trick Prometheus Configurer. It returns
`200 OK` status on any POST call.
Prometheus Configurer was originally designed to share a volume with the Prometheus Server. After
pushing new alert rules to the shared volume, Prometheus Configurer reloads the configuration
of the Prometheus Server.
Since prometheus-k8s and prometheus-configurer-k8s charms do not share a volume and also
Prometheus Server delivered by the prometheus-k8s charm reloads automatically upon new rules
detection, reload done by the Prometheus Configurer needs to be suppressed or otherwise it
interferes with Prometheus Server's automatic reload, causing relaod failure.
This dummy server's address is given to the `prometheus_configurer` service as the `prometheusURL`
parameter, so that Prometheus Configurer thinks it reloaded Prometheus Server's configuration.
"""

import logging
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from ops.charm import CharmBase
from ops.framework import Object

logger = logging.getLogger(__name__)

LOG_FILE_PATH = "/var/log/prometheus-configurer-dummy-server.log"


class DummyHTTPServer(Object):
    def __init__(self, charm: CharmBase, port: int):
        super().__init__(charm, None)
        self._port = port

    def start_server(self):
        """Starts dummy HTTP server in a new process."""
        logger.info(f"Starting dummy HTTP server on port {self._port}.")

        # We need to trick Juju into thinking that we are not running
        # in a hook context, as Juju will disallow use of juju-run.
        new_env = os.environ.copy()
        if "JUJU_CONTEXT_ID" in new_env:
            new_env.pop("JUJU_CONTEXT_ID")

        pid = subprocess.Popen(
            ["/usr/bin/python3", "src/dummy_http_server.py", f"{self._port}"],
            stdout=open(LOG_FILE_PATH, "a"),
            stderr=subprocess.STDOUT,
            env=new_env,
        ).pid

        logger.info(f"Started dummy HTTP server process with PID {pid}.")


class DummyServer(BaseHTTPRequestHandler):
    def _set_headers(self):
        """Sets the response which will be sent upon calls."""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_POST(self):  # noqa: N802
        """Responds to any POST call."""
        self._set_headers()


def main():
    """Starts the actual HTTP server."""
    port = sys.argv[1]
    server_address = ("", int(port))
    httpd = HTTPServer(server_address, DummyServer)

    httpd.serve_forever()


if __name__ == "__main__":
    main()
