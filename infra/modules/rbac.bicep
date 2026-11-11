// Access control.
//
// This is the module a client's security reviewer will open first, so the
// intent is written down rather than implied.
//
// Three principals, three different levels of access:
//
//   Developers            Data-plane access in DEV ONLY. A developer can
//                         build and test an agent where it is safe to break
//                         things, and has no standing access to acceptance or
//                         production. Investigating a production problem is a
//                         deliberate, audited elevation, not a default.
//
//   CI/CD identity        Promotes a version into acceptance and production.
//                         Authenticates with a federated credential from the
//                         GitHub environment -- there is no client secret to
//                         leak or rotate. Scoped to the project, not the
//                         subscription.
//
//   Workload identity     The running API. Data-plane access only, so it can
//                         call the model and nothing else. It cannot change
//                         deployments or create projects.
//
// Role GUIDs are used instead of names on purpose: the Foundry roles were
// renamed (Azure AI User became Foundry User and so on) and the names are
// still rolling out across surfaces, while the IDs did not change.

@allowed([ 'dev', 'acceptance', 'prod' ])
param environmentName string

param foundryAccountName string
param foundryProjectName string

@description('Entra ID group object ID for developers.')
param developerGroupObjectId string = ''

@description('Principal ID of the CI/CD federated identity.')
param cicdPrincipalId string = ''

@description('Principal ID of the workload managed identity.')
param workloadPrincipalId string = ''

// Foundry built-in roles.
var roleFoundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var roleFoundryProjectManager = 'eadc314b-1a2d-4efa-be10-5d325db5065e'

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-12-01' existing = {
  parent: foundryAccount
  name: foundryProjectName
}

var isDev = environmentName == 'dev'

// Developers: data-plane access in dev only.
resource developerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (isDev && !empty(developerGroupObjectId)) {
  scope: project
  name: guid(project.id, developerGroupObjectId, roleFoundryUser)
  properties: {
    principalId: developerGroupObjectId
    principalType: 'Group'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleFoundryUser)
    description: 'Developers build and test agents in dev. No standing access to acceptance or production.'
  }
}

// CI/CD: can manage this project in order to promote a version into it.
resource cicdAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(cicdPrincipalId)) {
  scope: project
  name: guid(project.id, cicdPrincipalId, roleFoundryProjectManager)
  properties: {
    principalId: cicdPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleFoundryProjectManager)
    description: 'Promotes a pinned agent version into ${environmentName}. Federated credential, no stored secret.'
  }
}

// The running workload: data plane only.
resource workloadAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(workloadPrincipalId)) {
  scope: project
  name: guid(project.id, workloadPrincipalId, roleFoundryUser)
  properties: {
    principalId: workloadPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleFoundryUser)
    description: 'Triage API calls the model as itself. Cannot change deployments or projects.'
  }
}

output developerAccessGranted bool = isDev && !empty(developerGroupObjectId)
output cicdAccessGranted bool = !empty(cicdPrincipalId)
output workloadAccessGranted bool = !empty(workloadPrincipalId)
