#!/usr/bin/env python3
"""
Kubernetes YAML Validator for QuantTradingSystem/k8s/

Checks:
1. Valid YAML syntax (multi-document aware)
2. Required K8s fields (apiVersion, kind, metadata.name, metadata.namespace)
3. Container ports match service ports
4. Selectors match labels
5. PVC names match volume claim refs
6. Secret/ConfigMap references are consistent
7. Health check paths match actual service endpoints (best-effort)
8. Image references are consistent (ghcr.io/quant-trading/* for app images)
"""

import sys
import os
import re
import yaml
from collections import defaultdict

K8S_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Known good external image prefixes (allowlist) ──
EXTERNAL_IMAGE_PREFIXES = (
    "timescale/timescaledb:",
    "redis:",
    "rabbitmq:",
    "docker.elastic.co/elasticsearch/",
    "docker.elastic.co/kibana/",
    "docker.elastic.co/logstash/",
    "questdb/questdb:",
    "prom/prometheus:",
    "grafana/grafana:",
    "busybox:",
)

# ── Health check paths that are expected per service (heuristic) ──
EXPECTED_HEALTH_PATHS = {
    "strategy-service": ["/health", "/metrics"],
    "execution-service": ["/health", "/metrics"],
    "ai-scheduler":      ["/health", "/metrics"],
    "dashboard":         ["/index.html"],
    "prometheus":        ["/-/healthy", "/-/ready"],
    "grafana":           ["/grafana/api/health"],
    "kibana":            ["/kibana/api/status"],
    "elasticsearch":     ["/_cluster/health"],
    "questdb":           ["/status"],
}

# ── Errors & Warnings ──
errors = []
warnings = []

def report(level, file_name, doc_index, kind, name, msg):
    entry = {
        "level": level,
        "file": os.path.basename(file_name),
        "doc": doc_index,
        "kind": kind,
        "name": name,
        "msg": msg,
    }
    if level == "ERROR":
        errors.append(entry)
    else:
        warnings.append(entry)


def load_all_yaml(filepath):
    """Load all YAML documents from a file."""
    with open(filepath, "r") as f:
        docs = list(yaml.safe_load_all(f))
    return [d for d in docs if d is not None]


def flatten_docs(all_files):
    """Parse every file and return a flat list of (filepath, doc_index, doc)."""
    flat = []
    for fp in all_files:
        try:
            docs = load_all_yaml(fp)
        except yaml.YAMLError as exc:
            errors.append({
                "level": "ERROR",
                "file": os.path.basename(fp),
                "doc": "N/A",
                "kind": "N/A",
                "name": "N/A",
                "msg": f"YAML parse error: {exc}",
            })
            continue
        for i, doc in enumerate(docs):
            flat.append((fp, i, doc))
    return flat


def check_required_fields(fp, idx, doc):
    """Check 2: required K8s fields."""
    kind = doc.get("kind", "<missing>")
    name = doc.get("metadata", {}).get("name", "<missing>")
    api_version = doc.get("apiVersion")

    if not api_version:
        report("ERROR", fp, idx, kind, name, "Missing apiVersion")
    if not kind:
        report("ERROR", fp, idx, kind, name, "Missing kind")
        return  # can't continue
    if "metadata" not in doc or not isinstance(doc["metadata"], dict):
        report("ERROR", fp, idx, kind, "<missing>", "Missing metadata")
        return

    meta = doc["metadata"]
    if not meta.get("name"):
        report("ERROR", fp, idx, kind, "<missing>", "Missing metadata.name")

    # Namespace is NOT required for Namespace kind or cluster-scoped resources
    cluster_scoped = kind in ("Namespace", "PersistentVolume", "ClusterRole", "ClusterRoleBinding",
                               "StorageClass", "CustomResourceDefinition")
    if not cluster_scoped and not meta.get("namespace"):
        report("WARN", fp, idx, kind, name, "Missing metadata.namespace (not cluster-scoped)")


def check_service_port_matching(services, workloads, flat_docs):
    """Check 3: container ports in workloads match targetPort in Services."""
    # Build service port map: service_name -> {port_name: targetPort}
    svc_ports = defaultdict(dict)
    for fp, idx, doc in flat_docs:
        if doc.get("kind") == "Service":
            svc_name = doc["metadata"]["name"]
            for p in doc.get("spec", {}).get("ports", []):
                svc_ports[svc_name][p.get("name", str(p["port"]))] = p.get("targetPort", p["port"])

    # Check workloads
    for fp, idx, doc in flat_docs:
        kind = doc.get("kind")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        wl_name = doc["metadata"]["name"]
        containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        for c in containers:
            c_ports = {p.get("name", str(p["containerPort"])): p["containerPort"]
                       for p in c.get("ports", [])}

        # Find service(s) that target this workload by label matching
        wl_labels = (doc.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {}))
        for svc_name, svc_port_map in svc_ports.items():
            if svc_name != wl_name and wl_name not in svc_name:
                continue  # skip obviously unrelated services
            for pname, tport in svc_port_map.items():
                if tport is None:
                    continue
                # Check if any container exposes this port
                found = any(cp == tport for cp in c_ports.values())
                if not found:
                    # Only flag if the service name clearly relates to this workload
                    if svc_name == wl_name or wl_name in svc_name:
                        report("WARN", fp, idx, kind, wl_name,
                               f"Service '{svc_name}' targetPort {tport} not found in any container port {list(c_ports.values())}")


def check_selector_label_match(services, flat_docs):
    """Check 4: Service selectors match pod template labels in workloads."""
    # Build workload label map: workload_name -> pod_template_labels
    wl_labels = {}
    for fp, idx, doc in flat_docs:
        kind = doc.get("kind")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        name = doc["metadata"]["name"]
        pt_labels = doc.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
        if pt_labels:
            wl_labels[name] = pt_labels

    # Also check matchLabels vs template labels within workloads
    for fp, idx, doc in flat_docs:
        kind = doc.get("kind")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        name = doc["metadata"]["name"]
        selector = doc.get("spec", {}).get("selector", {}).get("matchLabels", {})
        pt_labels = doc.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
        if selector and pt_labels:
            # Every selector key must be present in pod template labels with same value
            for k, v in selector.items():
                if pt_labels.get(k) != v:
                    report("ERROR", fp, idx, kind, name,
                           f"Selector matchLabels '{{ {k}: {v} }}' not found in pod template labels {pt_labels}")

    # Check Service selectors match workload labels
    for fp, idx, doc in flat_docs:
        if doc.get("kind") != "Service":
            continue
        svc_name = doc["metadata"]["name"]
        svc_sel = doc.get("spec", {}).get("selector", {})
        if not svc_sel:
            report("WARN", fp, idx, "Service", svc_name, "Service has no selector")
            continue
        # Try to find a matching workload
        matched = False
        for wl_name, wl_lbl in wl_labels.items():
            if all(wl_lbl.get(k) == v for k, v in svc_sel.items()):
                matched = True
                break
        if not matched:
            report("WARN", fp, idx, "Service", svc_name,
                   f"No workload found with labels matching selector {svc_sel}. "
                   f"Known workload labels: { {k: dict(v) for k, v in list(wl_labels.items())[:5]} }")


def check_pvc_consistency(flat_docs):
    """Check 5: PVC names match volume claimRefs."""
    # Collect all defined PVC names
    pvc_names = set()
    for fp, idx, doc in flat_docs:
        if doc.get("kind") == "PersistentVolumeClaim":
            pvc_names.add(doc["metadata"]["name"])

    # Collect all PVC references in volumes
    for fp, idx, doc in flat_docs:
        kind = doc.get("kind")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet", "Pod"):
            continue
        name = doc["metadata"]["name"]
        volumes = doc.get("spec", {}).get("template", {}).get("spec", {}).get("volumes", [])
        for v in volumes:
            pvc_ref = v.get("persistentVolumeClaim", {}).get("claimName")
            if pvc_ref and pvc_ref not in pvc_names:
                report("ERROR", fp, idx, kind, name,
                       f"PVC claimName '{pvc_ref}' references a PVC not defined in these files")


def check_config_secret_refs(flat_docs):
    """Check 6: Secret/ConfigMap refs point to existing resources."""
    # Collect all defined ConfigMaps and Secrets
    cm_names = set()
    secret_names = set()
    for fp, idx, doc in flat_docs:
        kind = doc.get("kind")
        if kind == "ConfigMap":
            cm_names.add(doc["metadata"]["name"])
        elif kind == "Secret":
            secret_names.add(doc["metadata"]["name"])

    for fp, idx, doc in flat_docs:
        kind = doc.get("kind")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet", "Pod"):
            continue
        name = doc["metadata"]["name"]
        containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        init_containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("initContainers", [])
        all_containers = containers + init_containers

        for c in all_containers:
            c_name = c.get("name", "<unknown>")
            for env_from in c.get("envFrom", []):
                cm_ref = env_from.get("configMapRef", {}).get("name")
                if cm_ref and cm_ref not in cm_names:
                    report("ERROR", fp, idx, kind, name,
                           f"Container '{c_name}' envFrom.configMapRef '{cm_ref}' not found")
                sec_ref = env_from.get("secretRef", {}).get("name")
                if sec_ref and sec_ref not in secret_names:
                    report("ERROR", fp, idx, kind, name,
                           f"Container '{c_name}' envFrom.secretRef '{sec_ref}' not found")

        # Also check volumes referencing ConfigMaps/Secrets
        volumes = doc.get("spec", {}).get("template", {}).get("spec", {}).get("volumes", [])
        for v in volumes:
            cm_vol = v.get("configMap", {}).get("name")
            if cm_vol and cm_vol not in cm_names:
                report("ERROR", fp, idx, kind, name,
                       f"Volume '{v.get('name','?')}' configMap name '{cm_vol}' not found")
            sec_vol = v.get("secret", {}).get("secretName")
            if sec_vol and sec_vol not in secret_names:
                report("ERROR", fp, idx, kind, name,
                       f"Volume '{v.get('name','?')}' secretName '{sec_vol}' not found")


def check_health_check_paths(flat_docs):
    """Check 7: Health check paths match expected service endpoints."""
    for fp, idx, doc in flat_docs:
        kind = doc.get("kind")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        name = doc["metadata"]["name"]
        containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        for c in containers:
            c_name = c.get("name", name)
            for probe_type in ("livenessProbe", "readinessProbe", "startupProbe"):
                probe = c.get(probe_type)
                if not probe:
                    continue
                http_get = probe.get("httpGet")
                if not http_get:
                    continue
                path = http_get.get("path", "")
                port = http_get.get("port")

                # Check port matches a declared container port
                declared_ports = [p["containerPort"] for p in c.get("ports", [])]
                if port and port not in declared_ports:
                    report("WARN", fp, idx, kind, name,
                           f"{probe_type} port {port} not in declared container ports {declared_ports}")

                # Heuristic: known bad health paths (these are obviously wrong patterns)
                if path.startswith("/grafana/") or path.startswith("/kibana/"):
                    # These are sub-path prefixed - Grafana/Kibana use these when behind reverse proxy
                    # This is expected in this setup
                    pass
                if path and path not in ("/health", "/metrics", "/-/healthy", "/-/ready",
                                          "/grafana/api/health", "/kibana/api/status",
                                          "/_cluster/health", "/_cluster/health?wait_for_status=yellow&timeout=5s",
                                          "/status", "/index.html"):
                    report("WARN", fp, idx, kind, name,
                           f"Unusual {probe_type} path: '{path}' — verify this endpoint exists")


def check_image_consistency(flat_docs):
    """Check 8: Application images use ghcr.io/quant-trading/* pattern."""
    APP_PREFIX = "ghcr.io/quant-trading/"
    for fp, idx, doc in flat_docs:
        kind = doc.get("kind")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet", "Pod"):
            continue
        name = doc["metadata"]["name"]
        containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        init_containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("initContainers", [])
        all_containers = containers + init_containers

        for c in all_containers:
            img = c.get("image", "")
            if not img:
                report("ERROR", fp, idx, kind, name, f"Container '{c.get('name','?')}' has no image")
                continue

            # Skip init containers with known helper images
            if img.startswith("busybox:"):
                continue

            # Skip known external infrastructure images
            is_external = any(img.startswith(pref) for pref in EXTERNAL_IMAGE_PREFIXES)
            if is_external:
                continue

            # Application images should use ghcr.io/quant-trading/*
            if not img.startswith(APP_PREFIX):
                report("ERROR", fp, idx, kind, name,
                       f"Container '{c.get('name','?')}' image '{img}' does not match expected pattern '{APP_PREFIX}*'")
            elif ":latest" in img or not re.search(r":v?\d+\.\d+", img):
                report("WARN", fp, idx, kind, name,
                       f"Container '{c.get('name','?')}' uses non-pinned image tag: '{img}'")


def check_hpa_targets(flat_docs):
    """Validate HPA scaleTargetRef points to existing Deployments."""
    deployment_names = set()
    for fp, idx, doc in flat_docs:
        if doc.get("kind") == "Deployment":
            deployment_names.add(doc["metadata"]["name"])

    for fp, idx, doc in flat_docs:
        if doc.get("kind") != "HorizontalPodAutoscaler":
            continue
        name = doc["metadata"]["name"]
        target_name = doc.get("spec", {}).get("scaleTargetRef", {}).get("name")
        if target_name and target_name not in deployment_names:
            report("ERROR", fp, idx, "HPA", name,
                   f"scaleTargetRef '{target_name}' not found among defined Deployments: {sorted(deployment_names)}")


def check_port_consistency_across_files(flat_docs):
    """Cross-check: Service DNS URLs in ConfigMaps match actual service ports."""
    # Collect service ports
    svc_ports = {}
    for fp, idx, doc in flat_docs:
        if doc.get("kind") == "Service":
            svc_name = doc["metadata"]["name"]
            svc_ports[svc_name] = [p["port"] for p in doc.get("spec", {}).get("ports", [])]

    # Check ConfigMap data for URLs with wrong ports
    for fp, idx, doc in flat_docs:
        if doc.get("kind") != "ConfigMap":
            continue
        cm_name = doc["metadata"]["name"]
        data = doc.get("data", {})
        for key, value in data.items():
            if not isinstance(value, str):
                continue
            # Find URL patterns with service names and ports
            # e.g., http://strategy-service.quant-trading.svc.cluster.local:8000
            for svc_name, ports in svc_ports.items():
                pattern = rf'{svc_name}\.quant-trading\.svc\.cluster\.local:(\d+)'
                matches = re.findall(pattern, value)
                for m in matches:
                    port = int(m)
                    if port not in ports:
                        report("ERROR", fp, idx, "ConfigMap", cm_name,
                               f"ConfigMap '{key}' references {svc_name} on port {port}, "
                               f"but service exposes ports {ports}")


def main():
    yaml_files = sorted([
        os.path.join(K8S_DIR, f) for f in os.listdir(K8S_DIR)
        if f.endswith(('.yaml', '.yml')) and not f.startswith('validate_')
    ])

    if not yaml_files:
        print("No YAML files found!")
        sys.exit(1)

    print(f"Validating {len(yaml_files)} YAML files in {K8S_DIR}\n{'='*70}")

    # Phase 1: Parse all files
    flat_docs = flatten_docs(yaml_files)
    print(f"Parsed {len(flat_docs)} Kubernetes resources from {len(yaml_files)} files.")

    # Phase 2: Check 1 - YAML syntax (done during flatten_docs)
    # Phase 2 cont: Check 2 - Required fields
    print("\n[2] Checking required K8s fields...")
    for fp, idx, doc in flat_docs:
        check_required_fields(fp, idx, doc)

    # Phase 3: Check 3 - Service port matching
    print("[3] Checking container ports match service ports...")
    services = [d for _, _, d in flat_docs if d.get("kind") == "Service"]
    workloads = [d for _, _, d in flat_docs if d.get("kind") in ("Deployment", "StatefulSet")]
    check_service_port_matching(services, workloads, flat_docs)

    # Phase 4: Check 4 - Selector/label matching
    print("[4] Checking selectors match labels...")
    check_selector_label_match(services, flat_docs)

    # Phase 5: Check 5 - PVC consistency
    print("[5] Checking PVC references...")
    check_pvc_consistency(flat_docs)

    # Phase 6: Check 6 - Secret/ConfigMap refs
    print("[6] Checking Secret/ConfigMap references...")
    check_config_secret_refs(flat_docs)

    # Phase 7: Check 7 - Health check paths
    print("[7] Checking health check paths...")
    check_health_check_paths(flat_docs)

    # Phase 8: Check 8 - Image consistency
    print("[8] Checking image references...")
    check_image_consistency(flat_docs)

    # Bonus checks
    print("[+] Checking HPA targets...")
    check_hpa_targets(flat_docs)

    print("[+] Checking cross-file port consistency...")
    check_port_consistency_across_files(flat_docs)

    # ── Report ──
    print("\n" + "=" * 70)
    print("VALIDATION REPORT")
    print("=" * 70)

    if errors:
        print(f"\n❌ ERRORS: {len(errors)}")
        print("-" * 50)
        for e in errors:
            print(f"  [{e['file']}] doc#{e['doc']} {e['kind']}/{e['name']}")
            print(f"     → {e['msg']}")
    else:
        print("\n✅ No errors found!")

    if warnings:
        print(f"\n⚠️  WARNINGS: {len(warnings)}")
        print("-" * 50)
        for w in warnings:
            print(f"  [{w['file']}] doc#{w['doc']} {w['kind']}/{w['name']}")
            print(f"     → {w['msg']}")
    else:
        print("\n✅ No warnings!")

    print(f"\nSummary: {len(errors)} error(s), {len(warnings)} warning(s) across {len(flat_docs)} resources in {len(yaml_files)} files.")

    # Exit code
    if errors:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
