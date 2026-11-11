// The Foundry resource, this environment's project, and the model deployment.
//
// Resource shape notes, because this is the part that changed with the
// Microsoft Foundry rebrand and is easy to get wrong:
//
//   * The Foundry resource is Microsoft.CognitiveServices/accounts with
//     kind 'AIServices'. The ARM resource type did not change with the
//     rename from Azure AI Foundry.
//   * allowProjectManagement: true is what makes it a Foundry resource
//     capable of holding projects, rather than a plain AI Services account.
//   * A project is a child resource, accounts/projects. Projects are the
//     access-control and evaluation boundary, which is why each environment
//     gets its own.
//   * customSubDomainName is required for Entra ID token authentication.
//     Without it the workload is pushed back onto API keys.

@description('Globally unique name for the Foundry resource.')
param accountName string

@description('Name of this environment\'s project.')
param projectName string

param location string
param tags object

@allowed([ 'dev', 'acceptance', 'prod' ])
param environmentName string

param modelName string
param modelVersion string
param modelDeploymentName string
param modelCapacity int

@description('Disable public network access and reach the resource privately.')
param disablePublicNetworkAccess bool = true

param privateEndpointSubnetId string = ''
param privateDnsZoneIds object = {}
param logAnalyticsWorkspaceId string

var deployPrivateEndpoint = disablePublicNetworkAccess && !empty(privateEndpointSubnetId)

// Only wire up DNS zone groups the platform team actually provided.
var dnsZoneConfigs = [for zone in items(privateDnsZoneIds): {
  name: replace(zone.key, '_', '-')
  properties: {
    privateDnsZoneId: zone.value
  }
} ]
var populatedDnsZoneConfigs = filter(dnsZoneConfigs, config => !empty(config.properties.privateDnsZoneId))

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    // Required for Entra ID token auth, which is what lets us disable keys.
    customSubDomainName: accountName
    allowProjectManagement: true
    publicNetworkAccess: disablePublicNetworkAccess ? 'Disabled' : 'Enabled'
    networkAcls: {
      defaultAction: disablePublicNetworkAccess ? 'Deny' : 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
    // No shared keys anywhere. Every caller authenticates as itself.
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-12-01' = {
  parent: foundryAccount
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: '${projectName} (${environmentName})'
    description: 'Ticket triage agent -- ${environmentName} environment. Promotion boundary; do not share across environments.'
  }
}

// Model version is pinned per environment via parameters, so a new model
// version reaching production is a reviewed parameter change rather than a
// silent upgrade underneath a running workload.
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundryAccount
  name: modelDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'send-to-law'
  scope: foundryAccount
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
      {
        categoryGroup: 'audit'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = if (deployPrivateEndpoint) {
  name: '${accountName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${accountName}-plsc'
        properties: {
          privateLinkServiceId: foundryAccount.id
          groupIds: [ 'account' ]
        }
      }
    ]
  }
}

resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (deployPrivateEndpoint && !empty(populatedDnsZoneConfigs)) {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: populatedDnsZoneConfigs
  }
}

output accountName string = foundryAccount.name
output accountId string = foundryAccount.id
output projectName string = project.name
output projectId string = project.id

// The endpoint the agent manifest and the evaluation SDK both target.
output projectEndpoint string = '${foundryAccount.properties.endpoint}api/projects/${project.name}'

output accountPrincipalId string = foundryAccount.identity.principalId
output projectPrincipalId string = project.identity.principalId
output modelDeploymentName string = modelDeployment.name
