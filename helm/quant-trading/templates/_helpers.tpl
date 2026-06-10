{{/*
QuantTradingSystem — 共享模板函数
*/}}

{{/*
通用标签
*/}}
{{- define "quant-trading.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: quant-trading
{{- end }}

{{/*
选择器标签
*/}}
{{- define "quant-trading.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
完整镜像名
*/}}
{{- define "quant-trading.image" -}}
{{- $reg := .registry | default .global.imageRegistry -}}
{{- if $reg -}}{{ $reg }}/{{- end -}}{{ .repository }}:{{ .tag }}
{{- end }}

{{/*
服务 URL 生成器
用法: {{ include "quant-trading.serviceUrl" (dict "service" "strategy-service" "port" 8000 "context" .) }}
*/}}
{{- define "quant-trading.serviceUrl" -}}
http://{{ .service }}.{{ .context.Release.Namespace }}.svc.cluster.local:{{ .port }}
{{- end }}

{{/*
默认资源限制
*/}}
{{- define "quant-trading.resources" -}}
{{- if .resources }}
resources:
  {{- with .resources.requests }}
  requests:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with .resources.limits }}
  limits:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
健康检查探针
*/}}
{{- define "quant-trading.probes" -}}
{{- $port := .port -}}
{{- $path := .path | default "/health" -}}
{{- $delay := .delay | default 30 -}}
livenessProbe:
  httpGet:
    path: {{ $path }}
    port: {{ $port }}
  initialDelaySeconds: {{ $delay }}
  periodSeconds: 15
  timeoutSeconds: 5
  failureThreshold: 3
readinessProbe:
  httpGet:
    path: {{ $path }}
    port: {{ $port }}
  initialDelaySeconds: {{ add $delay -20 | max 5 }}
  periodSeconds: 10
  timeoutSeconds: 3
  failureThreshold: 3
startupProbe:
  httpGet:
    path: {{ $path }}
    port: {{ $port }}
  initialDelaySeconds: 5
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 24
{{- end }}

{{/*
环境变量 from Secret
*/}}
{{- define "quant-trading.secretEnv" -}}
{{- range $key, $val := . }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ $.secretName }}
      key: {{ $key }}
{{- end }}
{{- end }}
