export interface SettingField {
  key: string
  type: 'str' | 'secret' | 'bool' | 'int' | 'float' | 'csv'
  group: 'credentials' | 'enrichment' | 'jellyfin' | 'library' | 'advanced'
  label: string
  secret: boolean
  value?: string | number | boolean | null
  is_set?: boolean
  masked?: string
}

export interface SettingsResponse {
  fields: SettingField[]
}

export interface TestResult {
  ok: boolean
  message: string
}
