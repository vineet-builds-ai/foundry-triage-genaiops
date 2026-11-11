using '../main.bicep'

param environmentName = 'prod'
param modelVersion = '2024-07-18'
param modelCapacity = 60

param enablePrivateNetworking = true

// Longer retention so an incident six months old can still be reconstructed
// from agent traces and evaluation history.
param logRetentionDays = 365

param privateEndpointSubnetId = readEnvironmentVariable('PRIVATE_ENDPOINT_SUBNET_ID', '')
param containerAppsSubnetId = readEnvironmentVariable('CONTAINER_APPS_SUBNET_ID', '')
param privateDnsZoneIds = {
  cognitiveServices: readEnvironmentVariable('DNS_ZONE_COGNITIVESERVICES', '')
  openAi: readEnvironmentVariable('DNS_ZONE_OPENAI', '')
  aiServices: readEnvironmentVariable('DNS_ZONE_AISERVICES', '')
}

param cicdPrincipalId = readEnvironmentVariable('CICD_PRINCIPAL_ID', '')

param tags = {
  dataClassification: 'customer-data'
  slo: '99.9'
}
