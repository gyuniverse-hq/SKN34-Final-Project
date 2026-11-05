{{/*
One backend service: ConfigMap, Deployment, Service, HPA, PDB.
  include "vishue.backend" (dict "root" $ "component" "api" "svc" .Values.api "migrate" true "storeEnv" "...")
*/}}
{{- define "vishue.backend" -}}
{{- $root := .root -}}
{{- $c := .component -}}
{{- $svc := .svc -}}
{{- $storeEnv := .storeEnv | default "" | trim -}}
{{- $name := printf "%s-%s" (include "vishue.fullname" $root) $c -}}
{{- $selector := include "vishue.selector" (dict "root" $root "component" $c) -}}
{{- $image := include "vishue.image" (dict "root" $root "name" $svc.image) -}}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ $name }}
  labels:
    {{- include "vishue.labels" $root | nindent 4 }}
data:
  ENV: {{ $root.Values.env | quote }}
  SUPABASE_URL: {{ $root.Values.supabase.url | quote }}
  SUPABASE_PUBLISHABLE_KEY: {{ $root.Values.supabase.publishableKey | quote }}
  {{- range $k, $v := $svc.env }}
  {{ $k }}: {{ $v | quote }}
  {{- end }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ $name }}
  labels:
    {{- include "vishue.labels" $root | nindent 4 }}
    {{- $selector | nindent 4 }}
spec:
  {{- if not $svc.autoscaling.enabled }}
  replicas: {{ $svc.replicas }}
  {{- end }}
  revisionHistoryLimit: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      {{- $selector | nindent 6 }}
  template:
    metadata:
      labels:
        {{- $selector | nindent 8 }}
      annotations:
        checksum/config: {{ list $svc.env $root.Values.supabase $root.Values.env | toJson | sha256sum }}
    spec:
      automountServiceAccountToken: false
      {{- include "vishue.imagePullSecrets" $root | nindent 6 }}
      {{- include "vishue.podSecurityContext" . | nindent 6 }}
      terminationGracePeriodSeconds: 30
      # Spread replicas over nodes and zones so one node (or AZ) failure keeps the service up.
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              {{- $selector | nindent 14 }}
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              {{- $selector | nindent 14 }}
      {{- if .migrate }}
      initContainers:
        - name: migrate
          image: {{ $image }}
          imagePullPolicy: {{ $root.Values.image.pullPolicy }}
          command: ["alembic", "upgrade", "head"]
          {{- include "vishue.envFrom" (dict "name" $name) | nindent 10 }}
          {{- with $storeEnv }}
          env:
            {{- . | nindent 12 }}
          {{- end }}
          {{- include "vishue.containerSecurityContext" . | nindent 10 }}
          volumeMounts:
            - { name: tmp, mountPath: /tmp }
      {{- end }}
      containers:
        - name: {{ $c }}
          image: {{ $image }}
          imagePullPolicy: {{ $root.Values.image.pullPolicy }}
          ports:
            - { name: http, containerPort: 8000 }
          {{- include "vishue.envFrom" (dict "name" $name) | nindent 10 }}
          {{- with $storeEnv }}
          env:
            {{- . | nindent 12 }}
          {{- end }}
          startupProbe:
            httpGet: { path: /healthz, port: http }
            periodSeconds: 3
            failureThreshold: 20
          livenessProbe:
            httpGet: { path: /healthz, port: http }
            periodSeconds: 20
            timeoutSeconds: 3
          readinessProbe:
            httpGet: { path: /readyz, port: http }
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
          lifecycle:
            # Let the Gateway stop routing to this pod before uvicorn shuts down.
            preStop:
              exec:
                command: ["sleep", "5"]
          resources:
            {{- toYaml $svc.resources | nindent 12 }}
          {{- include "vishue.containerSecurityContext" . | nindent 10 }}
          volumeMounts:
            - { name: tmp, mountPath: /tmp }
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 64Mi
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $name }}
  labels:
    {{- include "vishue.labels" $root | nindent 4 }}
spec:
  type: ClusterIP
  selector:
    {{- $selector | nindent 4 }}
  ports:
    - { name: http, port: 8000, targetPort: http }
{{- if $svc.autoscaling.enabled }}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ $name }}
  labels:
    {{- include "vishue.labels" $root | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ $name }}
  minReplicas: {{ $svc.autoscaling.minReplicas }}
  maxReplicas: {{ $svc.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ $svc.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
{{- if $root.Values.podDisruptionBudget.enabled }}
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ $name }}
  labels:
    {{- include "vishue.labels" $root | nindent 4 }}
spec:
  minAvailable: {{ $root.Values.podDisruptionBudget.minAvailable }}
  selector:
    matchLabels:
      {{- $selector | nindent 6 }}
{{- end }}
{{- end -}}
