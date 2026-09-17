import { useEffect, useRef, useState } from "react";
import type { ProcessedField } from "@/api/gen";
import { mapParamToFormula } from "@/lib/utils";
import {
  DetailedCellError,
  HyperFormula,
  NotAFormulaError,
  type NoErrorCellValue,
} from "hyperformula";

import type { ChangedFieldConfig, ChangedFieldMap } from "./comparison";

export type ProcessedSamples = Record<string, NoErrorCellValue[]>;

export const getSampleSize = (fields: ProcessedField[]) =>
  fields[0]?.sample_before.length ?? 0;

/**
 * Get the config that will actually be used for calculation.
 *
 * changedFieldMap takes priority over the backend-provided default config.
 */
const getEffectiveConfig = (
  field: ProcessedField,
  changedFieldMap: ChangedFieldMap,
): ChangedFieldConfig | null => {
  const changed = changedFieldMap[field.field_id];
  const variant = changed?.variant ?? field.default_variant;
  const param = changed?.param ?? field.param.default;

  return variant && param != null ? { variant, param } : null;
};

const isSameConfig = (
  a: ChangedFieldConfig | null,
  b: ChangedFieldConfig | null,
) => a === b || (a?.param === b?.param && a?.variant === b?.variant);

const buildSheetData = (fields: ProcessedField[]) => {
  const sampleSize = getSampleSize(fields);

  return [
    fields.map((field) => field.field_name),
    ...Array.from({ length: sampleSize }, (_, rowIndex) =>
      fields.map((field) => field.sample_before[rowIndex] ?? null),
    ),
  ];
};

const calculateFieldSamples = (
  hf: HyperFormula,
  field: ProcessedField,
  columnIndex: number,
  sampleSize: number,
  config: ChangedFieldConfig | null,
): NoErrorCellValue[] => {
  if (!config) {
    return Array.from({ length: sampleSize }, () => null);
  }

  return Array.from({ length: sampleSize }, (_, rowIndex) => {
    const cellAddress = hf.simpleCellAddressToString(
      { sheet: 0, row: rowIndex + 1, col: columnIndex },
      { includeSheetName: false },
    );

    if (!cellAddress) {
      return null;
    }

    const formula = mapParamToFormula(
      field.excel_formulas,
      config.variant,
      config.param,
      cellAddress,
    );

    if (!formula) {
      return null;
    }

    try {
      const result = hf.calculateFormula(formula, 0);

      if (result instanceof DetailedCellError) {
        return result.value;
      }

      // Array formulas aren't supported in this UI.
      if (Array.isArray(result)) {
        return null;
      }

      return result;
    } catch (error) {
      if (error instanceof NotAFormulaError) {
        console.error(
          `Invalid formula for field "${field.field_name}":`,
          formula,
          error,
        );

        return "#ERROR!";
      }

      throw error;
    }
  });
};

/** Recalculate every field and return a fresh ProcessedSamples map. */
const calculateAllSamples = (
  hf: HyperFormula,
  fields: ProcessedField[],
  changedFieldMap: ChangedFieldMap,
  sampleSize: number,
): ProcessedSamples =>
  fields.reduce<ProcessedSamples>((acc, field, columnIndex) => {
    acc[field.field_id] = calculateFieldSamples(
      hf,
      field,
      columnIndex,
      sampleSize,
      getEffectiveConfig(field, changedFieldMap),
    );

    return acc;
  }, {});

const useProcessedSamples = (
  fields: ProcessedField[],
  changedFieldMap: ChangedFieldMap,
  enabled: boolean,
) => {
  const [processedSamples, setProcessedSamples] = useState<ProcessedSamples>(
    {},
  );

  const hfRef = useRef<HyperFormula | null>(null);

  // Used to detect whether the source sheet changed; `fields` must be
  // updated immutably for this reference comparison to work.
  const previousFieldsRef = useRef<ProcessedField[] | null>(null);
  const previousChangedFieldMapRef = useRef<ChangedFieldMap>({});

  useEffect(() => {
    if (!enabled || fields.length === 0) {
      hfRef.current?.destroy();
      hfRef.current = null;
      previousFieldsRef.current = null;
      previousChangedFieldMapRef.current = {};

      setProcessedSamples({});

      return;
    }

    const sampleSize = getSampleSize(fields);

    // Source data changed (or the sheet doesn't exist yet): rebuild the
    // HyperFormula sheet and recalculate every field.
    if (previousFieldsRef.current !== fields || !hfRef.current) {
      hfRef.current?.destroy();

      const hf = HyperFormula.buildFromArray(buildSheetData(fields), {
        licenseKey: "gpl-v3",
      });

      hfRef.current = hf;
      previousFieldsRef.current = fields;
      previousChangedFieldMapRef.current = changedFieldMap;

      setProcessedSamples(
        calculateAllSamples(hf, fields, changedFieldMap, sampleSize),
      );

      return;
    }

    // Source data is unchanged: reuse the sheet and only recalculate
    // fields whose effective config actually changed.
    const hf = hfRef.current;
    const previousChangedFieldMap = previousChangedFieldMapRef.current;

    previousChangedFieldMapRef.current = changedFieldMap;

    const changedFields = fields
      .map((field, columnIndex) => ({
        field,
        columnIndex,
        config: getEffectiveConfig(field, changedFieldMap),
        previousConfig: getEffectiveConfig(field, previousChangedFieldMap),
      }))
      .filter(
        ({ config, previousConfig }) => !isSameConfig(config, previousConfig),
      );

    // changedFieldMap may be a new object reference with identical values.
    if (changedFields.length === 0) {
      return;
    }

    setProcessedSamples((previous) => {
      const next = { ...previous };

      changedFields.forEach(({ field, columnIndex, config }) => {
        next[field.field_id] = calculateFieldSamples(
          hf,
          field,
          columnIndex,
          sampleSize,
          config,
        );
      });

      return next;
    });
  }, [fields, changedFieldMap, enabled]);

  // Component unmount cleanup.
  useEffect(
    () => () => {
      hfRef.current?.destroy();
      hfRef.current = null;
    },
    [],
  );

  return processedSamples;
};

export default useProcessedSamples;
