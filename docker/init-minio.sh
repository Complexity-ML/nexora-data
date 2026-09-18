#!/bin/sh
set -eu
attempt=0
until mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 && mc ready local >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then echo 'MinIO indisponible' >&2; exit 1; fi
  sleep 2
done
mc mb --ignore-existing "local/$NEXORA_S3_BUCKET" >/dev/null
mc admin user add local "$NEXORA_S3_ACCESS_KEY" "$NEXORA_S3_SECRET_KEY" >/dev/null
cat > /tmp/nexora-policy.json <<POLICY
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":["s3:ListBucket","s3:GetBucketLocation","s3:ListBucketMultipartUploads"],"Resource":["arn:aws:s3:::$NEXORA_S3_BUCKET"]},
{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:AbortMultipartUpload","s3:ListMultipartUploadParts"],"Resource":["arn:aws:s3:::$NEXORA_S3_BUCKET/bronze/*"]}
]}
POLICY
mc admin policy create local nexora-bronze /tmp/nexora-policy.json >/dev/null
mc admin policy attach local nexora-bronze --user "$NEXORA_S3_ACCESS_KEY" >/dev/null
echo 'Bucket et compte applicatif MinIO prêts.'
