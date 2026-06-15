export interface SettingField {
  key: string
  type: 'str' | 'secret' | 'bool' | 'int' | 'float' | 'csv'
  group: 'credentials' | 'jellyfin' | 'library' | 'advanced'
  label: string
  description?: string
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
