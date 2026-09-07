/**
 * 這個檔案只做一件事：定義「後端 API 長什麼樣」以及「怎麼呼叫它」。
 *
 * 為什麼要獨立出來，不直接在元件裡寫 fetch：
 * 之後如果有其他頁面也要呼叫 /analyze（例如正式的表單頁），
 * 可以直接 import 這裡的函式重複使用，不用把 fetch 邏輯複製貼上到處都是。
 * 而且型別定義（interface）跟後端的 Pydantic schema 是一一對應的，
 * 之後後端 schema 改了，只需要改這個檔案，TypeScript 會自動幫你抓出
 * 所有用到舊型別、對不上的地方。
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// ---------- 對應後端 schemas/requests.py 的 FieldSpec ----------
export interface FieldSpec {
  name: string;
  data_type: string;
  format_rule: string | null;
  purpose: "內部使用" | "跨部門提供" | "對外公開研究" | "其他";
  purpose_detail: string | null;
  is_key_field: boolean;
  sample_count: 5 | 10 | 20;
}

// ---------- 對應後端 schemas/responses.py 的 FieldResult ----------
export interface FieldResult {
  field_name: string;
  original_samples: string[];
  processed_samples: string[];
  technique:
    | "mask"
    | "generalize"
    | "k_anonymity_group"
    | "suppress"
    | "differential_privacy";
  suggested_param: string;
  reason: string;
  excel_formula: string;
  adjustable_params: Record<string, string | number>;
}

// analyze 回應有三種可能的形狀，用 discriminated union 讓 TypeScript
// 可以依 status 自動縮小型別（narrowing），呼叫端寫 if 判斷時會有型別提示
export type AnalyzeResponse =
  | { status: "ok"; session_id: string; results: FieldResult[] }
  | {
      status: "need_clarification";
      source: "synthetic_data" | "technique_selection";
      field: string;
      question: string;
    };

export interface RecalculateResponse {
  processed_samples: string[];
  excel_formula: string;
}

/**
 * 呼叫 POST /analyze。
 * 用 try/catch 包起來，把「網路層錯誤」（連不上後端、CORS 被擋）
 * 跟「後端回傳的商業邏輯錯誤」（400、404）分開處理，
 * 呼叫端可以依錯誤類型顯示不同的提示訊息。
 */
export async function analyzeFields(
  fields: FieldSpec[],
): Promise<AnalyzeResponse> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields }),
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    // 後端有兩種錯誤格式並存：
    // - domain_exception_handler（main.py 攔截 ValueError）回傳 { message: "..." }
    // - FastAPI 內建的 HTTPException（例如 404）回傳 { detail: "..." }
    // 這裡兩種都嘗試讀取，確保不管哪種格式都能顯示正確的錯誤訊息。
    throw new Error(
      errorBody.message ||
        errorBody.detail ||
        `後端回傳錯誤狀態碼 ${res.status}`,
    );
  }

  return res.json();
}

/**
 * 呼叫 POST /recalculate。
 * 這支只會在使用者拖滑桿時觸發，params 的內容依技術種類不同
 * （mask 用 position/length，generalize 用 bucket_size，
 * k_anonymity_group 用 k，differential_privacy 用 epsilon）。
 */
export async function recalculateField(
  sessionId: string,
  fieldName: string,
  params: Record<string, string | number>,
): Promise<RecalculateResponse> {
  const res = await fetch(`${API_BASE}/recalculate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      field_name: fieldName,
      params,
    }),
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(
      errorBody.message ||
        errorBody.detail ||
        `後端回傳錯誤狀態碼 ${res.status}`,
    );
  }

  return res.json();
}

/** 呼叫 GET /health，用來確認後端有沒有正常啟動 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}
