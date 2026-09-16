export interface ChangedFieldConfig {
  param: number;
  variant: string;
}

// string is used as the key to represent the field_id
export type ChangedFieldMap = Record<string, ChangedFieldConfig>;
