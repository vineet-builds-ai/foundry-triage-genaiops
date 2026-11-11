// Log Analytics and Application Insights.
//
// Deployed first so every other resource can send diagnostics here. Agent
// traces, evaluation results and production quality signals all land in this
// workspace, which is what makes continuous evaluation in production possible
// rather than aspirational.

@description('Prefix for resource names.')
param namePrefix string

param location string
param tags object

@description('Retention in days. Audit requirements usually drive this.')
@minValue(30)
@maxValue(730)
param retentionInDays int = 30

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-law'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-appi'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output logAnalyticsWorkspaceId string = workspace.id
output logAnalyticsCustomerId string = workspace.properties.customerId

@secure()
output logAnalyticsSharedKey string = workspace.listKeys().primarySharedKey

output applicationInsightsId string = appInsights.id

@secure()
output applicationInsightsConnectionString string = appInsights.properties.ConnectionString
