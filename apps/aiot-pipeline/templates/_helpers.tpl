{{- define "aiot.name" -}}
aiot-pipeline
{{- end -}}

{{- define "aiot.labels" -}}
app.kubernetes.io/name: {{ include "aiot.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end -}}
