#!/usr/bin/env bash
# ============================================================
# QuantTradingSystem K8s Deployment Script
# ============================================================
# Deploys the full QuantTradingSystem stack to Kubernetes.
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - ingress-nginx controller installed
#   - storage class "standard" available
#   - Docker images built and pushed to registry
#
# Usage:
#   ./deploy.sh [deploy|status|logs|cleanup|port-forward]
#
# Options:
#   deploy       Deploy the entire stack
#   status       Show deployment status
#   logs         Tail logs from all services
#   cleanup      Remove all resources
#   port-forward Forward dashboard port to localhost
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$SCRIPT_DIR/.."
NAMESPACE="quant-trading"
ACTION="${1:-deploy}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v kubectl &>/dev/null; then
        log_error "kubectl not found. Please install kubectl first."
        exit 1
    fi

    if ! kubectl cluster-info &>/dev/null; then
        log_error "Cannot connect to Kubernetes cluster. Check your kubeconfig."
        exit 1
    fi

    log_ok "Prerequisites OK"
}

load_env() {
    # Load .env file if it exists
    ENV_FILE="$SCRIPT_DIR/../.env"
    if [ -f "$ENV_FILE" ]; then
        log_info "Loading environment from $ENV_FILE"
        set -a
        source "$ENV_FILE"
        set +a
    else
        log_warn ".env file not found at $ENV_FILE"
        log_warn "API keys will be empty — update secrets manually"
    fi
}

create_namespace() {
    if kubectl get namespace "$NAMESPACE" &>/dev/null; then
        log_info "Namespace $NAMESPACE already exists"
    else
        log_info "Creating namespace: $NAMESPACE"
        kubectl create namespace "$NAMESPACE"
        kubectl label namespace "$NAMESPACE" \
            app.kubernetes.io/part-of=quant-trading-system \
            environment=production
        log_ok "Namespace created"
    fi
}

apply_secrets() {
    log_info "Applying secrets..."

    # Read values from env
    local TUSHARE_TOKEN="${TUSHARE_TOKEN:-}"
    local AKSHARE_TOKEN="${AKSHARE_TOKEN:-}"
    local DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
    local KIMI_API_KEY="${KIMI_API_KEY:-}"
    local GLM_API_KEY="${GLM_API_KEY:-}"
    local MINIMAX_API_KEY="${MINIMAX_API_KEY:-}"
    local MINIQMT_USER="${MINIQMT_USER:-}"
    local MINIQMT_PASSWORD="${MINIQMT_PASSWORD:-}"
    local FEISHU_WEBHOOK="${FEISHU_WEBHOOK:-}"

    # Create/update secret
    kubectl create secret generic quant-secrets \
        --namespace="$NAMESPACE" \
        --from-literal=POSTGRES_USER=quant_user \
        --from-literal=POSTGRES_PASSWORD=quant_pass \
        --from-literal=POSTGRES_DB=quant_trading \
        --from-literal=DATABASE_URL="postgresql://quant_user:quant_pass@postgres.$NAMESPACE.svc.cluster.local:5432/quant_trading" \
        --from-literal=REDIS_URL="redis://redis.$NAMESPACE.svc.cluster.local:6379/0" \
        --from-literal=QUESTDB_URL="http://questdb.$NAMESPACE.svc.cluster.local:8812" \
        --from-literal=RABBITMQ_DEFAULT_USER=quant_user \
        --from-literal=RABBITMQ_DEFAULT_PASS=quant_pass \
        --from-literal=RABBITMQ_URL="amqp://quant_user:quant_pass@rabbitmq.$NAMESPACE.svc.cluster.local:5672" \
        --from-literal=TUSHARE_TOKEN="$TUSHARE_TOKEN" \
        --from-literal=AKSHARE_TOKEN="$AKSHARE_TOKEN" \
        --from-literal=DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
        --from-literal=KIMI_API_KEY="$KIMI_API_KEY" \
        --from-literal=GLM_API_KEY="$GLM_API_KEY" \
        --from-literal=MINIMAX_API_KEY="$MINIMAX_API_KEY" \
        --from-literal=MINIQMT_USER="$MINIQMT_USER" \
        --from-literal=MINIQMT_PASSWORD="$MINIQMT_PASSWORD" \
        --from-literal=FEISHU_WEBHOOK="$FEISHU_WEBHOOK" \
        --from-literal=GF_SECURITY_ADMIN_PASSWORD=admin \
        --dry-run=client -o yaml | kubectl apply -f -

    log_ok "Secrets applied"
}

update_postgres_init() {
    log_info "Setting up PostgreSQL init SQL..."

    local INIT_SQL="$SCRIPT_DIR/../docs/init.sql"

    if [ -f "$INIT_SQL" ]; then
        kubectl create configmap postgres-init \
            --namespace="$NAMESPACE" \
            --from-file=init.sql="$INIT_SQL" \
            --dry-run=client -o yaml | kubectl apply -f -
        log_ok "PostgreSQL init SQL loaded from docs/init.sql"
    else
        log_warn "docs/init.sql not found — database will be empty"
    fi
}

apply_security() {
    log_info "Applying security policies..."

    local SEC_FILES=(
        "rbac.yaml"
        "network-policy.yaml"
        "pdb.yaml"
        "resource-quota.yaml"
    )

    for file in "${SEC_FILES[@]}"; do
        if [ -f "$K8S_DIR/k8s/$file" ]; then
            log_info "  Applying $file..."
            kubectl apply -f "$K8S_DIR/k8s/$file"
        else
            log_warn "  $file not found — skipping"
        fi
    done

    log_ok "Security policies applied"
}

apply_configmaps() {
    log_info "Applying ConfigMaps..."
    kubectl apply -f "$K8S_DIR/k8s/configmap.yaml"
    log_ok "ConfigMaps applied"
}

apply_database_infra() {
    log_info "Deploying database infrastructure..."

    local DB_FILES=(
        "postgres.yaml"
        "redis.yaml"
        "questdb.yaml"
        "rabbitmq.yaml"
        "elasticsearch.yaml"
    )

    for file in "${DB_FILES[@]}"; do
        log_info "  Applying $file..."
        kubectl apply -f "$K8S_DIR/k8s/$file"
    done

    log_ok "Database infrastructure deployed"
}

apply_services() {
    log_info "Deploying microservices..."

    local SVC_FILES=(
        "strategy-service.yaml"
        "execution-service.yaml"
        "ai-scheduler.yaml"
        "dashboard.yaml"
        "logstash.yaml"
        "kibana.yaml"
        "prometheus.yaml"
        "grafana.yaml"
    )

    for file in "${SVC_FILES[@]}"; do
        log_info "  Applying $file..."
        kubectl apply -f "$K8S_DIR/k8s/$file"
    done

    log_ok "Microservices deployed"
}

apply_ingress() {
    log_info "Applying Ingress..."
    kubectl apply -f "$K8S_DIR/k8s/ingress.yaml"
    log_ok "Ingress applied"
}

wait_for_healthy() {
    local service="$1"
    local max_wait="${2:-120}"
    local waited=0

    log_info "Waiting for $service to be healthy (max ${max_wait}s)..."

    while [ $waited -lt $max_wait ]; do
        local ready
        ready=$(kubectl get pods -n "$NAMESPACE" -l "app=$service" \
            -o jsonpath='{.items[*].status.containerStatuses[*].ready}' 2>/dev/null || echo "")

        if [[ "$ready" == *"true"* ]] && [[ ! "$ready" == *"false"* ]]; then
            log_ok "$service is healthy"
            return 0
        fi

        sleep 5
        waited=$((waited + 5))
        echo -n "."
    done
    echo ""
    log_warn "$service may not be fully healthy — continuing anyway"
}

print_status() {
    echo ""
    echo "============================================"
    echo "  QuantTradingSystem K8s Deployment Status"
    echo "============================================"
    echo ""

    kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || true
    echo ""
    kubectl get svc -n "$NAMESPACE" 2>/dev/null || true
    echo ""
    kubectl get ingress -n "$NAMESPACE" 2>/dev/null || true
    echo ""
    kubectl get pvc -n "$NAMESPACE" 2>/dev/null || true
    echo ""

    # Get ingress URL
    local ingress_host
    ingress_host=$(kubectl get ingress -n "$NAMESPACE" quant-trading-ingress \
        -o jsonpath='{.spec.rules[0].host}' 2>/dev/null || echo "N/A")

    echo "Access URLs:"
    echo "  Dashboard:  http://${ingress_host}/"
    echo "  Grafana:    http://${ingress_host}/grafana"
    echo "  Kibana:     http://${ingress_host}/kibana"
    echo "  Prometheus: http://${ingress_host}/prometheus"
    echo "  RabbitMQ:   http://${ingress_host}/rabbitmq"
    echo ""
}

do_deploy() {
    log_info "============================================"
    log_info "  QuantTradingSystem K8s Deployment"
    log_info "============================================"
    echo ""

    check_prerequisites
    load_env
    create_namespace
    update_postgres_init
    apply_configmaps
    apply_secrets
    apply_database_infra

    log_info "Waiting for database services to be ready..."
    wait_for_healthy "postgres" 180
    wait_for_healthy "redis" 60
    wait_for_healthy "questdb" 60
    wait_for_healthy "rabbitmq" 120
    wait_for_healthy "elasticsearch" 180

    apply_services
    apply_ingress
    apply_security

    log_info "Waiting for application services..."
    wait_for_healthy "strategy-service" 120
    wait_for_healthy "execution-service" 60
    wait_for_healthy "ai-scheduler" 60
    wait_for_healthy "dashboard" 30
    wait_for_healthy "prometheus" 60
    wait_for_healthy "grafana" 60

    log_ok "============================================"
    log_ok "  Deployment Complete!"
    log_ok "============================================"
    print_status
}

do_status() {
    print_status
}

do_logs() {
    log_info "Tailing logs (Ctrl+C to stop)..."
    kubectl logs -n "$NAMESPACE" --all-containers=true -f --max-log-requests=20
}

do_cleanup() {
    log_warn "This will remove ALL resources in namespace '$NAMESPACE'"
    read -rp "Are you sure? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        kubectl delete namespace "$NAMESPACE"
        log_ok "Cleanup complete"
    else
        log_info "Cleanup cancelled"
    fi
}

do_port_forward() {
    log_info "Setting up port forwarding..."
    echo ""
    echo "Dashboard:  http://localhost:3000/"
    echo "Grafana:    http://localhost:3001/"
    echo ""
    kubectl port-forward -n "$NAMESPACE" svc/dashboard 3000:80 &
    kubectl port-forward -n "$NAMESPACE" svc/grafana 3001:3000 &
    wait
}

# Main
case "$ACTION" in
    deploy)
        do_deploy
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    cleanup)
        do_cleanup
        ;;
    port-forward)
        do_port_forward
        ;;
    pv)
        do_status
        ;;
    *)
        echo "Usage: $0 {deploy|status|logs|cleanup|port-forward}"
        exit 1
        ;;
esac
