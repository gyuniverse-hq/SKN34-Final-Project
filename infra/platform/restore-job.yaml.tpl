apiVersion: batch/v1
kind: Job
metadata:
  name: {{JOB_NAME}}
  namespace: {{NAMESPACE}}
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      serviceAccountName: {{SERVICE_ACCOUNT}}
      restartPolicy: Never
      initContainers:
        - name: fetch
          image: public.ecr.aws/aws-cli/aws-cli:latest
          env:
            - name: S3_URI
              value: s3://{{BUCKET}}/{{KEY}}
            - name: AWS_DEFAULT_REGION
              value: ap-northeast-2
          command:
            - sh
            - -ec
            - aws s3 cp "$S3_URI" /work/dump
          volumeMounts:
            - name: work
              mountPath: /work
          resources:
            requests:
              memory: 256Mi
              ephemeral-storage: 2Gi
            limits:
              memory: 512Mi
              ephemeral-storage: 4Gi
      containers:
        - name: restore
          image: postgres:17-bookworm
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: {{SECRET_NAME}}
                  key: DATABASE_URL
          command:
            - bash
            - -ec
            - |
              set -euo pipefail
              URL=$(printf '%s' "$DATABASE_URL" | sed -e 's|postgresql+asyncpg://|postgresql://|' -e 's|[?]ssl=require|?sslmode=require|' -e 's|&ssl=require||')
              echo "Creating extensions (if missing)..."
              psql "$URL" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'
              psql "$URL" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS vector;'
              echo "Restoring custom-format dump into RDS (clean existing objects)..."
              # --clean/--if-exists: replace current seed schema/data
              # --no-owner/--no-acl: dump roles (e.g. g5export) do not exist on RDS
              # --exit-on-error: fail the Job on first restore error
              pg_restore \
                --dbname="$URL" \
                --clean \
                --if-exists \
                --no-owner \
                --no-acl \
                --exit-on-error \
                --verbose \
                /work/dump
              echo "Restore finished."
              psql "$URL" -v ON_ERROR_STOP=1 -c "SELECT * FROM alembic_version;"
              psql "$URL" -v ON_ERROR_STOP=1 -c "SELECT count(*) AS products FROM products;"
          volumeMounts:
            - name: work
              mountPath: /work
          resources:
            requests:
              memory: 1Gi
              ephemeral-storage: 2Gi
            limits:
              memory: 2Gi
              ephemeral-storage: 4Gi
      volumes:
        - name: work
          emptyDir:
            sizeLimit: 4Gi
