# Prometheus Configurer Charmed Operator

## Description

The Prometheus Configurer Charmed Operator provides an HTTP-based API for managing 
[Prometheus](https://prometheus.io) alerting rules.

[Juju](https://juju.is/) charm in this repository has been designed to supplement 
[prometheus-k8s] charm. It leverages the `prometheus_remote_write` interface, provided by the 
[prometheus-k8s], to send over the alerting rules to the Prometheus Server inside the 
[Juju](https://juju.is/) relation data bag.

Full description of the API is available in [github].

[prometheus-k8s]: https://github.com/canonical/prometheus-k8s-operator
[github]: https://github.com/facebookarchive/prometheus-configmanager/blob/main/prometheus/docs/swagger.yaml

## Usage

### Deployment

The Prometheus Configurer Charmed Operator may be deployed using the Juju command line as in:

```bash
juju deploy prometheus-configurer-k8s
```

### Relating to the Prometheus Server

```bash
juju deploy prometheus-k8s
juju relate prometheus-configurer-k8s prometheus-k8s:receive-remote-write
```

### Configuring alert rules via prometheus-configurer

Prometheus Configurer exposes an HTTP API which allows managing Prometheus's alerting rules.
The API is available at port 9100 on the IP address of the charm unit. This unit and its IP address
may be determined using the `juju status` command.<br>
Full description of Prometheus Configurer's API is available in
[github](https://github.com/facebookarchive/prometheus-configmanager/blob/main/prometheus/docs/swagger-v1.yml).

By default, Prometheus Configurer supports multitenancy, hence all alerting rules added using
Prometheus Configurer will be augmented with the `tenant_id` passed in the endpoint URL.<br>
Example:

```yaml
alert: CPUOverUse
expr: process_cpu_seconds_total > 0.12
for: 0m
labels:
  severity: Low
annotations:
  summary: "Rule summary."
  description: "Rule description."
```

Adding above rule using Prometheus Configurer can be done by running below POST:

```bash
curl -X POST http://<PROMETHEUS CONFIGURER CHARM UNIT IP>:9100/<TENANT_ID>/alert 
  -H 'Content-Type: application/json' 
  -d '{"alert": "CPUOverUse", "expr": "process_cpu_seconds_total > 0.12", "for": "0m", "labels": {"severity": "Low"}, "annotations": {"summary": "Rule summary.", "description": "Rule description."}}'
```

To get tenant's alert rules:

```bash
curl -X GET http://<PROMETHEUS CONFIGURER CHARM UNIT IP>:9100/<TENANT_ID>/alert
```

To delete tenant's alert rule:

```bash
curl -X DELETE http://<PROMETHEUS CONFIGURER CHARM UNIT IP>:9100/<TENANT_ID>/alert?alert_name=<RULE_NAME>
```

## OCI Images

- [facebookincubator/prometheus-configurer](https://hub.docker.com/r/facebookincubator/prometheus-configurer)
