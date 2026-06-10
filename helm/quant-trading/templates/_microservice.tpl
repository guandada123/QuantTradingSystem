{{/*
QuantTradingSystem — 微服务部署模板

参数 (dict):
  .name        — 服务名称
  .port        — 端口
  .replicas    — 副本数
  .image       — 镜像配置 {repository, tag}
  .resources   — 资源配置
  .healthCheck — 健康检查 {path, livenessDelay, readinessDelay}
  .hpa         — HPA 配置 {enabled, minReplicas, maxReplicas, targetCPU, targetMemory}
  .env         — 额外的环境变量 map
  .envFromSecret — 从 Secret 注入的环境变量列表 [name, key]
  .initContainers — initContainer 配置列表
  .prometheus  — Prometheus 注解 {enabled, port, path}
  .labels      — 额外的标签
  .context     — root context (.)
*/}}

{{/* === 1. Service === */}}
{{- define "quant-trading.microservice" -}}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .name }}
  namespace: {{ .context.Values.global.namespace }}
  labels:
    {{- include "quant-trading.labels" .context | nindent 4 }}
    app: {{ .name }}
    {{- with .labels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  type: ClusterIP
  ports:
    - port: {{ .port }}
      targetPort: {{ .port }}
      protocol: TCP
      name: http
  selector:
    app: {{ .name }}

---
{{/* === 2. Deployment === */}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .name }}
  namespace: {{ .context.Values.global.namespace }}
  labels:
    {{- include "quant-trading.labels" .context | nindent 4 }}
    app: {{ .name }}
spec:
  replicas: {{ .replicas }}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: {{ .name }}
  template:
    metadata:
      labels:
        app: {{ .name }}
        {{- include "quant-trading.selectorLabels" .context | nindent 8 }}
        {{- with .labels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      annotations:
        {{- if .prometheus.enabled }}
        prometheus.io/scrape: "true"
        prometheus.io/port: {{ .prometheus.port | default .port | quote }}
        prometheus.io/path: {{ .prometheus.path | default "/metrics" | quote }}
        {{- end }}
        checksum/config: {{ include (print .context.Template.BasePath "/configmap.yaml") .context | sha256sum }}
    spec:
      serviceAccountName: {{ .context.Values.rbac.serviceAccount }}
      {{- if .initContainers }}
      initContainers:
        {{- toYaml .initContainers | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ .name }}
          image: {{ include "quant-trading.image" (dict "registry" .image.registry "repository" .image.repository "tag" .image.tag "global" .context.Values.global) }}
          imagePullPolicy: {{ .context.Values.global.imagePullPolicy }}
          ports:
            - containerPort: {{ .port }}
              protocol: TCP
          env:
            - name: SERVICE_NAME
              value: {{ .name | quote }}
            - name: SERVICE_PORT
              value: {{ .port | quote }}
            - name: ENVIRONMENT
              value: {{ .context.Values.global.environment | quote }}
            {{- range $k, $v := .env }}
            - name: {{ $k }}
              value: {{ $v | quote }}
            {{- end }}
          {{- if .envFrom }}
          envFrom:
            - secretRef:
                name: quant-secrets
          {{- end }}
          {{- include "quant-trading.probes" (dict "port" .port "path" (.healthCheck.path | default "/health") "delay" (.healthCheck.livenessDelay | default 30)) | nindent 10 }}
          {{- include "quant-trading.resources" (dict "resources" .resources) | nindent 10 }}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 1000
            capabilities:
              drop: ["ALL"]

{{/* === 3. HPA === */}}
{{- if .hpa.enabled }}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ .name }}-hpa
  namespace: {{ .context.Values.global.namespace }}
  labels:
    {{- include "quant-trading.labels" .context | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ .name }}
  minReplicas: {{ .hpa.minReplicas }}
  maxReplicas: {{ .hpa.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .hpa.targetCPU }}
    {{- if .hpa.targetMemory }}
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: {{ .hpa.targetMemory }}
    {{- end }}
{{- end }}

{{/* === 4. PDB === */}}
{{- if .context.Values.pdb.enabled }}
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ .name }}-pdb
  namespace: {{ .context.Values.global.namespace }}
spec:
  minAvailable: {{ max 1 (sub (.replicas | int) 1) | min 1 }}
  selector:
    matchLabels:
      app: {{ .name }}
{{- end }}
{{- end }}
