#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from ops import testing

from charm import PrometheusConfigurerOperatorCharm
from rules_dir_watcher import AlertRulesDirWatcher


class TestRulesDirWatcher(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda charm, ports: None)
    def setUp(self):
        self.harness = testing.Harness(PrometheusConfigurerOperatorCharm)
        self.harness.begin()

    @patch("subprocess.Popen")
    @patch("rules_dir_watcher.LOG_FILE_PATH")
    def test_given_rules_dir_watcher_when_start_watchdog_then_correct_subprocess_is_started(
        self, _, patched_popen
    ):
        test_watch_dir = "/whatever/watch/dir"
        watchdog = AlertRulesDirWatcher(self.harness.charm, test_watch_dir)

        watchdog.start_watchdog()

        call_list = patched_popen.call_args_list
        patched_popen.assert_called_once()
        assert call_list[0].kwargs["args"] == [
            "/usr/bin/python3",
            "src/rules_dir_watcher.py",
            test_watch_dir,
            "/usr/bin/juju-exec",
            self.harness.charm.unit.name,
            self.harness.charm.charm_dir,
        ]
