import type {
  ClarificationNeeded,
  ErrorDetail,
  FieldSpecInput,
  ValidationErrorResponse,
} from "@/api/gen";
import type { ResponseErrorConfig } from "@kubb/plugin-client/clients/axios";
import { nanoid } from "nanoid";

export type FieldType = "文字" | "數字" | "日期";

export const typeList: {
  label: string;
  value: FieldType;
}[] = [
  { label: "文字", value: "文字" },
  { label: "數字", value: "數字" },
  { label: "日期", value: "日期" },
];

export const createDataField = (
  name: string = "",
  isKeyfield: boolean = false,
): FieldSpecInput => ({
  id: nanoid(),
  name: name,
  data_type: "文字",
  format_hint: null,
  is_key_field: isKeyfield,
});

export const parseAnalyzeError = (
  error: ResponseErrorConfig<ErrorDetail | ValidationErrorResponse>,
): string => {
  const status = error.response?.status;
  const data = error.response?.data;

  if (status === 400 || status === 502) {
    const body = data as ErrorDetail;

    return `[${body.error_code}] ${body.detail}`;
  }

  if (status === 422) {
    const body = data as ValidationErrorResponse;

    return body.detail.map((item) => item.msg).join("\n");
  }

  return "發生未知錯誤，請稍後再試。";
};

export const findClarificationForField = (
  fieldId: string,
  clarifications: ClarificationNeeded[],
): string | null => {
  return (
    clarifications.find((item) => item.field_id === fieldId)
      ?.clarification_question ?? null
  );
};
