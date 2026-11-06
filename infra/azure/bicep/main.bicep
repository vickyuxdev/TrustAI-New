// infra/azure/bicep/main.bicep
// TrustAI — Azure Container Apps infrastructure
// Deploy: az deployment group create --resource-group rg-trustai --template-file main.bicep

param location string = 'eastus'
param environmentName string = 'production'
param acrName string = 'trustairegistry'
param postgresAdminUser string = 'trustai'
@secure()
param postgresAdminPassword string

// ── Log Analytics Workspace ──────────────────────────────────────
resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-trustai-${environmentName}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Container Apps Environment ───────────────────────────────────
resource caEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-trustai-${environmentName}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logWorkspace.properties.customerId
        sharedKey: logWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

// ── Azure Container Registry ─────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Standard' }
  properties: { adminUserEnabled: false }
}

// ── PostgreSQL Flexible Server (Metadata) ────────────────────────
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: 'psql-trustai-${environmentName}'
  location: location
  sku: { name: 'Standard_D2s_v3', tier: 'GeneralPurpose' }
  properties: {
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 }
    version: '16'
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgres
  name: 'trustai'
  properties: { charset: 'UTF8' }
}

// ── Azure Cache for Redis ─────────────────────────────────────────
resource redis 'Microsoft.Cache/redis@2023-08-01' = {
  name: 'redis-trustai-${environmentName}'
  location: location
  properties: {
    sku: { name: 'Standard', family: 'C', capacity: 1 }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
  }
}

// ── Event Hub ─────────────────────────────────────────────────────
resource eventHubNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'evhns-trustai-${environmentName}'
  location: location
  sku: { name: 'Standard', tier: 'Standard', capacity: 1 }
}

resource eventHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubNamespace
  name: 'trustai-telemetry'
  properties: {
    partitionCount: 4
    messageRetentionInDays: 7
  }
}

// ── Ingestion Container App ───────────────────────────────────────
resource ingestionApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-trustai-ingestion'
  location: location
  properties: {
    managedEnvironmentId: caEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
      }
      secrets: [
        { name: 'postgres-url', value: 'postgresql+asyncpg://${postgresAdminUser}:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/trustai' }
        { name: 'redis-url',    value: 'rediss://:${redis.listKeys().primaryKey}@${redis.properties.hostName}:6380/0' }
      ]
    }
    template: {
      containers: [
        {
          name: 'ingestion'
          image: '${acr.properties.loginServer}/trustai-ingestion:latest'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'TRUSTAI_POSTGRES_URL', secretRef: 'postgres-url' }
            { name: 'TRUSTAI_REDIS_URL',    secretRef: 'redis-url' }
            { name: 'TRUSTAI_ENVIRONMENT',  value: environmentName }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-scale'
            http: { metadata: { concurrentRequests: '100' } }
          }
        ]
      }
    }
  }
}

// Outputs
output ingestionUrl string = 'https://${ingestionApp.properties.configuration.ingress.fqdn}'
output acrLoginServer string = acr.properties.loginServer
