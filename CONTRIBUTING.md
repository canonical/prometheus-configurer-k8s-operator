# Contributing to prometheus-configurer-k8s-operator

## Overview

This documents explains the processes and practices recommended for contributing enhancements
or bug fixing to the Prometheus Configurer Charmed Operator.

## Setup

A typical setup using [snaps](https://snapcraft.io/) can be found in the
[Juju docs](https://juju.is/docs/sdk/dev-setup).

## Developing

- Prior to getting started on a pull request, we first encourage you to open an issue explaining
  the use case or bug. This gives other contributors a chance to weigh in early in the process.
- To author PRs you should be familiar with [juju](https://juju.is/#what-is-juju) and
  [how operators are written](https://juju.is/docs/sdk).
- All enhancements require review before being merged. Besides the code quality and test coverage,
  the review will also take into account the resulting user experience for Juju administrators
  using this charm. To be able to merge you would have to rebase onto the `main` branch. We do this
  to avoid merge commits and to have a linear Git history.
- We use [`tox`](https://tox.wiki/en/latest/#) to manage all virtualenvs for the development
  lifecycle.

### Testing
Unit tests are written with the Operator Framework [test harness] and integration tests are written
using [pytest-operator] and [python-libjuju].

The default test environments - lint, static and unit - will run if you start `tox` without
arguments.

You can also manually run a specific test environment:

```shell
tox -e fmt              # update your code according to linting rules
tox -e lint             # code style
tox -e static           # static analysis
tox -e unit             # unit tests
tox -e integration      # integration tests
```

`tox` creates a virtual environment for every tox environment defined in [tox.ini](tox.ini).
To activate a tox environment for manual testing,

```shell
source .tox/unit/bin/activate
```

## Build charm

Build the charm in this git repository using

```shell
charmcraft pack
```

which will create a `*.charm` file you can deploy with:

```shell
juju deploy ./prometheus-configurer-k8s_ubuntu-20.04-amd64.charm \
  --resource prometheus-configurer-image=docker.io/facebookincubator/prometheus-configurer:1.0.4 \
  --resource dummy-http-server-image=ghcr.io/canonical/200-ok:main
```

[test harness]: https://ops.readthedocs.io/en/latest/#module-ops.testing
[pytest-operator]: https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md
[python-libjuju]: https://pythonlibjuju.readthedocs.io/en/latest/
