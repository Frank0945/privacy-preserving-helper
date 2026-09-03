export type FieldType = "文字" | "數字" | "日期";

export const purposeList = [
  { label: "內部使用", value: "內部使用" },
  { label: "跨部門使用", value: "跨部門使用" },
  { label: "對外公開研究", value: "對外公開研究" },
  { label: "其他", value: "其他" },
];

export const fakeDataAmountList = [
  { label: "5", value: "5" },
  { label: "10", value: "10" },
  { label: "20", value: "20" },
];

export const typeList: {
  label: string;
  value: FieldType;
}[] = [
  { label: "文字", value: "文字" },
  { label: "數字", value: "數字" },
  { label: "日期", value: "日期" },
];

export interface DataField {
  id: string;
  name: string;
  type: FieldType;
  rule: string;
  isImportant: boolean;
}

export const createDataField = (): DataField => ({
  id: crypto.randomUUID(),
  name: "",
  type: "文字",
  rule: "",
  isImportant: false,
});
