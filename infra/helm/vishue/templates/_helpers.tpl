{{- define "vishue.fullname" -}}
{{- .Release.Name | trunc 40 | trimSuffix "-" -}}
{{- end -}}

{{- define "vishue.labels" -}}
app.kubernetes.io/part-of: vishue
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* dict "root" $ "component" "api" */}}
{{- define "vishue.selector" -}}
app.kubernetes.io/name: {{ .component }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{/* dict "root" $ "name" "vishue-api" */}}
{{- define "vishue.image" -}}
{{- $tag := .root.Values.image.tag | default .root.Chart.AppVersion -}}
{{- if .root.Values.image.registry -}}
{{- printf "%s/%s:%s" .root.Values.image.registry .name $tag -}}
{{- else -}}
{{- printf "%s:%s" .name $tag -}}
{{- end -}}
{{- end -}}

{{- define "vishue.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- define "vishue.podSecurityContext" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  seccompProfile:
    type: RuntimeDefault
{{- end -}}

{{- define "vishue.containerSecurityContext" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop: ["ALL"]
{{- end -}}

{{/*
Connection env for in-cluster data stores (dict "root" $). Explicit env wins over envFrom, so
these override whatever the service Secret holds; external stores come from the Secret alone.
*/}}
{{- define "vishue.apiStoreEnv" -}}
{{- $fullname := include "vishue.fullname" .root -}}
{{- if .root.Values.dataStores.postgres.enabled }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef: { name: {{ $fullname }}-datastores, key: DATABASE_URL }
{{- end }}
{{- if .root.Values.dataStores.redis.enabled }}
- name: REDIS_URL
  value: redis://{{ $fullname }}-redis:6379/0
{{- end }}
{{- end -}}

{{- define "vishue.chatbotStoreEnv" -}}
{{- $fullname := include "vishue.fullname" .root -}}
{{- if .root.Values.dataStores.neo4j.enabled }}
- name: NEO4J_URI
  value: bolt://{{ $fullname }}-neo4j:7687
- name: NEO4J_PASSWORD
  valueFrom:
    secretKeyRef: { name: {{ $fullname }}-datastores, key: NEO4J_PASSWORD }
{{- end }}
{{- if .root.Values.dataStores.redis.enabled }}
- name: REDIS_URL
  value: redis://{{ $fullname }}-redis:6379/1
{{- end }}
{{- end -}}

{{/* dict "root" $ "name" "vishue-api" ; envFrom for a backend service's ConfigMap + Secret */}}
{{- define "vishue.envFrom" -}}
envFrom:
  - configMapRef:
      name: {{ .name }}
  - secretRef:
      name: {{ .name }}
{{- end -}}
