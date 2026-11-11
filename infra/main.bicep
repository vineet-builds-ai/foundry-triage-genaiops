// =============================================================================
// Ticket triage agent -- one environment.
//
// Deployed once per environment (dev, acceptance, prod) into its OWN
// application landing zone resource group. Per Microsoft's Cloud Adoption
// Framework there is no separate "AI landing zone": an AI workload is a
// workload, so it goes into an application landing zone like any other.
//
// Platform-owned resources -- the virtual network, the subnets and the private
// DNS zones -- are NOT created here. They are passed in by resource ID, because
// in a landing zone the platform team owns them. That split is the point: this
// template deploys only what the workload team is accountable for.
// =============================================================================

targetScope = 'resourceGroup'

@description('Environment this deployment represents.')
@allowed([ 'dev', 'acceptance', 'prod' ])
param environmentName string

@description('Short workload name used to build resource names.')
@minLength(3)
@maxLength(12)
param workloadName string = 'tickettriage'

@description('Azure region. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Model deployment backing the agent.')
param modelName string = 'gpt-4o-mini'

@description('Model version. Pinned per environment so prod never silently moves.')
param modelVersion string

@description('Name of the deployment the agent manifest refers to.')
param modelDeploymentName string = 'gpt-4o-mini'

@description('Provisioned throughput, in thousands of tokens per minute.')
@minValue(1)
param modelCapacity int = 10

@description('Entra ID group of developers. Granted data-plane access in dev only.')
param developerGroupObjectId string = ''

@description('Principal ID of the CI/CD federated identity that promotes versions.')
param cicdPrincipalId string = ''

@description('Turn on private networking. Required outside dev.')
param enablePrivateNetworking bool = true

@description('Platform-owned subnet for private endpoints.')
param privateEndpointSubnetId string = ''

@description('Platform-owned subnet delegated to Container Apps.')
param containerAppsSubnetId string = ''

@description('Platform-owned private DNS zone IDs, keyed by service.')
param privateDnsZoneIds object = {
  cognitiveServices: ''
  openAi: ''
  aiServices: ''
}

@description('Log retention in days. Longer outside dev for audit.')
@minValue(30)
@maxValue(730)
param logRetentionDays int = 30

@description('Tags applied to every resource.')
param tags object = {}

// -----------------------------------------------------------------------------
// Naming and tagging.
//
// The "private networking is mandatory outside dev" rule is enforced in the
// CD workflow (see .github/workflows/cd.yml, the validate job) rather than
// with a template trick, so the failure message names the missing parameter
// instead of surfacing as an opaque template error.
// -----------------------------------------------------------------------------

var isProduction = environmentName == 'prod'

var commonTags = union(tags, {
  workload: workloadName
  environment: environmentName
  managedBy: 'bicep'
  costCentre: 'ai-platform'
})

var namePrefix = '${workloadName}-${environmentName}'
var uniqueSuffix = uniqueString(resourceGroup().id, workloadName, environmentName)

// -----------------------------------------------------------------------------
// Observability first. Everything else sends diagnostics here, so it is
// deployed before the resources that reference it.
// -----------------------------------------------------------------------------

module observability 'modules/observability.bicep' = {
  name: 'observability'
  params: {
    namePrefix: namePrefix
    location: location
    tags: commonTags
    retentionInDays: logRetentionDays
  }
}

// -----------------------------------------------------------------------------
// The Foundry resource and this environment's single project.
//
// Each environment gets a SEPARATE Foundry resource and project. Sharing one
// project across environments would mean a developer iterating on a prompt and
// production traffic sitting inside the same access and evaluation boundary.
// -----------------------------------------------------------------------------

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  params: {
    accountName: 'fdy-${workloadName}-${environmentName}-${uniqueSuffix}'
    projectName: '${namePrefix}-proj'
    location: location
    tags: commonTags
    environmentName: environmentName
    modelName: modelName
    modelVersion: modelVersion
    modelDeploymentName: modelDeploymentName
    modelCapacity: modelCapacity
    disablePublicNetworkAccess: enablePrivateNetworking
    privateEndpointSubnetId: privateEndpointSubnetId
    privateDnsZoneIds: privateDnsZoneIds
    logAnalyticsWorkspaceId: observability.outputs.logAnalyticsWorkspaceId
  }
}

// -----------------------------------------------------------------------------
// Hosting for the triage API.
// -----------------------------------------------------------------------------

module hosting 'modules/hosting.bicep' = {
  name: 'hosting'
  params: {
    namePrefix: namePrefix
    location: location
    tags: commonTags
    environmentName: environmentName
    infrastructureSubnetId: containerAppsSubnetId
    logAnalyticsCustomerId: observability.outputs.logAnalyticsCustomerId
    logAnalyticsSharedKey: observability.outputs.logAnalyticsSharedKey
    applicationInsightsConnectionString: observability.outputs.applicationInsightsConnectionString
    foundryProjectEndpoint: foundry.outputs.projectEndpoint
    modelDeploymentName: modelDeploymentName
    minReplicas: isProduction ? 2 : 0
    maxReplicas: isProduction ? 10 : 2
  }
}

// -----------------------------------------------------------------------------
// Access control. This is the module to read first in a security review.
// -----------------------------------------------------------------------------

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  params: {
    environmentName: environmentName
    foundryAccountName: foundry.outputs.accountName
    foundryProjectName: foundry.outputs.projectName
    developerGroupObjectId: developerGroupObjectId
    cicdPrincipalId: cicdPrincipalId
    workloadPrincipalId: hosting.outputs.managedIdentityPrincipalId
  }
}

output foundryAccountName string = foundry.outputs.accountName
output foundryProjectName string = foundry.outputs.projectName
output foundryProjectEndpoint string = foundry.outputs.projectEndpoint
output triageApiFqdn string = hosting.outputs.fqdn
output workloadPrincipalId string = hosting.outputs.managedIdentityPrincipalId
output logAnalyticsWorkspaceId string = observability.outputs.logAnalyticsWorkspaceId
output privateNetworkingEnabled bool = enablePrivateNetworking
