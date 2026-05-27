#!/bin/bash
set -e

PROJECT=${GCP_PROJECT:-blobfish-ai-429200}
REGION=${GCP_REGION:-us-central1}
SERVICE=skill-bench
IMAGE=gcr.io/$PROJECT/$SERVICE

echo "Building and deploying skill-bench to Cloud Run..."
echo "  Project: $PROJECT"
echo "  Region:  $REGION"
echo "  Image:   $IMAGE"

# Build
gcloud builds submit --tag $IMAGE --project $PROJECT

# Deploy
gcloud run deploy $SERVICE \
  --image $IMAGE \
  --region $REGION \
  --project $PROJECT \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars "SKILL_BENCH_DATABASE_PATH=/tmp/skill_bench.db,SKILL_BENCH_NUM_WORKERS=2"

echo ""
echo "Deployed. Getting URL..."
URL=$(gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format 'value(status.url)')
echo "Dashboard: $URL"
