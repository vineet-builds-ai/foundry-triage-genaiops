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

@description('Image for the triage API, pinned by digest. CD builds it once and passes the same digest to every environment. Empty deploys a placeholder, used only to bootstrap an environment before the first build.')
param containerImage string = ''

@description('Suffix for the revision this deployment creates, so each revision names the release and run that produced it. Empty lets Container Apps generate one.')
param revisionSuffix string = ''

@description('Revision currently serving traffic. When set (production), the new revision starts at 0% and the canary script moves traffic deliberately. When empty, the new revision takes all traffic at once (dev, acceptance, first deployment).')
param stableRevisionName string = ''

@minValue(0)
param minReplicas int = 0

@minValue(1)
param maxReplicas int = 2

var useVnet = !empty(infrastructureSubnetId)
var useAppImage = !empty(containerImage)
var image = useAppImage ? containerImage : 'mcr.microsoft.com/k8se/quickstart:latest'
// The placeholder listens on 80; the triage API on 8000.
var targetPort = useAppImage ? 8000 : 80

// Without an explicit traffic block Container Apps sends 100% to the newest
// revision the moment it is ready -- which would make the "canary" a full
// release. Pinning traffic to the stable revision is what makes it a canary.
var trafficSplit = empty(stableRevisionName) ? [
  {
    latestRevision: true
    weight: 100
  }
] : [
  {
    revisionName: stableRevisionName
    weight: 100
  }
  {
    latestRevision: true
    weight: 0
  }
]

var probes = useAppImage ? [
  {
    type: 'Startup'
    httpGet: {
      path: '/healthz'
      port: 8000
    }
    periodSeconds: 5
    failureThreshold: 24
  }
  {
    type: 'Liveness'
    httpGet: {
      path: '/healthz'
      port: 8000
    }
    periodSeconds: 30
    failureThreshold: 3
  }
  {
    type: 'Readiness'
    httpGet: {
      path: '/healthz'
      port: 8000
    }
    periodSeconds: 10
    failureThreshold: 3
  }
] : []

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
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
        traffic: trafficSplit
      }
    }
    template: {
      revisionSuffix: empty(revisionSuffix) ? null : revisionSuffix
      containers: [
        {
          name: 'triage-api'
          image: image
          probes: probes
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
output latestRevisionName string = triageApi.properties.latestRevisionName
output latestRevisionFqdn string = triageApi.properties.latestRevisionFqdn
output managedIdentityPrincipalId string = triageApi.identity.principalId
