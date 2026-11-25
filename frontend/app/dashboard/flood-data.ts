import type { Location } from "./data";

export const categories = ["Low", "Moderate", "High", "Very High", "Insufficient Data"] as const;
export type RiskCategory = typeof categories[number];
export const riskColors: Record<RiskCategory, string> = {
  Low: "#53ca89", Moderate: "#e8c658", High: "#f29955", "Very High": "#f47180", "Insufficient Data": "#93a0af",
};
export const indexHelp = "Experimental score from 0 to 100. It measures the index factors on their configured scale.";
export const probabilityHelp = "Estimated chance of inundation within the 24-hour forecast window from an approved calibrated flood model.";

type Numbers = Record<string, number | null>;
export type Assessment = {
  id: number; location: string; issued_at: string; valid_until: string; created_at: string;
  risk_category: RiskCategory; risk_index: number | null; method_version: string; forecast_horizon_hours: number;
  assessment_status: string; validation_status: string; weight_coverage: number; missing_features: string[];
  factors: Record<string, { weight: number; inputs: Numbers; normalized: number | null; contribution_points: number | null }>;
  observed_rainfall: Numbers; forecast_rainfall: Numbers;
  source_references: Record<string, {url: string; resolution: string}>;
  data_freshness: Record<string, {available_at: string; last_valid_at?: string | null}>;
  excluded_factors: Record<string, string>;
};
export type PointRisk = { point: Location; assessment: Assessment | null; is_current: boolean };
export type FloodPrediction = {
  id?: number; location: string; issued_at: string; valid_until: string; flood_probability: number | null;
  risk_classification: string; model_version: string | null; model_validation_status: string;
  feature_contributions?: Record<string, {probability_change_from_median_probe: number}> | null;
};
export type Readiness = { status: string; inventory: Record<string, number>; blocking_inventory: string[] };
type Evaluation = {
  precision: number | null; recall: number | null; f1: number | null; pr_auc_average_precision: number | null;
  roc_auc: number | null; brier: number | null; confusion?: {tn: number; fp: number; fn: number; tp: number};
  calibration_curve?: {mean_probability: number; positive_fraction: number; count: number}[];
};
export type FloodMetrics = {
  status: string; version: string | null; readiness: Readiness;
  evaluation: {
    winner?: string; calibration?: string; test?: Evaluation;
    candidates?: {candidate: string; method: string; status?: string; calibrated_selection?: Evaluation}[];
    feature_importance?: Record<string, number>;
  } | null;
};
export type FloodProfiles = {
  complete_points: number; excluded_points: number; silhouette_in_sample: number; interpretation: string;
  assignments: {location: string; cluster_id: number; features: Record<string, number>}[];
};
export type FloodCoverage = {
  counts: Record<string, number>; label_counts: Record<string, number>;
  weather_daily: {location: string; source: string; first_date: string; last_date: string; days_with_rainfall: number; missing_days_between: number | string}[];
  weather_provider_grids: {feed: string; source: string; point: string; rows: number; first_valid: string; last_valid: string}[];
  weather_hourly_nulls: Record<string, number>[];
  terrain: {point: string; source: string; feature: string}[];
  hydrology: {station_key: string; variable: string; source: string; rows: number; first_valid: string; last_valid: string; missing_hours_between: number | string}[];
  events: {event_key: string; locality_as_reported: string; started_at: string; ended_before: string; source_ref: string}[];
};

export const label = (value: string) => value.replaceAll("_", " ");
export const activeAssessment = (row?: PointRisk) => row?.is_current ? row.assessment : null;
export const pointCategory = (row?: PointRisk): RiskCategory => activeAssessment(row)?.risk_category ?? "Insufficient Data";
export const formatProbability = (value: number | null | undefined) => value == null ? "Unavailable" :
  new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 1 }).format(value);
