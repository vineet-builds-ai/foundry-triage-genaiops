// Container Apps environment and the triage API.
//
// Container Apps rather than AKS: this workload is one stateless HTTP service
// that scales to zero outside production. A cluster would add a control plane,
// node patching and a platform bill for no benefit. That trade-off is recorded
// in docs/architecture.md.

param namePrefix string
param location string
param tags object

@allowed([ 'dev', 'acceptance', 'prod' ])
param environmentName string

@description('Platform-owned subnet delegated to Container Apps. Empty means public ingress, acceptable in dev only.')
param infrastructureSubnetId string = ''

param logAnalyticsCustomerId string

@secure()
param logAnalyticsSharedKey string

@secure()
param applicationInsightsConnectionString string

@description('Foundry project endpoint the agent calls.')
param foundryProjectEndpoint string

param modelDeploymentName string

@description('Image for the triage API. CD overrides this with the built digest.')
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@minValue(0)
param minReplicas int = 0

@minValue(1)
param maxReplicas int = 2

var useVnet = !empty(infrastructureSubnetId)

resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-cae'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    vnetConfiguration: useVnet ? {
      infrastructureSubnetId: infrastructureSubnetId
      // Outside dev the app is reachable only from inside the virtual network;
      // public exposure is the platform team's decision, made at the gateway.
      internal: environmentName != 'dev'
    } : null
    zoneRedundant: environmentName == 'prod' && useVnet
  }
}

resource triageApi 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-api'
  location: location
  tags: tags
  identity: {
    // The workload authenticates to Foundry as itself. No keys are mounted.
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Multiple' // Required for the canary rollout.
      ingress: {
        external: environmentName == 'dev'
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'triage-api'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: foundryProjectEndpoint
            }
            {
              name: 'FOUNDRY_MODEL_DEPLOYMENT'
              value: modelDeploymentName
            }
            {
              name: 'TRIAGE_ENVIRONMENT'
              value: environmentName
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: applicationInsightsConnectionString
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

output managedEnvironmentId string = managedEnvironment.id
output containerAppName string = triageApi.name
output fqdn string = triageApi.properties.configuration.ingress.fqdn
output managedIdentityPrincipalId string = triageApi.identity.principalId
