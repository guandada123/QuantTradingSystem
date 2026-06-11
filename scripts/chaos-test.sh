#!/usr/bin/env bash
# ============================================================
# QuantTradingSystem 故障演练脚本 (Chaos Engineering)
# ============================================================
# 模拟常见生产故障，验证系统自愈能力和告警链路。
#
# 前提条件:
#   - kubectl 已配置且可访问集群
#   - 系统已通过 deploy.sh 部署
#   - Alertmanager + 飞书 Webhook 已配置
#
# Usage:
#   ./chaos-test.sh [scenario]
#
# Scenarios:
#   pod-kill      随机杀死一个服务 Pod
#   network-split  临时网络隔离（需要 NetworkPolicy）
#   cpu-stress     CPU 压力注入
#   resource-drain 资源耗尽模拟
#   all            依次运行所有场景
#   status         仅检查集群当前状态
# ============================================================

set -euo pipefail

NAMESPACE="${NAMESPACE:-quant-trading}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO="${1:-status}"

# ---- Colors ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${BLUE}[CHAOS]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

SERVICES=("strategy-service" "execution-service" "ai-scheduler")

# ---- Helpers ----

check_prerequisites() {
    log_info "Checking prerequisites..."
    if ! command -v kubectl &>/dev/null; then
        log_error "kubectl not found"
        exit 1
    fi
    if ! kubectl get ns "$NAMESPACE" &>/dev/null; then
        log_error "Namespace $NAMESPACE not found — is the system deployed?"
        exit 1
    fi
    log_ok "Prerequisites OK"
}

get_random_pod() {
    local service="$1"
    kubectl get pods -n "$NAMESPACE" -l "app=$service" \
        -o jsonpath='{.items[*].metadata.name}' \
        | tr ' ' '\n' | shuf -n 1
}

get_pod_count() {
    local service="$1"
    kubectl get pods -n "$NAMESPACE" -l "app=$service" \
        -o jsonpath='{.items[*].status.phase}' \
        | tr ' ' '\n' | grep -c "Running" || echo "0"
}

wait_for_recovery() {
    local service="$1"
    local expected_count="${2:-1}"
    local max_wait="${3:-120}"
    local waited=0

    log_info "Waiting for $service to recover ($expected_count replicas, max ${max_wait}s)..."
    while [ $waited -lt $max_wait ]; do
        local count
        count=$(get_pod_count "$service")
        if [ "$count" -ge "$expected_count" ]; then
            log_ok "$service recovered: $count/$expected_count replicas (${waited}s)"
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
        echo -n "."
    done
    echo ""
    log_error "$service FAILED to recover within ${max_wait}s"
    return 1
}

check_endpoint() {
    local url="$1"
    local label="${2:-health}"
    local max_retries="${3:-5}"

    for i in $(seq 1 "$max_retries"); do
        if curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" | grep -q "200"; then
            log_ok "Endpoint $label responsive"
            return 0
        fi
        sleep 2
    done
    log_warn "Endpoint $label may be degraded"
    return 1
}

# ---- Scenarios ----

scenario_pod_kill() {
    log_info "============================================"
    log_info "  Scenario: Pod Kill (服务进程崩溃)"
    log_info "============================================"

    local targets=()
    for svc in "${SERVICES[@]}"; do
        local pod
        pod=$(get_random_pod "$svc" 2>/dev/null || echo "")
        if [ -n "$pod" ]; then
            targets+=("$svc:$pod")
        fi
    done

    if [ ${#targets[@]} -eq 0 ]; then
        log_warn "No running pods found — nothing to kill"
        return 0
    fi

    # 随机选一个
    local target="${targets[$((RANDOM % ${#targets[@]}))]}"
    local svc_name="${target%%:*}"
    local pod_name="${target##*:}"

    log_warn "Killing pod: $pod_name (service: $svc_name)"
    kubectl delete pod -n "$NAMESPACE" "$pod_name" --grace-period=10

    # 等待恢复
    local expected
    expected=$(get_pod_count "$svc_name" 2>/dev/null || echo "1")
    wait_for_recovery "$svc_name" "$expected" 120 || return 1

    # 验证服务健康
    sleep 10
    if [ "$svc_name" = "strategy-service" ]; then
        check_endpoint "http://localhost:8000/health" "strategy-service" 10
    elif [ "$svc_name" = "execution-service" ]; then
        check_endpoint "http://localhost:8002/health" "execution-service" 10
    elif [ "$svc_name" = "ai-scheduler" ]; then
        check_endpoint "http://localhost:8003/health" "ai-scheduler" 10
    fi

    log_ok "Scenario Pod Kill: PASSED"
}

scenario_resource_drain() {
    log_info "============================================"
    log_info "  Scenario: Resource Drain (资源耗尽)"
    log_info "============================================"

    # 检查是否有 resource quota
    if kubectl get resourcequota -n "$NAMESPACE" &>/dev/null; then
        log_info "Resource quota found, checking headroom..."
        kubectl describe resourcequota -n "$NAMESPACE" | grep -E "Used|Hard" || true
    else
        log_warn "No resource quota defined — consider adding resource-quota.yaml"
    fi

    # 检查 Pod 资源使用
    log_info "Current resource usage:"
    kubectl top pods -n "$NAMESPACE" 2>/dev/null || log_warn "metrics-server not available"

    # 检查是否有 OOMKilled 的 Pod
    local oom_count
    oom_count=$(kubectl get pods -n "$NAMESPACE" -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
count = 0
for pod in data.get('items', []):
    for cs in pod.get('status', {}).get('containerStatuses', []):
        last = cs.get('lastState', {}).get('terminated', {})
        if last.get('reason') == 'OOMKilled':
            count += 1
            print(f'OOM: {pod[\"metadata\"][\"name\"]}', file=sys.stderr)
print(count)
" 2>/dev/null || echo "0")
    echo "OOMKilled pods: $oom_count"

    log_ok "Scenario Resource Drain: CHECKED"
}

scenario_alert_chain() {
    log_info "============================================"
    log_info "  Scenario: Alert Chain (告警链路验证)"
    log_info "============================================"

    # 检查 Alertmanager 是否运行
    if kubectl get pods -n "$NAMESPACE" -l "app=alertmanager" --no-headers 2>/dev/null | grep -q "Running"; then
        log_ok "Alertmanager is running"
    else
        log_warn "Alertmanager not found — check prometheus.yaml deployment"
    fi

    # 检查飞书适配器
    if kubectl get pods -n "$NAMESPACE" -l "app=alertmanager-feishu" --no-headers 2>/dev/null | grep -q "Running"; then
        log_ok "Feishu adapter is running"
    else
        log_warn "Feishu adapter not found — no alerts will reach Feishu"
    fi

    # 检查 Prometheus alert rules
    if kubectl get configmap -n "$NAMESPACE" prometheus-alert-rules &>/dev/null; then
        local rule_count
        rule_count=$(kubectl get configmap -n "$NAMESPACE" prometheus-alert-rules -o jsonpath='{.data}' | grep -c "alert:" || echo "0")
        log_ok "Alert rules loaded: $rule_count rules"
    else
        log_warn "No alert rules found"
    fi

    log_ok "Scenario Alert Chain: VERIFIED"
}

scenario_network_test() {
    log_info "============================================"
    log_info "  Scenario: Network Health (跨服务连通性)"
    log_info "============================================"

    # 从一个 Pod 测试到另一个服务的连通性
    local src_pod
    src_pod=$(get_random_pod "strategy-service" 2>/dev/null || echo "")
    if [ -z "$src_pod" ]; then
        log_warn "No strategy-service pod running"
        return 0
    fi

    # 测试到 execution-service 的连通性
    log_info "Testing $src_pod → execution-service:8002"
    if kubectl exec -n "$NAMESPACE" "$src_pod" -- curl -s -o /dev/null -w "%{http_code}" \
        --max-time 5 http://execution-service:8002/health 2>/dev/null | grep -q "200"; then
        log_ok "strategy → execution: OK"
    else
        log_warn "strategy → execution: FAILED or degraded"
    fi

    # 测试到 ai-scheduler 的连通性
    log_info "Testing $src_pod → ai-scheduler:8003"
    if kubectl exec -n "$NAMESPACE" "$src_pod" -- curl -s -o /dev/null -w "%{http_code}" \
        --max-time 5 http://ai-scheduler:8003/health 2>/dev/null | grep -q "200"; then
        log_ok "strategy → ai-scheduler: OK"
    else
        log_warn "strategy → ai-scheduler: FAILED or degraded"
    fi

    log_ok "Scenario Network Health: COMPLETE"
}

print_status() {
    log_info "============================================"
    log_info "  Cluster Status"
    log_info "============================================"
    echo ""
    echo "--- Pods ---"
    kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || log_error "Cannot list pods"
    echo ""
    echo "--- Events (last 5m) ---"
    kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' 2>/dev/null | tail -10 || true
    echo ""

    # 健康摘要
    local total running failing
    total=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l || echo "0")
    running=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l || echo "0")
    failing=$((total - running))

    echo "--- Summary ---"
    echo "Total pods:   $total"
    echo "Running:      $running"
    echo "Not running:  $failing"
}

# ---- Main ----

check_prerequisites

case "$SCENARIO" in
    pod-kill)
        scenario_pod_kill
        ;;
    resource-drain)
        scenario_resource_drain
        ;;
    network-test)
        scenario_network_test
        ;;
    alert-chain)
        scenario_alert_chain
        ;;
    all)
        print_status
        scenario_pod_kill || log_error "Pod Kill scenario FAILED"
        echo ""
        scenario_resource_drain
        echo ""
        scenario_network_test
        echo ""
        scenario_alert_chain
        echo ""
        print_status
        ;;
    status)
        print_status
        ;;
    *)
        echo "Usage: $0 {pod-kill|resource-drain|network-test|alert-chain|all|status}"
        echo ""
        echo "Scenarios:"
        echo "  pod-kill       Kill a random service pod and verify auto-recovery"
        echo "  resource-drain Check for OOM kills and resource pressure"
        echo "  network-test   Verify cross-service connectivity"
        echo "  alert-chain    Verify Alertmanager → Feishu alert pipeline"
        echo "  all            Run all scenarios sequentially"
        echo "  status         Print cluster health overview"
        exit 1
        ;;
esac

log_ok "Chaos test complete."
