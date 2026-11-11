using '../main.bicep'

param environmentName = 'dev'
param modelVersion = '2024-07-18'
param modelCapacity = 10

// Dev is the only environment where developers hold standing data-plane access
// and the only one where public ingress is acceptable.
param enablePrivateNetworking = false
param logRetentionDays = 30

// Supplied by the pipeline from GitHub environment variables.
param developerGroupObjectId = readEnvironmentVariable('DEVELOPER_GROUP_OBJECT_ID', '')
param cicdPrincipalId = readEnvironmentVariable('CICD_PRINCIPAL_ID', '')

param tags = {
  dataClassification: 'synthetic-only'
  slo: 'none'
}
