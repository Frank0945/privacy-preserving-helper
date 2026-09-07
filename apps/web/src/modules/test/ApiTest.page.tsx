import { useState } from "react";
import { Layout } from "@/layouts";

import {
  analyzeFields,
  checkBackendHealth,
  recalculateField,
  type AnalyzeResponse,
  type FieldResult,
  type FieldSpec,
} from "./apiTestClient";

function emptyField(): FieldSpec {
  return {
    name: "",
    data_type: "text",
    format_rule: null,
    purpose: "內部使用",
    purpose_detail: null,
    is_key_field: false,
    sample_count: 10,
  };
}

const SAMPLE_FIELDS: FieldSpec[] = [
  {
    name: "身分證字號",
    data_type: "text",
    format_rule: null,
    purpose: "內部使用",
    purpose_detail: null,
    is_key_field: false,
    sample_count: 5,
  },
  {
    name: "姓名",
    data_type: "text",
    format_rule: null,
    purpose: "內部使用",
    purpose_detail: null,
    is_key_field: false,
    sample_count: 5,
  },
  {
    name: "年齡",
    data_type: "number",
    format_rule: null,
    purpose: "對外公開研究",
    purpose_detail: null,
    is_key_field: true,
    sample_count: 5,
  },
];

const ApiTestPage = () => {
  const [fields, setFields] = useState<FieldSpec[]>([emptyField()]);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [healthStatus, setHealthStatus] = useState<"unknown" | "ok" | "fail">(
    "unknown",
  );

  function updateField<K extends keyof FieldSpec>(
    index: number,
    key: K,
    value: FieldSpec[K],
  ) {
    setFields((prev) =>
      prev.map((f, i) => (i === index ? { ...f, [key]: value } : f)),
    );
  }

  function addField() {
    setFields((prev) => [...prev, emptyField()]);
  }

  function removeField(index: number) {
    setFields((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleCheckHealth() {
    const ok = await checkBackendHealth();
    setHealthStatus(ok ? "ok" : "fail");
  }

  async function handleAnalyze() {
    const validFields = fields.filter((f) => f.name.trim() !== "");
    if (validFields.length === 0) {
      setError("請至少填寫一個欄位名稱");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await analyzeFields(validFields);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "未知錯誤");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Layout>
      <div style={styles.page}>
        <h1 style={styles.h1}>後端 API 測試頁</h1>
        <p style={styles.sub}>用來確認 /analyze 與 /recalculate 是否正常運作</p>

        <section style={styles.panel}>
          <button style={styles.secondaryBtn} onClick={handleCheckHealth}>
            測試連線 /health
          </button>
          {healthStatus === "ok" && (
            <span style={{ color: "#4caf7d", marginLeft: 10 }}>
              ✅ 連線正常
            </span>
          )}
          {healthStatus === "fail" && (
            <span style={{ color: "#e05c5c", marginLeft: 10 }}>
              ❌ 連不上後端
            </span>
          )}
        </section>

        <section style={styles.panel}>
          <h2 style={styles.h2}>欄位規格</h2>
          {fields.map((field, index) => (
            <FieldCard
              key={index}
              field={field}
              onChange={(key, value) => updateField(index, key, value)}
              onRemove={() => removeField(index)}
            />
          ))}
          <div style={{ display: "flex", gap: 10 }}>
            <button style={styles.secondaryBtn} onClick={addField}>
              ＋ 新增欄位
            </button>
            <button
              style={styles.secondaryBtn}
              onClick={() => setFields(SAMPLE_FIELDS)}
            >
              載入範例欄位
            </button>
          </div>
        </section>

        <button
          style={styles.primaryBtn}
          onClick={handleAnalyze}
          disabled={loading}
        >
          {loading ? "呼叫中...（會實際打到 Gemini）" : "送出分析"}
        </button>

        {error && <div style={styles.errorBar}>❌ {error}</div>}

        {result?.status === "need_clarification" && (
          <div style={styles.warnBar}>
            ⚠️ 需要澄清（來源：
            {result.source === "synthetic_data"
              ? "Task A 假資料生成"
              : "Task B 技術判斷"}
            ）
            <br />
            欄位「{result.field}」：{result.question}
          </div>
        )}

        {result?.status === "ok" && (
          <div>
            <div style={styles.okBar}>
              ✅ 分析成功，Session ID：{result.session_id}
            </div>
            {result.results.map((r) => (
              <ResultCard
                key={r.field_name}
                field={r}
                sessionId={result.session_id}
              />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
};

export default ApiTestPage;

// ---------------- 子元件：單一欄位的輸入卡片 ----------------

interface FieldCardProps {
  field: FieldSpec;
  onChange: <K extends keyof FieldSpec>(key: K, value: FieldSpec[K]) => void;
  onRemove: () => void;
}

function FieldCard({ field, onChange, onRemove }: FieldCardProps) {
  return (
    <div style={styles.fieldCard}>
      <button style={styles.removeBtn} onClick={onRemove}>
        移除 ✕
      </button>

      <div style={styles.row}>
        <div style={{ flex: 1 }}>
          <label style={styles.label}>欄位名稱</label>
          <input
            style={styles.input}
            value={field.name}
            onChange={(e) => onChange("name", e.target.value)}
            placeholder="例如：身分證字號"
          />
        </div>
        <div style={{ flex: 1 }}>
          <label style={styles.label}>型態</label>
          <select
            style={styles.input}
            value={field.data_type}
            onChange={(e) => onChange("data_type", e.target.value)}
          >
            <option value="text">text</option>
            <option value="number">number</option>
            <option value="date">date</option>
          </select>
        </div>
      </div>

      <label style={styles.label}>格式規則（選填）</label>
      <input
        style={styles.input}
        value={field.format_rule ?? ""}
        onChange={(e) => onChange("format_rule", e.target.value || null)}
        placeholder="例如：英文字母+9碼數字"
      />

      <div style={styles.row}>
        <div style={{ flex: 1 }}>
          <label style={styles.label}>使用目的</label>
          <select
            style={styles.input}
            value={field.purpose}
            onChange={(e) =>
              onChange("purpose", e.target.value as FieldSpec["purpose"])
            }
          >
            <option value="內部使用">內部使用</option>
            <option value="跨部門提供">跨部門提供</option>
            <option value="對外公開研究">對外公開研究</option>
            <option value="其他">其他</option>
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={styles.label}>範例筆數</label>
          <select
            style={styles.input}
            value={field.sample_count}
            onChange={(e) =>
              onChange(
                "sample_count",
                Number(e.target.value) as FieldSpec["sample_count"],
              )
            }
          >
            <option value={5}>5</option>
            <option value={10}>10</option>
            <option value={20}>20</option>
          </select>
        </div>
      </div>

      {field.purpose === "其他" && (
        <>
          <label style={styles.label}>使用目的補充說明</label>
          <input
            style={styles.input}
            value={field.purpose_detail ?? ""}
            onChange={(e) => onChange("purpose_detail", e.target.value || null)}
            placeholder="請描述實際用途"
          />
        </>
      )}

      <label style={{ fontSize: 13, color: "#e4e6eb" }}>
        <input
          type="checkbox"
          checked={field.is_key_field}
          onChange={(e) => onChange("is_key_field", e.target.checked)}
          style={{ marginRight: 6 }}
        />
        是否為關鍵分析欄位
      </label>
    </div>
  );
}

// ---------------- 子元件：單一欄位的結果卡片（含滑桿重算） ----------------

interface ResultCardProps {
  field: FieldResult;
  sessionId: string;
}

function ResultCard({ field, sessionId }: ResultCardProps) {
  const [processedSamples, setProcessedSamples] = useState(
    field.processed_samples,
  );
  const [excelFormula, setExcelFormula] = useState(field.excel_formula);
  const [params, setParams] = useState(field.adjustable_params);

  async function handleParamChange(key: string, value: string | number) {
    const newParams = { ...params, [key]: value };
    setParams(newParams);

    try {
      const res = await recalculateField(
        sessionId,
        field.field_name,
        newParams,
      );
      setProcessedSamples(res.processed_samples);
      setExcelFormula(res.excel_formula);
    } catch (e) {
      console.error("重算失敗：", e);
    }
  }

  return (
    <div style={styles.resultCard}>
      <h3 style={{ margin: "0 0 8px" }}>
        {field.field_name} <span style={styles.tag}>{field.technique}</span>
      </h3>
      <div style={styles.reasonText}>💡 {field.reason}</div>
      <div style={styles.reasonText}>建議參數：{field.suggested_param}</div>

      <div style={styles.compareGrid}>
        <div style={styles.compareCol}>
          <div style={styles.compareLabel}>處理前</div>
          {field.original_samples.map((v, i) => (
            <div key={i} style={styles.compareVal}>
              {v}
            </div>
          ))}
        </div>
        <div style={styles.compareCol}>
          <div style={styles.compareLabel}>處理後</div>
          {processedSamples.map((v, i) => (
            <div key={i} style={styles.compareVal}>
              {v}
            </div>
          ))}
        </div>
      </div>

      <div style={styles.formula}>📎 {excelFormula}</div>

      <ParamControls
        technique={field.technique}
        params={params}
        onChange={handleParamChange}
      />
    </div>
  );
}

// ---------------- 子元件：依技術種類顯示對應的滑桿控制項 ----------------

interface ParamControlsProps {
  technique: FieldResult["technique"];
  params: Record<string, string | number>;
  onChange: (key: string, value: string | number) => void;
}

function ParamControls({ technique, params, onChange }: ParamControlsProps) {
  if (technique === "mask") {
    return (
      <div style={styles.paramsBox}>
        <div style={styles.paramRow}>
          <label style={styles.paramLabel}>遮罩位置</label>
          <select
            style={{ ...styles.input, marginBottom: 0 }}
            value={String(params.position ?? "right")}
            onChange={(e) => onChange("position", e.target.value)}
          >
            <option value="right">右側</option>
            <option value="left">左側</option>
            <option value="middle">中間</option>
          </select>
        </div>
        <div style={styles.paramRow}>
          <label style={styles.paramLabel}>遮罩位數</label>
          <input
            type="range"
            min={1}
            max={10}
            value={Number(params.length ?? 4)}
            onChange={(e) => onChange("length", Number(e.target.value))}
            style={{ flex: 1, margin: "0 8px" }}
          />
          <span style={styles.paramValue}>{params.length ?? 4}</span>
        </div>
      </div>
    );
  }

  if (technique === "generalize") {
    return (
      <div style={styles.paramsBox}>
        <div style={styles.paramRow}>
          <label style={styles.paramLabel}>區間粗細</label>
          <input
            type="range"
            min={1}
            max={20}
            value={Number(params.bucket_size ?? 5)}
            onChange={(e) => onChange("bucket_size", Number(e.target.value))}
            style={{ flex: 1, margin: "0 8px" }}
          />
          <span style={styles.paramValue}>{params.bucket_size ?? 5}</span>
        </div>
      </div>
    );
  }

  if (technique === "k_anonymity_group") {
    return (
      <div style={styles.paramsBox}>
        <div style={styles.paramRow}>
          <label style={styles.paramLabel}>k 值</label>
          <input
            type="range"
            min={2}
            max={10}
            value={Number(params.k ?? 5)}
            onChange={(e) => onChange("k", Number(e.target.value))}
            style={{ flex: 1, margin: "0 8px" }}
          />
          <span style={styles.paramValue}>{params.k ?? 5}</span>
        </div>
      </div>
    );
  }

  if (technique === "differential_privacy") {
    return (
      <div style={styles.paramsBox}>
        <div style={styles.paramRow}>
          <label style={styles.paramLabel}>epsilon</label>
          <input
            type="range"
            min={0.1}
            max={5}
            step={0.1}
            value={Number(params.epsilon ?? 1.0)}
            onChange={(e) => onChange("epsilon", Number(e.target.value))}
            style={{ flex: 1, margin: "0 8px" }}
          />
          <span style={styles.paramValue}>{params.epsilon ?? 1.0}</span>
        </div>
      </div>
    );
  }

  return null;
}

// ---------------- 樣式 ----------------

const styles: Record<string, React.CSSProperties> = {
  page: {
    background: "#0f1117",
    color: "#e4e6eb",
    minHeight: "100vh",
    padding: 24,
    fontFamily:
      "-apple-system, 'PingFang TC', 'Microsoft JhengHei', sans-serif",
    maxWidth: 900,
    margin: "0 auto",
  },
  h1: { fontSize: 20, marginBottom: 4 },
  h2: { fontSize: 15, color: "#8b8f9c", marginTop: 0 },
  sub: { color: "#8b8f9c", fontSize: 13, marginBottom: 20 },
  panel: {
    background: "#1a1d27",
    border: "1px solid #2a2e3a",
    borderRadius: 10,
    padding: 18,
    marginBottom: 16,
  },
  label: { display: "block", fontSize: 13, color: "#8b8f9c", marginBottom: 4 },
  input: {
    width: "100%",
    background: "#0f1117",
    border: "1px solid #2a2e3a",
    color: "#e4e6eb",
    padding: "8px 10px",
    borderRadius: 6,
    fontSize: 14,
    marginBottom: 10,
  },
  row: { display: "flex", gap: 10 },
  primaryBtn: {
    background: "#5b8def",
    color: "white",
    border: "none",
    padding: "12px 16px",
    borderRadius: 6,
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer",
    width: "100%",
  },
  secondaryBtn: {
    background: "transparent",
    border: "1px solid #2a2e3a",
    color: "#e4e6eb",
    padding: "9px 16px",
    borderRadius: 6,
    fontSize: 14,
    cursor: "pointer",
  },
  fieldCard: {
    border: "1px solid #2a2e3a",
    borderRadius: 8,
    padding: 14,
    marginBottom: 12,
    position: "relative",
  },
  removeBtn: {
    position: "absolute",
    top: 10,
    right: 10,
    background: "transparent",
    border: "none",
    color: "#8b8f9c",
    fontSize: 12,
    cursor: "pointer",
  },
  errorBar: {
    background: "rgba(224,92,92,0.15)",
    color: "#e05c5c",
    border: "1px solid rgba(224,92,92,0.3)",
    padding: "10px 14px",
    borderRadius: 6,
    fontSize: 13,
    marginTop: 16,
  },
  warnBar: {
    background: "rgba(217,164,65,0.15)",
    color: "#d9a441",
    border: "1px solid rgba(217,164,65,0.3)",
    padding: "10px 14px",
    borderRadius: 6,
    fontSize: 13,
    marginTop: 16,
  },
  okBar: {
    background: "rgba(76,175,125,0.15)",
    color: "#4caf7d",
    border: "1px solid rgba(76,175,125,0.3)",
    padding: "10px 14px",
    borderRadius: 6,
    fontSize: 13,
    marginTop: 16,
    marginBottom: 14,
  },
  resultCard: {
    border: "1px solid #2a2e3a",
    borderRadius: 8,
    padding: 16,
    marginBottom: 14,
  },
  tag: {
    display: "inline-block",
    background: "rgba(91,141,239,0.15)",
    color: "#5b8def",
    fontSize: 11,
    padding: "2px 8px",
    borderRadius: 10,
    marginLeft: 6,
  },
  reasonText: { fontSize: 13, color: "#8b8f9c", margin: "8px 0" },
  compareGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 12,
    margin: "10px 0",
  },
  compareCol: {
    background: "#0f1117",
    borderRadius: 6,
    padding: 10,
    fontSize: 13,
  },
  compareLabel: { fontSize: 11, color: "#8b8f9c", marginBottom: 6 },
  compareVal: { padding: "2px 0", fontFamily: "monospace" },
  formula: {
    background: "#0f1117",
    border: "1px dashed #2a2e3a",
    borderRadius: 6,
    padding: "8px 10px",
    fontFamily: "monospace",
    fontSize: 12.5,
    color: "#a7c7ff",
    wordBreak: "break-all",
    marginTop: 8,
  },
  paramsBox: { marginTop: 10, paddingTop: 10, borderTop: "1px solid #2a2e3a" },
  paramRow: { display: "flex", alignItems: "center", marginBottom: 6 },
  paramLabel: { width: 100, fontSize: 13, color: "#8b8f9c" },
  paramValue: {
    width: 60,
    textAlign: "right",
    fontFamily: "monospace",
    fontSize: 12,
  },
};
