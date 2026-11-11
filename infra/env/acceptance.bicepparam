using '../main.bicep'

param environmentName = 'acceptance'

// Pinned to the same model version as production. Acceptance testing against a
// different model version than production would not be acceptance testing.
param modelVersion = '2024-07-18'
param modelCapacity = 20

param enablePrivateNetworking = true
param logRetentionDays = 90

// Platform-owned networking, passed in by the platform team's landing zone.
param privateEndpointSubnetId = readEnvironmentVariable('PRIVATE_ENDPOINT_SUBNET_ID', '')
param containerAppsSubnetId = readEnvironmentVariable('CONTAINER_APPS_SUBNET_ID', '')
param privateDnsZoneIds = {
  cognitiveServices: readEnvironmentVariable('DNS_ZONE_COGNITIVESERVICES', '')
  openAi: readEnvironmentVariable('DNS_ZONE_OPENAI', '')
  aiServices: readEnvironmentVariable('DNS_ZONE_AISERVICES', '')
}

// No developer group: acceptance has no standing human data-plane access.
param cicdPrincipalId = readEnvironmentVariable('CICD_PRINCIPAL_ID', '')

param tags = {
  dataClassification: 'production-like'
  slo: 'best-effort'
}
