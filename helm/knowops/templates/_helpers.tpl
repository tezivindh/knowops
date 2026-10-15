{{- define "knowops.name" -}}{{ .Release.Name }}{{- end -}}
{{- define "knowops.labels" -}}
app.kubernetes.io/name: knowops
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
{{- define "knowops.security" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- end -}}
{{- define "knowops.wait" -}}
- name: wait-for-migrations
  image: "{{ .Values.images.backend.repository }}:{{ .Values.images.backend.tag }}"
  imagePullPolicy: {{ .Values.images.backend.pullPolicy }}
  command: [python, scripts/wait_for_migrations.py]
  envFrom:
    - configMapRef: { name: {{ include "knowops.name" . }}-config }
    - secretRef: { name: {{ .Values.secretName }} }
  securityContext:
    {{- include "knowops.security" . | nindent 4 }}
{{- end -}}
